#!/usr/bin/env python3
"""CareerPilot AI -- the demo script.

Runs one resume and one job advert through the complete seven-node pipeline and
prints the result as a report a human can read out loud.

    python test_complete_workflow.py                    # uses data/sample_*.txt
    python test_complete_workflow.py cv.txt advert.txt  # your own files
    python test_complete_workflow.py --no-emoji         # plain ASCII markers
    python test_complete_workflow.py --verbose          # plus the app's own logs

Everything printed is also written to ``results.txt`` so the run can be shown
without a terminal.

Two notes on what this script will and will not do:

**It prints the numbers it was given.** The brief for this script contained an
illustrative report -- 80.5%, APPLY, 15 skills, a 7-day plan. The sample resume
in ``data/`` does not score 80.5 against the sample advert; it scores about 60
and the honest verdict is SKIP. Hard-coding the prettier numbers would make this
a screenshot rather than a demo, and the first person to run it with their own
CV would find out. Every figure below is read from the live result.

**It does not invent a company name.** The illustrative report showed
``COMPANY: TechCorp AI``. ``JobAnalyzerAgent`` extracts a job title and a company
*size*, but not a company name, so this prints what is actually known and says
so when the advert does not say.

Despite the ``test_`` prefix -- which the brief asked for -- this is a demo
script, not a unit test. The real tests for this pipeline are in
``tests/test_complete_workflow.py``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DEFAULT_RESUME = BASE_DIR / "data" / "sample_resume.txt"
DEFAULT_JOB = BASE_DIR / "data" / "sample_jd.txt"
DEFAULT_OUTPUT = BASE_DIR / "results.txt"

WIDTH = 58
RULE = "=" * WIDTH

# The brief asks for a full analysis in under 200ms. Node time only -- importing
# torch and chromadb costs seconds on a cold start and is not what is measured.
TIME_BUDGET_MS = 200

# How many suggestions to show before saying "and N more". The optimiser
# routinely produces a dozen; a wall of them is not a demo.
MAX_GAPS_SHOWN = 6
MAX_IMPROVEMENTS_SHOWN = 6
MAX_STEPS_SHOWN = 4

# Rules are 58 wide to match the other scripts; prose gets a little more room
# before it is cut, because a suggestion truncated mid-verb is not actionable.
TEXT_WIDTH = 68

EMOJI = {
    "APPLY": "\U0001f7e2",       # green circle
    "MAYBE": "\U0001f7e1",       # yellow circle
    "SKIP": "\U0001f534",        # red circle
    "CRITICAL": "\U0001f534",
    "IMPORTANT": "\U0001f7e0",   # orange circle
    "NICE": "\U0001f7e1",
    "questions": "\U0001f4da",   # books
    "clock": "\u23f0",
    "target": "\U0001f3af",
    "tick": "\u2713",
    "cross": "\u2717",
    "arrow": "\u2193",
    "warn": "\u26a0",
    "ellipsis": "\u2026",
}

ASCII = {
    "APPLY": "[APPLY]",
    "MAYBE": "[MAYBE]",
    "SKIP": "[SKIP]",
    "CRITICAL": "[!]",
    "IMPORTANT": "[*]",
    "NICE": "[~]",
    "questions": "*",
    "clock": "*",
    "target": "*",
    "tick": "+",
    "cross": "x",
    "arrow": "->",
    "warn": "!",
    "ellipsis": "...",
}


class Report:
    """Collects every printed line so the same text can be saved verbatim.

    Printing and writing separately would let the two drift; the file would then
    disagree with what was demonstrated on screen.
    """

    def __init__(self, marks: Dict[str, str]) -> None:
        self.lines: List[str] = []
        self.marks = marks

    def __call__(self, text: str = "") -> None:
        self.lines.append(text)
        try:
            print(text)
        except UnicodeEncodeError:
            # A terminal that cannot render the markers should not kill the run.
            print(text.encode("ascii", "replace").decode("ascii"))

    def rule(self) -> None:
        self(RULE)

    def banner(self, title: str) -> None:
        self()
        self.rule()
        self(title)
        self.rule()

    def mark(self, key: str) -> str:
        return self.marks.get(key, "")

    def cut(self, text: Any, limit: int) -> str:
        """Truncate using the active marker set's ellipsis."""
        return truncate(text, limit, self.marks.get("ellipsis", "..."))

    def save(self, path: Path) -> None:
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def read_text(path: Path, label: str) -> str:
    """Read one input file, failing with a sentence rather than a traceback."""
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise SystemExit(f"{label} is empty: {path}")
    return text


