"""The shared skeleton every CareerPilot agent is built on.

An "agent" here is a small, single-purpose unit of reasoning. Each one:

* knows which prompt template it uses,
* asks the LLM through :class:`~agents.ollama_handler.LLMClient`,
* and, crucially, **has a deterministic fallback** so it still produces a
  useful answer when no model is running.

That last point is what makes the whole workflow runnable on a laptop with no
Ollama daemon and no API key. The LLM makes answers richer; it is never
required for the pipeline to complete.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents import AgentConfig
from agents.ollama_handler import (
    LLMClient,
    LLMError,
    LLMResponseError,
    LLMUnavailableError,
    get_prompt_template,
    parse_json_response,
    render_prompt,
)
from utils.error_handling import AnalysisError
from utils.logger import get_logger
from utils.skills import find_skills

logger = get_logger(__name__)


class AgentError(AnalysisError):
    """Raised when an agent cannot produce a result at all.

    A failed *LLM* call is not an agent error: it downgrades to the fallback.
    This is reserved for bad inputs and broken fallbacks.
    """


@dataclass
class AgentResult:
    """What an agent hands back: the data, plus how it was produced."""

    agent: str
    output: Dict[str, Any] = field(default_factory=dict)
    #: ``"llm"`` when a model answered, ``"fallback"`` when the deterministic
    #: path ran. Surfaced in the execution trace so runs are explainable.
    source: str = "fallback"
    #: Which backend answered, when ``source == "llm"``.
    backend: Optional[str] = None
    duration_ms: float = 0.0
    #: Populated when the LLM was tried and failed. The run still succeeded.
    warning: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "source": self.source,
            "backend": self.backend,
            "duration_ms": round(self.duration_ms, 2),
            "warning": self.warning,
            "output": self.output,
        }


class BaseAgent(ABC):
    """Prompt in, structured dict out, with a guaranteed answer.

    Subclasses provide :attr:`name`, :attr:`prompt_name`,
    :attr:`required_inputs` and a :meth:`fallback` implementation. Everything
    else - prompt rendering, retries, JSON parsing, timing, error handling -
    is inherited.
    """

    #: Stable identifier used in traces and tool names.
    name: str = "base"
    description: str = "A CareerPilot agent."
    #: Key into ``ollama_handler.PROMPT_TEMPLATES``. ``None`` means this agent
    #: is purely deterministic and never calls a model.
    prompt_name: Optional[str] = None
    #: Input keys that must be present and non-empty.
    required_inputs: Tuple[str, ...] = ()

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm: Optional[LLMClient] = None,
        use_llm: bool = True,
    ) -> None:
        self.config = config or AgentConfig.from_settings()
        # Injectable so tests can pass a fake and stay offline.
        self._llm = llm
        self.use_llm = use_llm and self.prompt_name is not None

    # -- LLM plumbing -----------------------------------------------------

    @property
    def llm(self) -> LLMClient:
        """The client, created on first access rather than at construction."""
        if self._llm is None:
            self._llm = LLMClient(self.config)
        return self._llm

    def prompt_template(self):
        """The LangChain ``ChatPromptTemplate`` backing this agent."""
        if self.prompt_name is None:
            raise AgentError(f"Agent '{self.name}' has no prompt template")
        return get_prompt_template(self.prompt_name)

    def build_prompt(self, **inputs: Any) -> str:
        """Render this agent's template into a single prompt string."""
        if self.prompt_name is None:
            raise AgentError(f"Agent '{self.name}' has no prompt template")
        return render_prompt(self.prompt_name, **self.prompt_values(**inputs))

    def prompt_values(self, **inputs: Any) -> Dict[str, Any]:
        """Map raw inputs onto template placeholders. Override when they differ."""
        return dict(inputs)

    # -- Subclass hooks ---------------------------------------------------

    def parse(self, payload: Dict[str, Any], **inputs: Any) -> Dict[str, Any]:
        """Turn the model's JSON into this agent's output shape."""
        return payload

    @abstractmethod
    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        """Deterministic answer used when no model is available."""

    # -- Entry point ------------------------------------------------------

    def validate_inputs(self, **inputs: Any) -> None:
        missing = [
            key
            for key in self.required_inputs
            if inputs.get(key) is None
            or (isinstance(inputs[key], str) and not inputs[key].strip())
        ]
        if missing:
            raise AgentError(
                f"Agent '{self.name}' is missing required input(s): "
                f"{', '.join(missing)}"
            )

    def run(self, **inputs: Any) -> AgentResult:
        """Produce a result, preferring the LLM but never depending on it."""
        self.validate_inputs(**inputs)
        started = time.perf_counter()
        warning: Optional[str] = None

        if self.use_llm:
            try:
                prompt = self.build_prompt(**inputs)
                raw = self.llm.generate(prompt)
                payload = parse_json_response(raw)
                output = self.parse(payload, **inputs)
                return AgentResult(
                    agent=self.name,
                    output=output,
                    source="llm",
                    backend=self.llm.last_backend,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            except LLMUnavailableError as exc:
                warning = f"no LLM available, used fallback ({exc})"
                logger.info("Agent '%s': %s", self.name, warning)
            except (LLMResponseError, LLMError) as exc:
                warning = f"LLM call failed, used fallback ({exc})"
                logger.warning("Agent '%s': %s", self.name, warning)
            except Exception as exc:  # defensive: a bad parse must not crash
                warning = f"unexpected LLM error, used fallback ({exc})"
                logger.warning("Agent '%s': %s", self.name, warning, exc_info=True)

        try:
            output = self.fallback(**inputs)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(
                f"Agent '{self.name}' fallback failed: {exc}"
            ) from exc

        return AgentResult(
            agent=self.name,
            output=output,
            source="fallback",
            duration_ms=(time.perf_counter() - started) * 1000,
            warning=warning,
        )

    # -- Tooling ----------------------------------------------------------

    def as_tool(self):
        """Expose this agent as a LangChain ``Tool``.

        Lets the same agents be reused by a tool-calling agent later without
        rewriting any logic. LangChain is imported lazily.
        """
        from langchain_core.tools import Tool

        primary = self.required_inputs[0] if self.required_inputs else "text"

        def _call(tool_input: str) -> str:
            return str(self.run(**{primary: tool_input}).output)

        return Tool(name=self.name, description=self.description, func=_call)


# ---------------------------------------------------------------------------
# Concrete agents
#
# ``JobAnalyzerAgent`` deliberately lives in ``agents/job_analyzer.py`` instead
# of here, next to the keyword engine it falls back to. Importing it here would
# create a cycle, since that module imports ``BaseAgent`` from this one.
# ---------------------------------------------------------------------------


class SkillExtractionAgent(BaseAgent):
    """Lists the technical skills a resume actually evidences."""

    name = "extract_skills"
    description = "Extract the technical skills demonstrated in a resume."
    prompt_name = "skill_extraction"
    required_inputs = ("resume_text",)

    def parse(self, payload: Dict[str, Any], **inputs: Any) -> Dict[str, Any]:
        skills = _clean_skill_list(payload.get("skills"))
        if not skills:
            # An empty list from the model is almost always a formatting slip,
            # not a resume with zero skills. Prefer the reliable answer.
            raise LLMResponseError("Model returned no skills")
        return {"skills": skills}

    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        return {"skills": find_skills(inputs["resume_text"])}


class GapAnalysisAgent(BaseAgent):
    """Works out which required skills the candidate is missing."""

    name = "detect_gaps"
    description = (
        "Compare a candidate's skills against a job's requirements and list "
        "the gaps and the strengths."
    )
    prompt_name = "gap_analysis"
    required_inputs = ("candidate_skills",)

    def prompt_values(self, **inputs: Any) -> Dict[str, Any]:
        return {
            "candidate_skills": ", ".join(inputs.get("candidate_skills") or [])
            or "none listed",
            "required_skills": ", ".join(inputs.get("required_skills") or [])
            or "none listed",
            "preferred_skills": ", ".join(inputs.get("preferred_skills") or [])
            or "none listed",
        }

    def parse(self, payload: Dict[str, Any], **inputs: Any) -> Dict[str, Any]:
        have = {s.lower() for s in inputs.get("candidate_skills") or []}
        # Trust the model's wording, but never let it claim a gap for a skill
        # the candidate demonstrably has.
        gaps = [g for g in _clean_skill_list(payload.get("gaps")) if g not in have]
        return {
            "gaps": gaps,
            "strengths": _clean_skill_list(payload.get("strengths")),
            "explanation": str(payload.get("explanation") or "").strip(),
        }

    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        have = {s.lower() for s in inputs.get("candidate_skills") or []}
        required = _clean_skill_list(inputs.get("required_skills"))
        preferred = _clean_skill_list(inputs.get("preferred_skills"))

        gaps = [s for s in required if s not in have]
        nice_to_have_gaps = [s for s in preferred if s not in have]
        strengths = [s for s in required if s in have]

        if gaps:
            explanation = (
                f"Missing {len(gaps)} of {len(required)} required skill(s): "
                f"{', '.join(gaps[:5])}."
            )
        elif required:
            explanation = "Every required skill is evidenced in the resume."
        else:
            explanation = "The job listing did not name any required skills."

        return {
            "gaps": gaps,
            "preferred_gaps": nice_to_have_gaps,
            "strengths": strengths,
            "explanation": explanation,
        }


class MatchScoringAgent(BaseAgent):
    """Turns the analysis into a 0-100 score.

    Deliberately has no prompt: a score must be reproducible, and asking a
    model to invent a number would make the same inputs give different answers
    on different runs.
    """

    name = "calculate_match"
    label = "Match Calculator"
    description = "Score how well a resume matches a job, from 0 to 100."
    prompt_name = None
    required_inputs = ("resume_text",)

    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        # Imported here rather than at module level to keep the dependency
        # running one way only: match_calculator -> job_analyzer -> base_agent.
        from agents.match_calculator import match_calculator

        job_analysis = dict(inputs.get("job_analysis") or {})
        # Callers that predate the richer analysis pass loose keyword arguments.
        job_analysis.setdefault("title", inputs.get("job_title") or "Unknown role")
        if inputs.get("required_skills"):
            job_analysis.setdefault("required_skills", inputs["required_skills"])

        resume_data = dict(inputs.get("resume_data") or {})
        resume_data.setdefault("resume_text", inputs["resume_text"])
        if inputs.get("skills_found"):
            resume_data.setdefault("skills", inputs["skills_found"])

        return match_calculator.calculate_match(
            resume_data=resume_data,
            job_analysis=job_analysis,
            retriever=inputs.get("retriever"),
        )

    def trace_fields(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """The extra columns this agent contributes to the execution trace."""
        return {
            "label": self.label,
            "overall_score": output.get("overall_match", 0.0),
            "recommendation": output.get("recommendation", "SKIP"),
        }


def build_tools(
    config: Optional[AgentConfig] = None,
    llm: Optional[LLMClient] = None,
) -> List[Any]:
    """LangChain ``Tool`` objects for every agent, ready for a tool-calling LLM."""
    # Imported here rather than at module level to keep the dependency running
    # one way only: job_analyzer -> base_agent.
    from agents.job_analyzer import JobAnalyzerAgent

    agents: Sequence[BaseAgent] = (
        JobAnalyzerAgent(config=config, llm=llm),
        SkillExtractionAgent(config=config, llm=llm),
        GapAnalysisAgent(config=config, llm=llm),
        MatchScoringAgent(config=config, llm=llm),
    )
    return [agent.as_tool() for agent in agents]


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

_VALID_SENIORITY = {"junior", "mid", "senior", "lead"}


def _clean_str_list(value: Any) -> List[str]:
    """Coerce whatever the model returned into a de-duplicated list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []

    seen = set()
    out: List[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


def _clean_skill_list(value: Any) -> List[str]:
    """Like :func:`_clean_str_list` but lowercased, since skills are compared."""
    return [s.lower() for s in _clean_str_list(value)]


def _clean_seniority(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if text in _VALID_SENIORITY else None


def _guess_title(description: str) -> str:
    """First non-empty line of a posting is nearly always the role title."""
    for line in description.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "Unknown role"
