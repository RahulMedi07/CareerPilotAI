"""Tests for the shared skill vocabulary."""

import pytest

from utils.skills import (
    KNOWN_SKILLS,
    _REQUIRE_CONTEXT,
    find_skills,
    match_skill,
    normalise_skill,
    skill_similarity,
)


class TestFindSkills:
    def test_finds_known_skills_case_insensitively(self):
        assert find_skills("We use PYTHON and Docker") == ["docker", "python"]

    def test_results_are_sorted_and_unique(self):
        found = find_skills("aws aws python docker python")
        assert found == ["aws", "docker", "python"]

    def test_no_skills_returns_empty_list(self):
        assert find_skills("We are looking for a friendly teammate.") == []

    @pytest.mark.parametrize("text", ["", None])
    def test_empty_input(self, text):
        assert find_skills(text) == []


class TestWordBoundaries:
    """Regression tests: plain substring matching produced false positives."""

    def test_go_does_not_match_inside_django(self):
        assert "go" not in find_skills("Built a Django app")

    def test_sql_does_not_match_inside_postgresql(self):
        found = find_skills("We run PostgreSQL")
        assert "postgresql" in found
        assert "sql" not in found

    def test_rag_does_not_match_inside_storage(self):
        assert "rag" not in find_skills("Object storage on disk")

    def test_r_words_do_not_match_rest(self):
        assert "rest" not in find_skills("The restaurant was great")

    def test_rest_the_english_word_is_not_rest_the_api_style(self):
        # From a live search: a "Freelance Writer" advert containing "the rest
        # of" was read as requiring REST. It was the only skill found, the
        # resume has REST, and the writing job came back as a 100% match.
        assert "rest" not in find_skills("We will handle the rest of it")
        assert "rest" not in find_skills("Rest assured, the team is friendly")
        assert "rest" not in find_skills("Take the rest of the week off")

    def test_rest_still_matches_when_it_means_the_api_style(self):
        for text in (
            "Created REST APIs with FastAPI",
            "Build RESTful services",
            "Design REST endpoints for the client",
            "experience with rest-api design",
        ):
            assert "rest" in find_skills(text), text

    def test_standalone_terms_still_match(self):
        assert set(find_skills("We use Go, SQL and RAG")) == {"go", "sql", "rag"}

    def test_punctuation_terminated_skills_match(self):
        assert "c++" in find_skills("Strong C++ background")
        assert "c#" in find_skills("Wrote C# services")

    def test_skill_followed_by_punctuation(self):
        assert "python" in find_skills("Skills: Python, Docker.")

    def test_multiword_skills_match(self):
        found = find_skills("Applied machine learning and deep learning")
        assert "machine learning" in found
        assert "deep learning" in found


class TestAliases:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("nodejs backend", "node.js"),
            ("Node JS backend", "node.js"),
            ("sklearn pipelines", "scikit-learn"),
            ("Postgres tuning", "postgresql"),
            ("CICD pipelines", "ci/cd"),
            ("k8s operators", "kubernetes"),
            ("huggingface models", "hugging face"),
        ],
    )
    def test_alias_resolves_to_canonical_name(self, text, expected):
        assert expected in find_skills(text)

    def test_alias_result_is_the_canonical_name_only(self):
        found = find_skills("nodejs")
        assert found == ["node.js"]


class TestVocabulary:
    def test_every_entry_is_lowercase(self):
        assert all(skill == skill.lower() for skill in KNOWN_SKILLS)

    def test_no_blank_entries(self):
        assert all(skill.strip() for skill in KNOWN_SKILLS)

    def test_every_skill_is_findable_in_isolation(self):
        # Except the handful whose bare name is an ordinary English word: those
        # are findable only through a phrase that unambiguously means the
        # skill, which is the whole point of _REQUIRE_CONTEXT. Each one is
        # checked here through its first such phrase, so the entry still has to
        # be reachable -- it just cannot be reached by the bare word.
        for skill in KNOWN_SKILLS:
            term = (_REQUIRE_CONTEXT.get(skill) or [skill])[0]
            assert skill in find_skills(f"Experienced with {term} daily."), skill

    def test_context_requiring_skills_are_not_findable_by_their_bare_name(self):
        for skill in _REQUIRE_CONTEXT:
            assert skill in KNOWN_SKILLS
            assert skill not in find_skills(f"Experienced with {skill} daily.")