def as_percent(value: Any) -> Optional[float]:
    """Coerce a score onto 0-100, whether it arrived as 0.78 or 78.

    The agents are not consistent about this -- the match calculator reports
    ``59.7`` and the interview agent reports ``0.3`` -- and printing one in the
    other's units is exactly the mistake this project has already had to fix
    once, inside the pipeline itself.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 1.0:
        number *= 100.0
    return max(0.0, min(100.0, number))


def plural(count: int, word: str, suffix: str = "s") -> str:
    return f"{count} {word}{'' if count == 1 else suffix}"


def truncate(text: str, limit: int, ellipsis: str = "\u2026") -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - len(ellipsis)].rstrip() + ellipsis


# --------------------------------------------------------------------------- #
# Report sections
# --------------------------------------------------------------------------- #
def print_header(out: Report, analysis: Dict[str, Any]) -> None:
    out("CAREERPILOT AI - COMPLETE ANALYSIS")
    out(RULE)
    out()
    out(f"JOB:     {analysis.get('title') or 'Untitled role'}")

    # No company-name extraction exists, so say what is known rather than
    # printing a plausible-looking blank.
    company = analysis.get("company") or analysis.get("company_name")
    if company:
        out(f"COMPANY: {company}")
    else:
        size = analysis.get("company_size")
        detail = f"not stated in the advert (size: {size})" if size else "not stated in the advert"
        out(f"COMPANY: {detail}")

    seniority = analysis.get("seniority")
    role_type = analysis.get("role_type")
    if seniority or role_type:
        out(f"LEVEL:   {seniority or 'unspecified'} / {role_type or 'general'}")


def print_execution(out: Report, result: Dict[str, Any]) -> None:
    out.banner("ANALYSIS EXECUTION")
    out()

    trace: Sequence[Dict[str, Any]] = result.get("execution_trace") or []
    if not trace:
        out(f"{out.mark('warn')} No execution trace was recorded.")
        return

    for entry in trace:
        label = entry.get("label") or entry.get("node") or "step"
        status = str(entry.get("status", "unknown"))
        duration = entry.get("duration_ms")
        shown = f"{float(duration):.0f}ms" if isinstance(duration, (int, float)) else "?"
        marker = out.mark("tick") if status == "completed" else out.mark("cross")
        out(f"{marker} {label} ({shown})")

        detail = entry.get("detail") or entry.get("error")
        if detail:
            out(f"  {out.mark('arrow')} {out.cut(detail, TEXT_WIDTH)}")

    total = result.get("total_duration_ms")
    out()
    if isinstance(total, (int, float)):
        verdict = "within" if total <= TIME_BUDGET_MS else "over"
        out(f"Total Analysis Time: {float(total):.0f}ms ({verdict} the {TIME_BUDGET_MS}ms budget)")
    else:
        out("Total Analysis Time: not recorded")

    failed = result.get("nodes_failed") or []
    if failed:
        out(f"{out.mark('warn')} Degraded run - {plural(len(failed), 'node')} failed: {', '.join(failed)}")


def print_verdict(out: Report, result: Dict[str, Any]) -> None:
    out.banner("RESULTS")
    out()

    recommendation = result.get("recommendation") or {}
    score = as_percent(result.get("match_score"))

    # ``recommendation["decision"]`` is the verdict word. The top-level
    # ``user_recommendation`` is the prose paragraph shown to the user -- reading
    # that here printed an essay where APPLY/MAYBE/SKIP belonged.
    decision = str(recommendation.get("decision") or "UNKNOWN").upper()

    out(f"OVERALL MATCH: {score:.1f}%" if score is not None else "OVERALL MATCH: not scored")
    out(f"RECOMMENDATION: {out.mark(decision)} {decision}".strip())

    headline = recommendation.get("headline")
    if headline:
        out()
        out(out.cut(headline, WIDTH * 2))

    # When the pipeline overrides the scorer's verdict it owes the reader a
    # reason. Printing the new answer and hiding the disagreement is how a tool
    # loses the benefit of the doubt.
    if recommendation.get("adjusted"):
        scored = recommendation.get("scored_decision")
        reason = recommendation.get("adjustment_reason")
        out()
        out(f"{out.mark('warn')} Adjusted from {scored} to {decision}: {out.cut(reason or 'no reason given', 120)}")


def print_breakdown(out: Report, result: Dict[str, Any]) -> None:
    breakdown = (result.get("match_result") or {}).get("match_breakdown") or {}
    if not breakdown:
        return

    out()
    out("Match Breakdown:")
    for name, component in breakdown.items():
        if not isinstance(component, dict):
            continue
        if component.get("applicable") is False:
            out(f"  {name.replace('_', ' ').title():<12} not applicable")
            continue
        score = as_percent(component.get("score"))
        weight = component.get("weight")
        weight_note = f"  (weight {float(weight):.0%})" if isinstance(weight, (int, float)) else ""
        if score is not None:
            out(f"  {name.replace('_', ' ').title():<12} {score:>5.1f}%{weight_note}")


def print_gaps(out: Report, result: Dict[str, Any]) -> None:
    report = (result.get("gaps") or {}).get("gap_report") or {}
    critical = list(report.get("critical_gaps") or [])
    nice = list(report.get("nice_to_have_gaps") or [])

    out()
    out("GAPS FOUND:")
    if not critical and not nice:
        out("  None - the resume covers everything the advert asks for.")
        return

    # Costliest first. The pipeline's own priority order is cheapest-first,
    # which answers "what should I study tonight" -- but this list answers
    # "what is standing between me and this job", and that is the expensive one.
    def cost(gap: Dict[str, Any]) -> float:
        try:
            return -float(gap.get("learning_time_days", 0))
        except (TypeError, ValueError):
            return 0.0

    ordered: List[Tuple[Dict[str, Any], str]] = []
    # Required gaps are listed before preferred ones, but the marker follows the
    # detector's own grade -- CRITICAL, IMPORTANT or NICE. Colouring by list
    # instead printed an amber-graded gap in red, which reads as a harder
    # blocker than the detector actually judged it to be.
    for gap in sorted(critical, key=cost):
        ordered.append((gap, "CRITICAL"))
    for gap in sorted(nice, key=cost):
        ordered.append((gap, "NICE"))

    for gap, fallback_grade in ordered[:MAX_GAPS_SHOWN]:
        grade = str(gap.get("importance") or fallback_grade).upper()
        marker = out.mark(grade) or out.mark(fallback_grade)
        days = gap.get("learning_time_days")
        timing = f" ({plural(int(days), 'day')} to learn)" if isinstance(days, (int, float)) else ""
        out(f"  {marker} {grade}: {gap.get('skill', 'unnamed')}{timing}")

    remaining = len(ordered) - MAX_GAPS_SHOWN
    if remaining > 0:
        out(f"  ... and {plural(remaining, 'more gap')}")

    weeks = report.get("total_learning_time_weeks")
    if isinstance(weeks, (int, float)) and weeks:
        out(f"  Roughly {plural(int(weeks), 'week')} of focused study to close them.")

    quick = report.get("quick_wins") or []
    if quick:
        names = [str(q.get("skill", q)) if isinstance(q, dict) else str(q) for q in quick[:3]]
        out(f"  Quick wins: {', '.join(names)}")


def print_improvements(out: Report, result: Dict[str, Any]) -> None:
    optimisations = result.get("resume_optimizations") or {}
    improvements = list(optimisations.get("improvements") or [])

    out()
    out("RESUME IMPROVEMENTS:")
    if not improvements:
        out("  None suggested.")
        return

    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ordered = sorted(improvements, key=lambda i: rank.get(str(i.get("impact", "LOW")).upper(), 3))

    for number, item in enumerate(ordered[:MAX_IMPROVEMENTS_SHOWN], start=1):
        impact = str(item.get("impact", "LOW")).upper()
        what = item.get("suggested") or item.get("why") or "no suggestion text"
        section = item.get("section")
        prefix = f"{section}: " if section else ""
        out(f"  {number}. {out.cut(prefix + str(what), TEXT_WIDTH)} ({impact} impact)")

    remaining = len(ordered) - MAX_IMPROVEMENTS_SHOWN
    if remaining > 0:
        out(f"  ... and {plural(remaining, 'more suggestion')}")

    # The optimiser deliberately leaves blanks rather than inventing numbers.
    # A demo that hides that looks more impressive and teaches the wrong thing.
    needs_input = sum(1 for item in improvements if item.get("needs_your_input"))
    if needs_input:
        out(f"  {plural(needs_input, 'suggestion')} leave a blank for you to fill in - no invented figures.")


def print_interview(out: Report, result: Dict[str, Any]) -> None:
    prep = result.get("interview_prep") or {}

    out()
    out("INTERVIEW PREP:")
    if not prep:
        out("  Not generated.")
        return

    questions = prep.get("question_count") or len(prep.get("questions") or [])
    out(f"  {out.mark('questions')} {plural(int(questions), 'likely question')}")

    days = prep.get("prep_days")
    hours = prep.get("estimated_prep_time_hours")
    if isinstance(days, (int, float)) and days:
        detail = f" ({float(hours):.0f} hours)" if isinstance(hours, (int, float)) else ""
        out(f"  {out.mark('clock')} {int(days)}-day preparation plan{detail}")

    success = as_percent(prep.get("success_rate_prediction"))
    if success is not None:
        out(f"  {out.mark('target')} Predicted success rate: {success:.0f}%")

    difficulty = prep.get("interview_difficulty")
    if difficulty:
        out(f"  Difficulty: {difficulty}")

    gap_questions = prep.get("gap_question_count")
    if isinstance(gap_questions, int) and gap_questions:
        out(f"  {plural(gap_questions, 'question')} will probe a gap - prepare those first.")


def print_next_steps(out: Report, result: Dict[str, Any]) -> None:
    steps = (result.get("recommendation") or {}).get("next_steps") or []
    if not steps:
        return

    out()
    out("WHAT TO DO NEXT:")
    for number, step in enumerate(steps[:MAX_STEPS_SHOWN], start=1):
        if isinstance(step, dict):
            action = step.get("action", "")
            effort = step.get("effort")
            suffix = f"  [{effort}]" if effort else ""
            out(f"  {number}. {out.cut(action, TEXT_WIDTH)}{suffix}")
        else:
            out(f"  {number}. {out.cut(step, TEXT_WIDTH)}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete CareerPilot pipeline and print a report."
    )
    parser.add_argument("resume", nargs="?", default=str(DEFAULT_RESUME), help="resume file")
    parser.add_argument("job", nargs="?", default=str(DEFAULT_JOB), help="job advert file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="where to save the report")
    parser.add_argument("--no-emoji", action="store_true", help="use ASCII markers instead")
    parser.add_argument("--verbose", action="store_true", help="show the application's own logs")
    return parser.parse_args(argv)


def supports_emoji() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or ""
    return "utf" in encoding.lower()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not args.verbose:
        # The pipeline logs a line per node. Useful when debugging, noise in a demo.
        logging.disable(logging.INFO)

    marks = ASCII if (args.no_emoji or not supports_emoji()) else EMOJI
    out = Report(marks)

    resume_text = read_text(Path(args.resume), "Resume")
    job_text = read_text(Path(args.job), "Job advert")

    # Imported here so a missing dependency is reported after the argument
    # parsing, and so --help costs nothing.
    from agents.complete_workflow import run_complete_analysis

    started = time.perf_counter()
    try:
        result = run_complete_analysis(resume_text, job_text)
    except Exception:  # pragma: no cover - run_complete_analysis absorbs its own errors
        traceback.print_exc()
        return 1
    wall_ms = (time.perf_counter() - started) * 1000.0

    print_header(out, result.get("analysis") or {})
    print_execution(out, result)
    print_verdict(out, result)
    print_breakdown(out, result)
    print_gaps(out, result)
    print_improvements(out, result)
    print_interview(out, result)
    print_next_steps(out, result)

    out()
    out.rule()
    out(f"Wall-clock time including model loading: {wall_ms:.0f}ms")

    status = str(result.get("status", "unknown"))
    if status != "completed":
        note = result.get("note")
        out(f"{out.mark('warn')} Run status: {status}{f' - {note}' if note else ''}")

    output_path = Path(args.output)
    out.save(output_path)
    print(f"\nSaved to {output_path}")

    # A degraded run still prints a useful report, but it is not a pass.
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
