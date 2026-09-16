"""Turn a list of missing skills into a plan for closing them.

``MatchCalculator`` already answers *what* is missing. That is the easy half,
and on its own it is not much use: being told you lack LangGraph, Kubernetes
and SQL does not tell you which one to open a tutorial for on Monday morning.

This module answers the harder half - which gaps actually cost you the job,
which are cheap to close, and roughly how long each will take given what you
already know. The central idea is that **learning time is not a property of a
skill, it is a property of the distance between a skill and what you already
have**. Someone who knows LangChain can pick up LangGraph in a week; someone
who has never touched an LLM framework cannot. So every estimate here starts
from a base cost and is discounted by the related skills found on the resume.

Design notes:

- **No LLM.** Every number is derived from lookup tables and the resume, so the
  same input always gives the same plan and it works offline. The tables are
  editable in one place rather than buried in prompt text.
- **No invented URLs.** Resources are named, not linked. A confidently wrong
  URL is worse than a name the reader can search for, and link rot is certain.
- **Estimates are calendar days of part-time study**, not full-time days. They
  are deliberately round numbers; the honest precision here is low, and a plan
  that claims 13.5 days invites a trust it has not earned.

Example:
    >>> report = gap_detector.detect_gaps(resume_data, job_analysis, match_data)
    >>> report["priority_order"][0]
    'LangGraph'
    >>> report["critical_gaps"][0]["learning_time_days"]
    7
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from utils.logger import get_logger, observed
from utils.skills import (
    KNOWN_SKILLS,
    find_skills,
    match_skill,
    normalise_skill,
)
from utils.validation import as_dict

logger = get_logger(__name__)

__all__ = [
    "GapDetectorAgent",
    "gap_detector",
    "SKILL_FAMILIES",
    "BASE_LEARNING_DAYS",
    "DEFAULT_LEARNING_DAYS",
    "CRITICAL",
    "IMPORTANT",
    "NICE_TO_HAVE",
]


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
CRITICAL = "CRITICAL"
IMPORTANT = "IMPORTANT"
NICE_TO_HAVE = "NICE_TO_HAVE"

_IMPORTANCE_RANK = {CRITICAL: 0, IMPORTANT: 1, NICE_TO_HAVE: 2}

#: A gap this cheap is worth closing before you apply, not after.
QUICK_WIN_DAYS = 7

#: Nothing is learnable in under two days; the floor stops discounts reaching zero.
MINIMUM_DAYS = 2

#: What we assume when a skill is not in the table below - a genuinely new
#: concept with no shortcut. The brief calls for exactly this.
DEFAULT_LEARNING_DAYS = 30


# --------------------------------------------------------------------------- #
# Skill families
# --------------------------------------------------------------------------- #
#: Skills that share a family transfer to one another. This is the table that
#: makes the estimates useful: knowing *any* member of a family means the
#: vocabulary, the mental model and usually the tooling are already familiar,
#: so a sibling skill costs roughly half what it would cold.
#:
#: Membership is deliberately generous - the cost of a slightly optimistic
#: estimate is smaller than the cost of telling someone a skill they are one
#: step away from will take them a month.
SKILL_FAMILIES: Dict[str, Set[str]] = {
    "llm_frameworks": {
        "langchain", "langgraph", "llamaindex", "rag", "llm", "ollama",
        "hugging face", "prompt engineering", "mcp",
    },
    "vector_stores": {
        "vector database", "chromadb", "pinecone", "embeddings", "faiss",
        "elasticsearch", "weaviate", "qdrant",
    },
    "ml_frameworks": {
        "pytorch", "tensorflow", "keras", "scikit-learn", "machine learning",
        "deep learning", "computer vision", "nlp",
    },
    "data_engineering": {
        "pandas", "numpy", "spark", "airflow", "kafka", "snowflake", "etl",
    },
    "databases": {
        "sql", "postgresql", "mysql", "sqlite", "mongodb", "redis", "nosql",
    },
    "containers": {
        "docker", "kubernetes", "podman", "helm", "containerisation",
    },
    "infrastructure": {
        "terraform", "ansible", "ci/cd", "jenkins", "github actions", "nginx",
        "linux", "devops",
    },
    "cloud": {"aws", "azure", "gcp", "cloud"},
    "backend_web": {
        "fastapi", "django", "flask", "rest", "graphql", "grpc",
        "microservices", "node.js", "express",
    },
    "frontend_web": {
        "react", "vue", "angular", "next.js", "svelte", "javascript",
        "typescript", "html", "css",
    },
    "typed_languages": {"java", "c#", "go", "rust", "kotlin", "scala", "typescript"},
    "scripting_languages": {"python", "ruby", "php", "javascript", "bash"},
    "engineering_practice": {
        "git", "agile", "scrum", "tdd", "unit testing", "system design",
        "code review", "pair programming",
    },
}

#: Families where the members are close cousins rather than distant relatives.
#: A second discount applies here: Docker to Kubernetes is a smaller leap than
#: Python to Rust, even though both pairs share a family.
_TIGHT_FAMILIES = {"llm_frameworks", "vector_stores", "containers", "databases"}


# --------------------------------------------------------------------------- #
# Learning cost
# --------------------------------------------------------------------------- #
#: Calendar days of part-time study to reach "can use this at work without
#: supervision" - not mastery, and not a weekend skim. Absent from this table
#: means DEFAULT_LEARNING_DAYS.
BASE_LEARNING_DAYS: Dict[str, int] = {
    # Tools you can be productive with quickly
    "git": 5, "rest": 5, "json": 2, "bash": 7, "linux": 14,
    "postman": 2, "markdown": 1,
    # Frameworks and libraries - a fortnight of evenings
    "fastapi": 10, "flask": 7, "django": 21, "express": 7,
    "langchain": 14, "langgraph": 14, "llamaindex": 14, "mcp": 10,
    "pandas": 10, "numpy": 7, "scikit-learn": 14,
    "react": 21, "vue": 14, "angular": 30, "next.js": 14, "svelte": 10,
    "pytest": 5, "unit testing": 7, "tdd": 14,
    # Databases and stores
    "sql": 14, "postgresql": 14, "mysql": 14, "sqlite": 5, "mongodb": 10,
    "redis": 7, "elasticsearch": 21,
    "chromadb": 5, "pinecone": 5, "faiss": 7, "vector database": 10,
    "embeddings": 7,
    # Infrastructure - genuinely large surfaces
    "docker": 10, "kubernetes": 30, "terraform": 21, "ansible": 14,
    "ci/cd": 10, "jenkins": 14, "github actions": 7, "nginx": 7,
    "aws": 30, "azure": 30, "gcp": 30,
    # Concepts, not tools. These take real time and cannot be crammed.
    "rag": 14, "llm": 21, "prompt engineering": 10,
    "machine learning": 90, "deep learning": 90, "nlp": 60,
    "computer vision": 60, "system design": 60, "microservices": 21,
    "agile": 5, "scrum": 5,
    # Languages
    "python": 45, "javascript": 45, "typescript": 21, "java": 60,
    "go": 30, "rust": 60, "c++": 90, "c#": 60, "ruby": 30, "scala": 45,
    "kotlin": 30, "swift": 30, "php": 30,
    # Frameworks with a steep on-ramp
    "pytorch": 45, "tensorflow": 45, "keras": 21, "spark": 30,
    "airflow": 21, "kafka": 21, "snowflake": 21, "graphql": 14, "grpc": 14,
    "hugging face": 14, "ollama": 3,
}

#: Skills whose usual spelling is not what `.title()` produces.
_DISPLAY_NAMES: Dict[str, str] = {
    "ci/cd": "CI/CD", "aws": "AWS", "gcp": "GCP", "sql": "SQL",
    "nosql": "NoSQL", "rest": "REST", "graphql": "GraphQL", "grpc": "gRPC",
    "html": "HTML", "css": "CSS", "llm": "LLM", "nlp": "NLP",
    "rag": "RAG", "mcp": "MCP", "tdd": "TDD", "etl": "ETL",
    "api": "API", "ui": "UI", "ux": "UX",
    "javascript": "JavaScript", "typescript": "TypeScript",
    "node.js": "Node.js", "next.js": "Next.js", "c++": "C++", "c#": "C#",
    "postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite",
    "mongodb": "MongoDB", "chromadb": "ChromaDB", "faiss": "FAISS",
    "langchain": "LangChain", "langgraph": "LangGraph",
    "llamaindex": "LlamaIndex", "pytorch": "PyTorch",
    "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn",
    "fastapi": "FastAPI", "github actions": "GitHub Actions",
    "hugging face": "Hugging Face", "devops": "DevOps",
    "openai": "OpenAI", "gpt": "GPT",
}

#: Official documentation, and nothing else.
#:
#: The module's rule is "no invented URLs", and it stands. These are not
#: invented: every one was requested and returned 200 before being written
#: here, and each points at a project's own canonical documentation root
#: rather than a deep link into a versioned page, because roots are what
#: survive. A skill absent from this table gets a named resource to search
#: for, exactly as before -- a missing link is a small inconvenience, while a
#: confidently wrong one costs the reader their trust in every other line.
_DOC_URLS: Dict[str, str] = {
    "langgraph": "https://langchain-ai.github.io/langgraph/",
    "langchain": "https://python.langchain.com/docs/introduction/",
    "docker": "https://docs.docker.com/get-started/",
    "kubernetes": "https://kubernetes.io/docs/home/",
    "chromadb": "https://docs.trychroma.com/",
    "fastapi": "https://fastapi.tiangolo.com/",
    "aws": "https://docs.aws.amazon.com/",
    "postgresql": "https://www.postgresql.org/docs/",
    "pytorch": "https://pytorch.org/docs/stable/index.html",
    "hugging face": "https://huggingface.co/docs",
    "pinecone": "https://docs.pinecone.io/",
    "ollama": "https://ollama.com/",
    "terraform": "https://developer.hashicorp.com/terraform/docs",
    "github actions": "https://docs.github.com/en/actions",
    "scikit-learn": "https://scikit-learn.org/stable/",
    "pandas": "https://pandas.pydata.org/docs/",
    "numpy": "https://numpy.org/doc/stable/",
    "git": "https://git-scm.com/doc",
    "tensorflow": "https://www.tensorflow.org/api_docs",
}

#: One thing to build per skill. A project beats a tutorial in an interview:
#: it gives the candidate something concrete to describe, and describing it is
#: what they will actually be asked to do.
#:
#: Each is deliberately small enough to finish in the learning time estimated
#: for that skill, because an unfinished project is worth less than none.
_PRACTICE_PROJECTS: Dict[str, str] = {
    "langgraph": "Rebuild an existing chain as a graph with one conditional edge and one cycle, so you can explain why a graph beat a chain",
    "langchain": "Build a retrieval chain over documents you actually own, then measure what it gets wrong",
    "rag": "Index 50 of your own documents and log every query the retriever answers badly - the failures are the interesting part",
    "vector database": "Load the same embeddings into two stores and compare recall and latency on identical queries",
    "chromadb": "Index a folder of notes, add metadata filtering, and search by meaning rather than keyword",
    "pinecone": "Move an existing local index to Pinecone and note what had to change",
    "embeddings": "Embed 200 sentences, cluster them, and see whether the clusters match your own intuition",
    "docker": "Containerise a project you already have, including its database, and get it running from a single compose command",
    "kubernetes": "Deploy a two-service app locally with kind, then survive deliberately deleting a pod",
    "ci/cd": "Add a pipeline to one of your repositories that runs tests on every push and refuses to merge a red build",
    "github actions": "Automate the tests and linting for an existing repository of yours",
    "terraform": "Define one small piece of real infrastructure, destroy it, and recreate it from the same file",
    "aws": "Deploy one working service end to end - a container, a database and a domain - and read the bill afterwards",
    "sql": "Take a dataset you care about, load it, and answer five questions that need joins and aggregation",
    "postgresql": "Migrate a project off SQLite and onto PostgreSQL, indexes included",
    "mongodb": "Model the same data relationally and as documents, then write the queries both ways",
    "fastapi": "Put an API in front of something you have already built, with validation and generated docs",
    "pytorch": "Train a small classifier on your own data and write down why it fails on the cases it fails on",
    "machine learning": "Take one dataset from raw to evaluated model, and keep an honest record of every result",
    "nlp": "Build a classifier for text you understand well enough to grade its mistakes yourself",
    "mcp": "Expose one tool you already use through an MCP server and call it from a client",
    "spark": "Rewrite a pandas job that no longer fits in memory",
    "airflow": "Schedule a real multi-step job of yours with retries and alerting",
    "kafka": "Produce and consume a stream, then deliberately kill the consumer and watch what happens",
    "microservices": "Split one of your own services in two and feel the cost of the network between them",
    "system design": "Write the design document for a system you have already built, then have someone attack it",
    "prompt engineering": "Take one prompt and evaluate ten variants against a fixed set of cases",
    "git": "Practise the recovery paths - rebase, bisect, and undoing a bad merge - on a throwaway clone",
}

#: Named starting points. No URLs on purpose - see the module docstring.
_RESOURCES: Dict[str, List[str]] = {
    "langgraph": [
        "Official LangGraph documentation - start with the state and node concepts",
        "LangChain Academy: Introduction to LangGraph",
        "Build a multi-step agent with a cycle and a conditional edge",
    ],
    "langchain": [
        "Official LangChain documentation - chains, tools and retrievers",
        "Build a retrieval chain over your own documents",
    ],
    "kubernetes": [
        "Kubernetes official tutorials - pods, deployments and services first",
        "Kubernetes the Hard Way (once the basics are comfortable)",
        "Run a local cluster with kind or minikube and deploy a real app",
    ],
    "docker": [
        "Docker official 'Get Started' guide",
        "Write a Dockerfile and a docker-compose file for a project you already have",
    ],
    "sql": [
        "SQLBolt or Mode's SQL tutorial for the query fundamentals",
        "Practise joins and aggregation on a real dataset",
        "Learn EXPLAIN and how an index changes a query plan",
    ],
    "pinecone": [
        "Pinecone official quickstart and the index-design guide",
        "Port an existing vector search from a local store to Pinecone",
    ],
    "chromadb": [
        "Chroma official getting-started guide",
        "Index a document set and compare retrieval quality against keyword search",
    ],
    "ci/cd": [
        "GitHub Actions documentation - workflows, jobs and steps",
        "Add a pipeline that runs your tests on every push",
        "Extend it to build and publish an artefact",
    ],
    "aws": [
        "AWS Cloud Practitioner Essentials for the vocabulary",
        "Deploy one small service end to end (S3, Lambda, or ECS)",
    ],
    "terraform": [
        "HashiCorp's official Terraform tutorials",
        "Reproduce infrastructure you built by hand, in code",
    ],
    "fastapi": [
        "FastAPI official tutorial - it is unusually good",
        "Build an API with request validation and automatic docs",
    ],
    "react": [
        "The official React docs' Learn section",
        "Build a small app with state, effects and a data fetch",
    ],
    "rag": [
        "Read a primer on retrieval-augmented generation end to end",
        "Build a question-answering system over documents you care about",
        "Learn how chunking and embedding choice change the answers",
    ],
    "machine learning": [
        "Andrew Ng's Machine Learning Specialisation for the foundations",
        "Work through a supervised learning problem on a real dataset",
        "Learn to read a confusion matrix and explain overfitting",
    ],
    "kafka": [
        "Confluent's Kafka fundamentals course",
        "Produce and consume from a topic in a small project",
    ],
    "mcp": [
        "Model Context Protocol specification and the official quickstart",
        "Build a small MCP server exposing one tool",
    ],
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _display(skill: str) -> str:
    """Present a canonical skill the way a human would write it."""
    key = skill.strip().lower()
    if key in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[key]
    return " ".join(word.capitalize() for word in key.split())


def _clean(values: Any) -> List[str]:
    """Normalise anything list-shaped into lowercase canonical skill names."""
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    seen: List[str] = []
    for value in values:
        name = normalise_skill(str(value))
        if name and name not in seen:
            seen.append(name)
    return seen


def _families_of(skill: str) -> Set[str]:
    """Which families a skill belongs to. A skill may sit in more than one."""
    return {name for name, members in SKILL_FAMILIES.items() if skill in members}


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class GapDetectorAgent:
    """Works out which missing skills matter, and what to do about them.

    Like :class:`~agents.match_calculator.MatchCalculator`, this takes and
    returns plain dictionaries so it can be driven from the graph, an API
    handler or a test without any model objects in the way.
    """

    label = "Gap Detector"
    quick_win_days = QUICK_WIN_DAYS
    default_days = DEFAULT_LEARNING_DAYS

    # -- Public API --------------------------------------------------------- #
    @observed("detect_gaps")
    def detect_gaps(
        self,
        resume_data: Dict[str, Any],
        job_analysis: Dict[str, Any],
        match_data: Optional[Dict[str, Any]] = None,
        job_text: str = "",
    ) -> Dict[str, Any]:
        """Produce a prioritised, costed plan for closing the candidate's gaps.

        Args:
            resume_data: The candidate. Either ``{"skills": [...]}``, or
                ``{"resume_text": "..."}`` which will be scanned for skills.
            job_analysis: Output of :meth:`JobAnalyzerAgent.analyze` - uses
                ``required_skills``, ``preferred_skills`` and ``tech_stack``.
            match_data: Optional output of :meth:`MatchCalculator.calculate_match`.
                When present its ``missing`` lists are trusted, because it has
                already done alias-aware matching - without it we would report
                "PostgreSQL" as a gap for a candidate whose resume says
                "Postgres".
            job_text: Optional raw advert. Only used to count how often a skill
                is mentioned, which is the strongest available signal of how
                much the employer cares.

        Returns:
            A dict with ``critical_gaps``, ``nice_to_have_gaps``,
            ``priority_order``, ``total_learning_time_weeks`` and
            ``quick_wins``, plus a ``summary`` line and counts.
        """
        # Shape is coerced, not validated. An upstream agent that fell back may
        # hand us None, and losing the whole run over that would throw away the
        # stages that did succeed. See utils.validation.
        resume_data = as_dict(resume_data, "resume_data")
        job_analysis = as_dict(job_analysis, "job_analysis")
        match_data = as_dict(match_data, "match_data") or None
        job_text = job_text if isinstance(job_text, str) else ""

        user_skills = self._user_skills(resume_data)
        required = _clean(job_analysis.get("required_skills"))
        preferred = _clean(job_analysis.get("preferred_skills"))
        tech_stack = set(_clean(job_analysis.get("tech_stack")))
        advert = job_text or str(job_analysis.get("job_description") or "")

        missing_required, missing_preferred = self._categorize_gaps(
            required, user_skills, preferred=preferred, match_data=match_data
        )

        critical: List[Dict[str, Any]] = []
        nice_to_have: List[Dict[str, Any]] = []

        for skill in missing_required:
            gap = self._build_gap(
                skill,
                user_skills=user_skills,
                required=True,
                tech_stack=tech_stack,
                advert=advert,
            )
            # A required skill the advert barely mentions is still required,
            # but it does not deserve to outrank one mentioned eight times.
            critical.append(gap)

        for skill in missing_preferred:
            nice_to_have.append(
                self._build_gap(
                    skill,
                    user_skills=user_skills,
                    required=False,
                    tech_stack=tech_stack,
                    advert=advert,
                )
            )

        critical = self._prioritize_gaps(critical)
        nice_to_have = self._prioritize_gaps(nice_to_have)

        blocking_days = sum(g["learning_time_days"] for g in critical)
        weeks = self._to_weeks(blocking_days)

        report = {
            "critical_gaps": critical,
            "nice_to_have_gaps": nice_to_have,
            "priority_order": [g["skill"] for g in critical + nice_to_have],
            "total_learning_time_weeks": weeks,
            "quick_wins": self._quick_wins(critical + nice_to_have),
            "critical_count": len(critical),
            "nice_to_have_count": len(nice_to_have),
            "blocking_learning_days": blocking_days,
            "summary": self._summarise(critical, nice_to_have, weeks),
            "source": "rules",
        }

        logger.info(
            "Gap analysis: %d critical, %d nice-to-have, ~%d week(s) of study",
            len(critical),
            len(nice_to_have),
            weeks,
        )
        return report

    # -- Required-by-spec internals ----------------------------------------- #
    def _categorize_gaps(
        self,
        required: Sequence[str],
        found: Iterable[str],
        preferred: Sequence[str] = (),
        match_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Split what the job wants into critical gaps and nice-to-have gaps.

        Prefers the match calculator's verdict when it is available, because
        it matched aliases and near-spellings that a plain set difference
        would miss.
        """
        have = set(found)

        trusted = self._missing_from_match(match_data)
        if trusted is not None:
            critical = [s for s in required if s in trusted]
            optional = [s for s in preferred if s in trusted or not self._has(s, have)]
            return critical, [s for s in optional if s not in critical]

        critical = [s for s in required if not self._has(s, have)]
        optional = [
            s for s in preferred if not self._has(s, have) and s not in critical
        ]
        return critical, optional

    def _estimate_learning_time(
        self, skill: str, similar: Sequence[str] = ()
    ) -> int:
        """Days to become job-ready in `skill`, given related skills already held.

        The brief's two worked examples anchor the arithmetic: LangGraph with
        LangChain already on the resume should come out at 7 days, and a skill
        with nothing related should come out at 30.

        Args:
            skill: Canonical skill name.
            similar: Related skills the candidate already has. Passing none
                gives the undiscounted cost.
        """
        base = BASE_LEARNING_DAYS.get(skill, self.default_days)
        if not similar:
            return base

        tight = bool(_families_of(skill) & _TIGHT_FAMILIES)
        # One close relative halves the cost; several means the surrounding
        # ecosystem is familiar too, which halves it again but no further.
        if len(similar) >= 3 and tight:
            factor = 0.35
        elif len(similar) >= 3:
            factor = 0.5
        elif tight:
            factor = 0.5
        else:
            factor = 0.7

        return max(MINIMUM_DAYS, int(round(base * factor)))

    def _find_similar_skills(
        self, gap_skill: str, user_skills: Iterable[str]
    ) -> List[str]:
        """Skills the candidate has that make `gap_skill` easier to pick up.

        Two routes count as related: sharing a family, or being close enough
        in name that the matcher would have paired them (which catches
        spelling variants the family table does not list).
        """
        families = _families_of(gap_skill)
        related: List[str] = []

        for skill in user_skills:
            if skill == gap_skill:
                continue
            if families & _families_of(skill):
                related.append(skill)
                continue
            score, _reason = self._similarity(gap_skill, skill)
            if score >= 0.6:
                related.append(skill)

        return sorted(set(related))

    def _generate_learning_path(self, gap: Dict[str, Any]) -> Dict[str, Any]:
        """Turn a gap into named resources and a phased timeline.

        The phases are proportional to the estimate rather than fixed, so a
        five-day gap does not get the same four-stage plan as a ninety-day one.
        """
        skill = gap["skill_id"]
        days = gap["learning_time_days"]
        similar = gap.get("similar_skills_user_has") or []

        resources = list(_RESOURCES.get(skill, []))
        if not resources:
            resources = [
                f"Official {_display(skill)} documentation",
                f"One hands-on tutorial that builds something with {_display(skill)}",
            ]
        if similar:
            resources.append(
                f"Skim rather than study the basics - your {similar[0]} "
                "experience already covers much of the ground"
            )

        # Short gaps do not need a four-phase plan; long ones do.
        if days <= self.quick_win_days:
            splits = [("Learn the basics", 0.5), ("Build something small", 0.5)]
        elif days <= 21:
            splits = [
                ("Fundamentals", 0.3),
                ("Guided practice", 0.4),
                ("Portfolio project", 0.3),
            ]
        else:
            splits = [
                ("Fundamentals", 0.25),
                ("Guided practice", 0.3),
                ("Portfolio project", 0.3),
                ("Interview readiness", 0.15),
            ]

        timeline: List[Dict[str, Any]] = []
        cursor = 1
        for index, (phase, share) in enumerate(splits):
            length = max(1, int(round(days * share)))
            if index == len(splits) - 1:
                length = max(1, days - cursor + 1)
            timeline.append(
                {
                    "phase": phase,
                    "days": f"{cursor}-{cursor + length - 1}",
                    "goal": self._phase_goal(phase, skill),
                }
            )
            cursor += length

        return {
            "resources": resources,
            "timeline": timeline,
            # Both are None rather than a guess when the skill is not in the
            # tables, so a caller can tell "we have nothing for this" apart
            # from "here is something plausible".
            "documentation": _DOC_URLS.get(skill),
            "practice_project": _PRACTICE_PROJECTS.get(skill),
        }

    def _prioritize_gaps(self, gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Order gaps by impact: importance, then how loudly the advert asked.

        Ties break towards the cheapest, so where two gaps matter equally the
        candidate is pointed at the one they can finish first.
        """
        return sorted(
            gaps,
            key=lambda g: (
                _IMPORTANCE_RANK.get(g["importance"], 9),
                -g.get("mentions_in_job", 0),
                g["learning_time_days"],
                g["skill_id"],
            ),
        )

    # -- Supporting internals ----------------------------------------------- #
    def _build_gap(
        self,
        skill: str,
        user_skills: Set[str],
        required: bool,
        tech_stack: Set[str],
        advert: str,
    ) -> Dict[str, Any]:
        """Assemble one fully-costed gap entry."""
        similar = self._find_similar_skills(skill, user_skills)
        days = self._estimate_learning_time(skill, similar)
        mentions = self._count_mentions(skill, advert)
        importance = self._importance(skill, required, tech_stack, mentions)

        gap: Dict[str, Any] = {
            "skill": _display(skill),
            "skill_id": skill,
            "required": required,
            "user_has": False,
            "importance": importance,
            "why": self._why(skill, required, tech_stack, mentions),
            "mentions_in_job": mentions,
            "learning_time_days": days,
            "similar_skills_user_has": [_display(s) for s in similar],
        }

        path = self._generate_learning_path(gap)
        gap["learning_resources"] = path["resources"]
        gap["learning_path"] = path["timeline"]
        gap["documentation"] = path["documentation"]
        gap["practice_project"] = path["practice_project"]
        gap["recommendation"] = self._recommendation(gap)
        return gap

    def _user_skills(self, resume_data: Dict[str, Any]) -> Set[str]:
        """Everything the candidate can demonstrate, from whichever field holds it."""
        skills = set(_clean(resume_data.get("skills")))
        text = str(resume_data.get("resume_text") or "").strip()
        if text:
            skills.update(_clean(find_skills(text)))
        return skills

    def _missing_from_match(
        self, match_data: Optional[Dict[str, Any]]
    ) -> Optional[Set[str]]:
        """The skills the match calculator judged missing, if it ran.

        Returns ``None`` when there is nothing usable, which tells the caller
        to fall back to computing the difference itself.
        """
        if not match_data:
            return None

        breakdown = match_data.get("match_breakdown") or {}
        missing: Set[str] = set()
        seen_any = False

        for name in ("skills", "tech_stack"):
            component = breakdown.get(name) or {}
            value = component.get("missing")
            # Only the skill-style components hold lists. Experience and
            # education store prose such as "1 more years", which is not a
            # skill and must not become a gap.
            if isinstance(value, (list, tuple, set)):
                seen_any = True
                missing.update(_clean(list(value)))

        if not seen_any:
            top_level = match_data.get("missing_skills")
            if isinstance(top_level, (list, tuple, set)):
                return set(_clean(list(top_level)))
            return None

        return missing

    def _has(self, skill: str, user_skills: Set[str]) -> bool:
        """Does the candidate have this skill, allowing for aliases?"""
        if skill in user_skills:
            return True
        return match_skill(skill, user_skills) is not None

    def _similarity(self, left: str, right: str) -> Tuple[float, str]:
        """Name similarity, guarded so a matcher change cannot break the report."""
        try:
            from utils.skills import skill_similarity

            return skill_similarity(left, right)
        except Exception:  # noqa: BLE001 - relatedness is a nicety, not a duty
            logger.debug("Similarity failed for %r/%r", left, right, exc_info=True)
            return 0.0, "unavailable"

    def _count_mentions(self, skill: str, advert: str) -> int:
        """How many times the advert names this skill.

        Repetition is the clearest signal an employer gives about what they
        actually care about, and it costs nothing to read.
        """
        if not advert:
            return 0
        haystack = advert.lower()
        count = haystack.count(skill)
        if skill not in KNOWN_SKILLS:
            return count
        # Count common spellings too, so "K8s" and "Kubernetes" do not split
        # the tally between them.
        for alias in self._aliases(skill):
            if alias != skill:
                count += haystack.count(alias)
        return count

    @staticmethod
    def _aliases(skill: str) -> List[str]:
        try:
            from utils.skills import _ALIASES  # type: ignore[attr-defined]

            return list(_ALIASES.get(skill, []))
        except Exception:  # noqa: BLE001 - private table, treated as optional
            return []

    def _importance(
        self, skill: str, required: bool, tech_stack: Set[str], mentions: int
    ) -> str:
        """Grade a gap.

        Being listed as required is necessary but not sufficient for CRITICAL:
        adverts pad their requirements. Appearing in the core tech stack, or
        being named repeatedly, is what separates a real requirement from a
        wish.
        """
        if not required:
            return NICE_TO_HAVE
        if skill in tech_stack or mentions >= 2:
            return CRITICAL
        return IMPORTANT

    def _why(
        self, skill: str, required: bool, tech_stack: Set[str], mentions: int
    ) -> str:
        """Explain the grade in the employer's own terms."""
        reasons: List[str] = []
        if mentions >= 2:
            reasons.append(f"mentioned {mentions} times in the advert")
        elif mentions == 1:
            reasons.append("named in the advert")
        if skill in tech_stack:
            reasons.append("part of the core tech stack")
        if required:
            reasons.append("listed as a requirement")
        else:
            reasons.append("listed as preferred, not required")

        return _display(skill) + " is " + ", ".join(reasons) + "."

    def _recommendation(self, gap: Dict[str, Any]) -> str:
        """What to actually do, in one sentence."""
        name = gap["skill"]
        days = gap["learning_time_days"]
        similar = gap.get("similar_skills_user_has") or []

        if gap["importance"] == NICE_TO_HAVE:
            if days <= self.quick_win_days:
                return f"Cheap to add ({days} days) - worth it once the critical gaps are closed."
            return f"Good to learn but not a priority for this role (~{days} days)."

        if similar:
            return (
                f"Build one portfolio project using {name}. Your {similar[0]} "
                f"experience should get you there in about {days} days."
            )
        if days <= self.quick_win_days:
            return f"Close this before you apply - about {days} days of work."
        if days >= 60:
            return (
                f"{name} is a long road (~{days} days). Be honest about it in the "
                "application rather than trying to hide it."
            )
        return f"Add a {name} project to your portfolio - roughly {days} days."

    def _quick_wins(self, gaps: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gaps cheap enough to close before applying.

        Either genuinely small, or made small by something already on the
        resume - those are the ones worth doing this week.
        """
        wins: List[Dict[str, Any]] = []
        for gap in gaps:
            days = gap["learning_time_days"]
            similar = gap.get("similar_skills_user_has") or []
            if days > self.quick_win_days:
                continue
            if similar:
                why = f"You already know {', '.join(similar[:2])}, so this is a short step."
            else:
                why = f"{gap['skill']} is small enough to pick up in under a fortnight."
            wins.append(
                {
                    "skill": gap["skill"],
                    "skill_id": gap["skill_id"],
                    "why": why,
                    "learning_time_days": days,
                }
            )
        return sorted(wins, key=lambda w: w["learning_time_days"])

    @staticmethod
    def _to_weeks(days: int) -> int:
        """Calendar weeks, rounded up - a part week is still a week of your life."""
        if days <= 0:
            return 0
        return max(1, -(-days // 7))

    @staticmethod
    def _phase_goal(phase: str, skill: str) -> str:
        name = _display(skill)
        return {
            "Learn the basics": f"Understand what {name} does and when to reach for it.",
            "Build something small": f"Ship one working thing that uses {name}.",
            "Fundamentals": f"Work through the {name} documentation and a starter tutorial.",
            "Guided practice": "Rebuild a worked example, then change it and see what breaks.",
            "Portfolio project": f"Build something of your own with {name} and push it publicly.",
            "Interview readiness": f"Be able to explain {name}'s trade-offs out loud.",
        }.get(phase, f"Make progress on {name}.")

    def _summarise(
        self,
        critical: Sequence[Dict[str, Any]],
        nice_to_have: Sequence[Dict[str, Any]],
        weeks: int,
    ) -> str:
        """One line a human can read without unpacking the rest."""
        if not critical and not nice_to_have:
            return "No skill gaps found - you meet the stated requirements."
        if not critical:
            return (
                f"No critical gaps. {len(nice_to_have)} optional skill(s) would "
                "strengthen the application."
            )
        names = ", ".join(g["skill"] for g in critical[:3])
        more = f" and {len(critical) - 3} more" if len(critical) > 3 else ""
        return (
            f"{len(critical)} critical gap(s): {names}{more}. "
            f"Roughly {weeks} week(s) of focused study to close them."
        )


#: Module-level singleton, matching ``match_calculator`` and ``job_analyzer_agent``.
gap_detector = GapDetectorAgent()
