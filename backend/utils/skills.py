"""Shared skill vocabulary used by the RAG indexer, job analyzer and scorer."""

import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Pattern, Set, Tuple

KNOWN_SKILLS = {
    # languages
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "c#",
    "ruby", "php", "scala", "kotlin", "swift", "bash",
    # data
    "sql", "nosql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "snowflake", "spark", "airflow", "kafka",
    # web / api
    "fastapi", "django", "flask", "react", "vue", "angular", "node.js",
    "next.js", "svelte", "rest", "graphql", "grpc", "microservices",
    # infra
    "docker", "kubernetes", "terraform", "ansible", "aws", "azure", "gcp",
    "ci/cd", "jenkins", "github actions", "linux", "nginx",
    # ai / ml
    "langchain", "langgraph", "llamaindex", "pytorch", "tensorflow", "keras",
    "scikit-learn", "pandas", "numpy", "hugging face", "ollama",
    "rag", "llm", "nlp", "machine learning", "deep learning", "computer vision",
    "prompt engineering", "vector database", "chromadb", "pinecone", "embeddings",
    # practices
    "git", "agile", "scrum", "tdd", "unit testing", "system design",
}

#: Skills that describe an approach or a body of knowledge rather than a
#: concrete tool. Used to split "everything the job requires" from "the tech
#: stack you would actually install".
CONCEPT_SKILLS = {
    "rag", "llm", "nlp", "machine learning", "deep learning", "computer vision",
    "prompt engineering", "embeddings", "vector database", "microservices",
    "system design", "agile", "scrum", "tdd", "unit testing", "ci/cd",
}