class TestNormaliseSkill:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Python", "python"),
            ("  PYTHON  ", "python"),
            ("K8s", "kubernetes"),
            ("postgres", "postgresql"),
            ("ML", "machine learning"),
            ("Advanced Python experience", "python"),
            ("strong React knowledge", "react"),
            ("C++", "c++"),
            ("ci/cd", "ci/cd"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_reduces_to_a_comparable_core(self, raw, expected):
        assert normalise_skill(raw) == expected

    def test_punctuation_that_distinguishes_skills_is_kept(self):
        assert normalise_skill("C#") != normalise_skill("C++")


class TestSkillSimilarity:
    @pytest.mark.parametrize(
        "a,b,reason",
        [
            ("python", "Python", "exact"),
            ("K8s", "kubernetes", "exact"),
            ("node.js", "nodejs", "exact"),
            ("next.js", "next js", "punctuation"),
            ("react", "reactjs", "prefix"),
            ("kubernets", "kubernetes", "similar spelling"),
            ("machine learning", "machine learning engineer", "exact"),
        ],
    )
    def test_matches_and_explains_why(self, a, b, reason):
        score, why = skill_similarity(a, b)
        assert score > 0.0
        assert why == reason

    @pytest.mark.parametrize(
        "a,b",
        [
            ("java", "javascript"),
            ("c", "c++"),
            ("c#", "c++"),
            ("aws", "azure"),
            ("react", "angular"),
            ("sql", "nosql"),
            ("mysql", "postgresql"),
            ("pytorch", "tensorflow"),
            ("go", "django"),
            ("rust", "trust"),
            ("python", ""),
        ],
    )
    def test_rejects_dangerous_lookalikes(self, a, b):
        assert skill_similarity(a, b)[0] == 0.0

    def test_short_names_are_never_fuzzy_matched(self):
        # "r" and "go" would otherwise match half the vocabulary on similarity
        # alone, so short names must go through the curated alias table.
        assert skill_similarity("r", "ruby")[0] == 0.0
        assert skill_similarity("go", "mongodb")[0] == 0.0
        assert skill_similarity("go", "golang") == (1.0, "exact")  # via alias

    def test_is_symmetric(self):
        for a, b in [("react", "reactjs"), ("java", "javascript"), ("k8s", "kubernetes")]:
            assert skill_similarity(a, b)[0] == skill_similarity(b, a)[0]

    def test_identical_names_score_one(self):
        assert skill_similarity("docker", "docker") == (1.0, "exact")


class TestEntailment:
    """A specific database implies the general skill it is written in."""

    @pytest.mark.parametrize(
        "specific, general",
        [
            ("postgresql", "sql"),
            ("postgres", "sql"),  # via the alias table
            ("mysql", "sql"),
            ("sqlite", "sql"),
            ("mongodb", "nosql"),
        ],
    )
    def test_a_specific_database_satisfies_the_general_requirement(
        self, specific, general
    ):
        score, reason = skill_similarity(general, specific)
        assert score > 0.0, f"{specific} should count as evidence for {general}"
        assert "implies" in reason

    def test_entailment_is_symmetric_like_every_other_rule(self):
        assert skill_similarity("sql", "postgresql") == skill_similarity(
            "postgresql", "sql"
        )

    def test_entailment_does_not_override_explicit_distinctions(self):
        # nosql is not sql, however much the spelling suggests otherwise.
        assert skill_similarity("sql", "nosql")[0] == 0.0

    def test_a_resume_naming_postgresql_is_not_told_it_lacks_sql(self):
        assert match_skill("sql", ["python", "postgresql", "docker"]) is not None


class TestMatchSkill:
    def test_finds_the_match_in_a_list(self):
        assert match_skill("kubernetes", ["python", "k8s"])[0] == "k8s"

    def test_returns_none_when_absent(self):
        assert match_skill("rust", ["python", "docker"]) is None

    def test_prefers_the_strongest_match_over_the_first(self):
        # "reactjs" is a prefix match; "react" is exact and must win despite
        # appearing later in the list.
        matched, score, _ = match_skill("react", ["reactjs", "react"])
        assert matched == "react"
        assert score == 1.0

    def test_empty_haystack(self):
        assert match_skill("python", []) is None