#: Alternative spellings that should resolve to a canonical skill name.
_ALIASES = {
    "node.js": ["nodejs", "node js"],
    "next.js": ["nextjs"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "postgresql": ["postgres"],
    "ci/cd": ["cicd", "continuous integration"],
    "machine learning": ["ml"],
    "hugging face": ["huggingface"],
    "kubernetes": ["k8s"],
    # Resumes spell this out in prose far more often than they use the acronym.
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    # "golang" is too far from "go" for similarity scoring to bridge, and bare
    # "node" is deliberately absent: it would fire on Kubernetes nodes and
    # graph nodes, which have nothing to do with Node.js.
    "go": ["golang"],
}


#: Skills whose canonical name is also an ordinary English word, and so cannot
#: be matched on its own. The value is the list of phrases that do mean the
#: skill; the bare name is deliberately not among them.
#:
#: "rest" is the whole reason this exists. A live search returned a "Freelance
#: Writer" advert whose prose contained "the rest of", which was read as REST
#: the API style. It was the *only* skill found in that advert, the resume has
#: REST, so one word of ordinary English became a requirements list of one that
#: matched perfectly: **100% - APPLY**, on a writing job, top of the results.
#:
#: This is the same trap the "go"/"node" note below describes, and it is worth
#: being blunt about the asymmetry: failing to spot REST in an advert that only
#: ever writes it bare costs a few points on one card, while a false positive
#: on a common word can invent a perfect score out of nothing.
_REQUIRE_CONTEXT: Dict[str, List[str]] = {
    "rest": [
        "rest api", "rest apis", "rest-api", "rest-apis",
        "restful", "restful api", "restful apis", "restful service",
        "restful services", "rest service", "rest services",
        "rest endpoint", "rest endpoints",
    ],
}


def _compile(term: str) -> Pattern:
    """Match `term` only as a whole word.

    Plain `in` checks produce false positives — "go" inside "django", "sql"
    inside "postgresql". Lookarounds work for terms ending in punctuation
    (``c++``, ``c#``) where ``\\b`` would not.
    """
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")


_PATTERNS: Dict[str, List[Pattern]] = {
    skill: [
        _compile(term)
        for term in (_REQUIRE_CONTEXT.get(skill) or [skill]) + _ALIASES.get(skill, [])
    ]
    for skill in KNOWN_SKILLS
}


def find_skills(text: str) -> List[str]:
    """Return the sorted, de-duplicated known skills mentioned in `text`."""
    if not text:
        return []

    lowered = text.lower()
    return sorted(
        skill
        for skill, patterns in _PATTERNS.items()
        if any(pattern.search(lowered) for pattern in patterns)
    )


def tech_stack(skills: Iterable[str]) -> List[str]:
    """Narrow a skill list to the concrete tools, dropping the concepts.

    "python" and "docker" are things you install; "rag" and "agile" are not.
    """
    return sorted({s.lower() for s in skills if s.lower() not in CONCEPT_SKILLS})


# ---------------------------------------------------------------------------
# Soft skills
# ---------------------------------------------------------------------------

SOFT_SKILLS = {
    "communication", "collaboration", "teamwork", "leadership", "mentoring",
    "problem solving", "ownership", "adaptability", "time management",
    "stakeholder management", "critical thinking", "attention to detail",
    "self-motivated", "curiosity", "empathy", "presentation", "negotiation",
    "cross-functional", "analytical thinking", "creativity",
}

#: Job adverts rarely use the canonical noun, so most of the matching power
#: lives here. Note that bare "lead" is deliberately absent: it would collide
#: with the seniority detector, which reads "Lead Engineer" as a job level.
_SOFT_ALIASES = {
    "communication": ["communicate", "communication skills", "written and verbal"],
    "collaboration": ["collaborate", "collaborative", "collaborating"],
    "teamwork": ["team player", "team-oriented", "work in a team"],
    "leadership": ["lead a team", "leading teams", "lead teams", "people management"],
    "mentoring": ["mentor", "mentored", "mentors", "mentorship", "coaching"],
    "problem solving": ["problem-solving", "problem solver"],
    "ownership": ["take ownership", "sense of ownership", "self-starter"],
    "adaptability": ["adaptable", "flexible", "thrive in ambiguity"],
    "time management": ["prioritise", "prioritize", "manage your time"],
    "stakeholder management": ["stakeholder", "stakeholders"],
    "critical thinking": ["critical thinker"],
    "attention to detail": ["detail-oriented", "detail oriented"],
    "self-motivated": ["self motivated", "self-driven", "proactive"],
    "curiosity": ["curious", "eager to learn"],
    "empathy": ["empathetic"],
    "presentation": ["presenting", "presentation skills"],
    "negotiation": ["negotiate"],
    "cross-functional": ["cross functional", "cross-functionally"],
    "analytical thinking": ["analytical", "analytical skills"],
    "creativity": ["creative"],
}

_SOFT_PATTERNS: Dict[str, List[Pattern]] = {
    skill: [_compile(skill)] + [_compile(alias) for alias in _SOFT_ALIASES.get(skill, [])]
    for skill in SOFT_SKILLS
}


def find_soft_skills(text: str) -> List[str]:
    """Return the sorted, de-duplicated soft skills mentioned in `text`."""
    if not text:
        return []

    lowered = text.lower()
    return sorted(
        skill
        for skill, patterns in _SOFT_PATTERNS.items()
        if any(pattern.search(lowered) for pattern in patterns)
    )


# ---------------------------------------------------------------------------
# Fuzzy matching
#
# Comparing two skill lists with ``==`` is too strict: a resume says "K8s"
# where the advert says "Kubernetes", "ReactJS" where it says "React". But
# fuzzy matching is dangerous in the other direction — crediting somebody with
# "Java" because they wrote "JavaScript" would be a silent, serious error in a
# tool people use to decide whether to apply for a job.
#
# So the rules below are deliberately conservative, ordered by how much they
# can be trusted, and every match records *why* it matched.
# ---------------------------------------------------------------------------

#: Below this length a name is too short for similarity to mean anything:
#: "go", "r", "c#" and "ml" would fuzzy-match half the vocabulary. Short
#: skills must match exactly or through a curated alias.
_MIN_FUZZY_LENGTH = 5

#: Similarity above which two names are considered the same thing. 0.88
#: accepts "kubernets"/"kubernetes" (0.94) and rejects "java"/"javascript".
_FUZZY_THRESHOLD = 0.88

#: Pairs that look alike but are emphatically different technologies. Checked
#: before anything else, because one false positive here discredits the score.
_NEVER_MATCH = {
    frozenset({"java", "javascript"}),
    frozenset({"c", "c++"}),
    frozenset({"c", "c#"}),
    frozenset({"c++", "c#"}),
    frozenset({"angular", "react"}),
    frozenset({"aws", "azure"}),
    frozenset({"mysql", "nosql"}),
    frozenset({"sql", "nosql"}),
    frozenset({"postgresql", "mysql"}),
    frozenset({"tensorflow", "pytorch"}),
    frozenset({"scala", "scalability"}),
    frozenset({"react", "redis"}),
    frozenset({"rust", "trust"}),
}

#: Specialisations that entail a broader skill: nobody has used PostgreSQL
#: without writing SQL. Without this, a resume naming PostgreSQL was told it
#: lacked SQL -- talking a candidate out of a skill they demonstrably have.
#:
#: Only entailments that hold in every case belong here. "Django implies
#: Python" would be true; "AWS implies Docker" would not, and one false
#: entailment discredits the score as surely as a false gap.
#:
#: Checked after :data:`_NEVER_MATCH`, so "sql"/"nosql" stays distinct, and
#: after containment, so "sql server"/"sql" keeps its stronger 0.95.
_IMPLIES: Dict[str, Set[str]] = {
    "postgresql": {"sql"},
    "mysql": {"sql"},
    "sqlite": {"sql"},
    "mariadb": {"sql"},
    "oracle": {"sql"},
    "mssql": {"sql"},
    "t-sql": {"sql"},
    "pl/sql": {"sql"},
    "snowflake": {"sql"},
    "mongodb": {"nosql"},
    "cassandra": {"nosql"},
    "dynamodb": {"nosql"},
}

#: Scored below an exact match because the entailment is strong but not
#: symmetric: PostgreSQL experience fully satisfies "SQL required", whereas a
#: resume naming only "SQL" is weaker evidence for a PostgreSQL-specific role.
#: One value serves both directions -- callers sort and compare these scores,
#: and an asymmetric similarity function would make that ordering meaningless.
_IMPLICATION_SCORE = 0.9

#: Words carrying no meaning when comparing skill names, so "react developer"
#: still matches "react".
_NOISE_WORDS = {
    "experience", "expert", "expertise", "developer", "development", "engineer",
    "engineering", "programming", "advanced", "basic", "proficient", "knowledge",
    "skills", "skill", "framework", "library", "language", "using", "with",
    "and", "the", "strong", "solid", "hands", "on", "years", "year", "plus",
}

#: Reverse index from every alias to its canonical skill, e.g. "k8s" ->
#: "kubernetes". Built from the same table the keyword matcher uses, so the
#: two can never disagree.
_CANONICAL: Dict[str, str] = {}
for _canon, _alias_list in _ALIASES.items():
    _CANONICAL[_canon] = _canon
    for _alias in _alias_list:
        _CANONICAL[_alias] = _canon


def normalise_skill(skill: str) -> str:
    """Reduce a skill name to a comparable core.

    Lowercases, resolves aliases, drops filler words and trims punctuation, so
    "Advanced Kubernetes experience" becomes "kubernetes".
    """
    text = str(skill or "").strip().lower()
    if not text:
        return ""
    if text in _CANONICAL:
        return _CANONICAL[text]

    # Keep + # . - / because they distinguish c++, c#, node.js and ci/cd.
    text = re.sub(r"[^\w\s+#.\-/]", " ", text)
    words = [w for w in text.split() if w and w not in _NOISE_WORDS]
    text = " ".join(words).strip(" .-")
    return _CANONICAL.get(text, text)


def _bare(text: str) -> str:
    """Strip separators so "node.js", "node js" and "nodejs" compare equal."""
    return re.sub(r"[\s._\-/]", "", text)


def skill_similarity(left: str, right: str) -> Tuple[float, str]:
    """How alike two skill names are, and which rule decided it.

    Returns ``(score, reason)`` with score in 0.0-1.0. The reason is kept so a
    match can be explained to the user rather than merely asserted.
    """
    a, b = normalise_skill(left), normalise_skill(right)
    if not a or not b:
        return 0.0, "empty"
    if a == b:
        return 1.0, "exact"
    if frozenset({a, b}) in _NEVER_MATCH:
        return 0.0, "explicitly distinct"

    bare_a, bare_b = _bare(a), _bare(b)
    if bare_a == bare_b:
        return 1.0, "punctuation"

    # Multi-word containment: "machine learning" inside "machine learning
    # engineer". Whole-word only, so "go" cannot match inside "django".
    if " " in a or " " in b:
        longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
        if _compile(shorter).search(longer):
            return 0.95, "contains"

    if b in _IMPLIES.get(a, frozenset()):
        return _IMPLICATION_SCORE, f"{a} implies {b}"
    if a in _IMPLIES.get(b, frozenset()):
        return _IMPLICATION_SCORE, f"{b} implies {a}"

    short_bare, long_bare = sorted((bare_a, bare_b), key=len)
    if len(short_bare) >= _MIN_FUZZY_LENGTH:
        # react / reactjs, postgres / postgresql.
        if long_bare.startswith(short_bare):
            return 0.93, "prefix"
        ratio = SequenceMatcher(None, bare_a, bare_b).ratio()
        if ratio >= _FUZZY_THRESHOLD:
            return round(ratio, 2), "similar spelling"

    return 0.0, "no match"


def match_skill(
    needle: str, haystack: Iterable[str]
) -> Optional[Tuple[str, float, str]]:
    """Best match for `needle` within `haystack`, or ``None``.

    Returns ``(matched_name, score, reason)``. The strongest match wins rather
    than the first, so the order of the candidate list cannot change the result.
    """
    best: Optional[Tuple[str, float, str]] = None
    for candidate in haystack:
        score, reason = skill_similarity(needle, candidate)
        if score <= 0.0:
            continue
        if best is None or score > best[1]:
            best = (candidate, score, reason)
        if score == 1.0:
            break
    return best
