"""Tests for the ResumeIndexer class against a real in-memory Chroma store.

The embedder is a deterministic offline fake (see conftest.HashingEmbedder), so
these tests never download a model or hit the network.
"""

import pytest

from config import settings
from rag.resume_indexer import (
    ContentType,
    FileValidationError,
    ResumeIndexer,
    Section,
)

PROJECTS = [
    {
        "name": "CareerPilot",
        "role": "Lead engineer",
        "description": "Retrieval augmented resume assistant",
        "technologies": ["FastAPI", "ChromaDB", "LangGraph"],
        "impact": "Cut screening time in half",
    },
    {
        "name": "Ledger",
        "description": "Double entry accounting service",
        "technologies": ["Django", "PostgreSQL"],
    },
]

ACHIEVEMENTS = """
- Reduced deployment time from 40 minutes to 6 minutes with Docker and CI/CD
- Mentored 5 junior engineers through their first production launch
- Spoke at PyCon about vector databases
"""


class TestIndexResume:
    def test_returns_a_summary(self, indexer, resume_file):
        result = indexer.index_resume(resume_file)
        assert result["status"] == "indexed"
        assert result["type"] == ContentType.RESUME.value
        assert result["source"] == "jane_developer.txt"
        assert result["document_id"].startswith("resume-")
        assert result["chunks_indexed"] > 0
        assert result["characters"] > 0

    def test_extracts_profile_metadata(self, indexer, resume_file):
        profile = indexer.index_resume(resume_file)["profile"]
        assert profile["name"] == "Jane Developer"
        assert profile["email"] == "jane.developer@example.com"
        assert profile["experience_years"] == 7.0
        assert "fastapi" in profile["skills"]

    def test_splits_content_across_sections(self, indexer, resume_file):
        sections = indexer.index_resume(resume_file)["sections"]
        assert Section.SKILLS.value in sections
        assert Section.EXPERIENCE.value in sections
        assert Section.EDUCATION.value in sections

    def test_chunks_land_in_the_store(self, indexer, resume_file):
        result = indexer.index_resume(resume_file)
        # every content chunk, plus one profile record
        assert indexer.count() == result["chunks_indexed"] + 1

    def test_the_reported_document_count_reconciles_with_the_store(
        self, indexer, resume_file
    ):
        """`chunks_indexed` alone never matched `count()`, which read as a bug.

        The profile record is a document but not a chunk of the resume, so the
        two numbers legitimately differ. Reporting both means the caller can
        reconcile them instead of hunting for an off-by-one.
        """
        result = indexer.index_resume(resume_file)
        assert result["profile_indexed"] is True
        assert result["documents_indexed"] == result["chunks_indexed"] + 1
        assert result["documents_indexed"] == indexer.count()

    def test_metadata_is_attached_to_every_chunk(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        for _, metadata in indexer._get_all():
            assert metadata["source"]
            assert metadata["chunk_id"]
            assert metadata["type"]
            assert metadata["section"]
            assert "chunk_index" in metadata
            assert metadata["indexed_at"]

    def test_accepts_a_string_path(self, indexer, resume_file):
        assert indexer.index_resume(str(resume_file))["status"] == "indexed"

    def test_indexing_the_same_file_twice_stores_one_copy(self, indexer, resume_file):
        """The second upload of identical text must not be stored again.

        This previously asserted the opposite. It was pinning what the code did,
        not what it should do: the live collection had grown to 27 rows holding
        9 distinct chunks, because every upload gets a fresh generated filename
        and nothing compared content. The cost was not just space - duplicates
        score identically, so a top_k=5 search returned 5 rows carrying only 2
        distinct facts.
        """
        first = indexer.index_resume(resume_file)
        before = indexer.count()
        second = indexer.index_resume(resume_file)

        assert first["document_id"] != second["document_id"]
        assert indexer.count() == before, "identical text was stored twice"
        assert second["chunks_written"] == 0
        assert second["chunks_reused"] == second["chunks_indexed"]

    def test_the_first_upload_still_reports_what_it_wrote(self, indexer, resume_file):
        first = indexer.index_resume(resume_file)
        assert first["chunks_written"] == first["chunks_indexed"]
        assert first["chunks_reused"] == 0

    def test_a_genuinely_different_resume_is_still_indexed(self, indexer, resume_file, tmp_path):
        """De-duplication must not become de-duplication of everything."""
        indexer.index_resume(resume_file)
        before = indexer.count()

        other = tmp_path / "someone_else.txt"
        other.write_text(
            "EXPERIENCE\nRust systems engineer at Foundry, 2019-2024.\n"
            "Wrote the storage layer and the wire protocol.\n",
            encoding="utf-8",
        )
        result = indexer.index_resume(other)

        assert result["chunks_written"] > 0
        assert indexer.count() > before

    def test_a_second_resume_joins_the_first_rather_than_replacing_it(
        self, indexer, resume_file, tmp_path
    ):
        """Indexing appends. Three places in the UI and docs said it replaced.

        The settings page read "One resume is indexed at a time. Uploading
        another replaces it", its button said "Replace resume", and the
        full-analysis docstring said an attached file "replaces whatever was
        there". Measured against a running backend, a second upload took the
        index from 8 chunks to 21 and every later analysis scored against both
        resumes at once.

        Nothing here is a bug in the indexer -- appending is the intended
        behaviour and `clear_index` is the documented way to swap. The bug was
        that the app described the opposite, so this pins the behaviour the
        wording now claims.
        """
        indexer.index_resume(resume_file)

        other = tmp_path / "someone_else.txt"
        other.write_text(
            "EXPERIENCE\nCobol maintainer at Ledgerworks, 1998-2024.\n"
            "Kept the nightly settlement batch running.\n",
            encoding="utf-8",
        )
        indexer.index_resume(other)

        context = indexer.get_full_context()
        assert "Ledgerworks" in context, "the second resume is missing"
        assert "Foundry" in context or "Python" in context or "EXPERIENCE" in context, (
            "the first resume was evicted, so this really is a replace"
        )

    def test_duplicates_no_longer_crowd_out_the_results(self, indexer, resume_file):
        """The reason de-duplication is a correctness fix, not a tidy-up."""
        for _ in range(3):
            indexer.index_resume(resume_file)
        results = indexer.search("python developer experience", top_k=5)
        texts = [r.text for r in results]
        assert len(texts) == len(set(texts)), "the same chunk was returned twice"

    def test_whitespace_only_file_reports_empty(self, indexer, tmp_path):
        path = tmp_path / "blank.txt"
        path.write_text("   \n\n   ", encoding="utf-8")
        result = indexer.index_resume(path)
        assert result["status"] == "empty"
        assert result["chunks_indexed"] == 0
        assert indexer.count() == 0

    def test_resume_without_headings_still_indexes(self, indexer, tmp_path):
        path = tmp_path / "flat.txt"
        path.write_text("I write Python and deploy with Docker every day.", encoding="utf-8")
        result = indexer.index_resume(path)
        assert result["status"] == "indexed"
        assert Section.OTHER.value in result["sections"]


class TestFileValidation:
    def test_missing_file(self, indexer, tmp_path):
        with pytest.raises(FileValidationError, match="File not found"):
            indexer.index_resume(tmp_path / "nope.pdf")

    def test_directory_instead_of_file(self, indexer, tmp_path):
        with pytest.raises(FileValidationError, match="Not a file"):
            indexer.index_resume(tmp_path)

    def test_unsupported_extension(self, indexer, tmp_path):
        # .rtf, not .docx: Word documents are read now. An older .doc still
        # is not, and neither is this.
        path = tmp_path / "resume.rtf"
        path.write_text("content", encoding="utf-8")
        with pytest.raises(FileValidationError, match="Unsupported file type"):
            indexer.index_resume(path)

    def test_empty_file(self, indexer, tmp_path):
        path = tmp_path / "resume.txt"
        path.write_bytes(b"")
        with pytest.raises(FileValidationError, match="empty"):
            indexer.index_resume(path)

    def test_file_over_the_size_limit(self, indexer, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.0001)
        path = tmp_path / "big.txt"
        path.write_text("x" * 5000, encoding="utf-8")
        with pytest.raises(FileValidationError, match="over the"):
            indexer.index_resume(path)

    def test_nothing_is_written_when_validation_fails(self, indexer, tmp_path):
        with pytest.raises(FileValidationError):
            indexer.index_resume(tmp_path / "nope.pdf")
        assert indexer.count() == 0


class TestIndexProjects:
    def test_indexes_each_project(self, indexer):
        result = indexer.index_projects(PROJECTS)
        assert result["status"] == "indexed"
        assert result["projects_indexed"] == 2
        assert result["project_names"] == ["CareerPilot", "Ledger"]
        assert indexer.count() == result["chunks_indexed"]

    def test_stores_technologies_in_metadata(self, indexer):
        indexer.index_projects(PROJECTS)
        technologies = {
            metadata.get("technologies") for _, metadata in indexer._get_all()
        }
        assert "FastAPI, ChromaDB, LangGraph" in technologies

    def test_tags_chunks_as_projects(self, indexer):
        indexer.index_projects(PROJECTS)
        for _, metadata in indexer._get_all():
            assert metadata["type"] == ContentType.PROJECT.value
            assert metadata["section"] == Section.PROJECTS.value

    def test_accepts_plain_strings(self, indexer):
        result = indexer.index_projects(["Built a Flask API backed by Redis"])
        assert result["projects_indexed"] == 1
        assert indexer.count() == 1

    def test_empty_list(self, indexer):
        result = indexer.index_projects([])
        assert result["status"] == "empty"
        assert result["chunks_indexed"] == 0
        assert indexer.count() == 0

    def test_entry_without_text_is_skipped(self, indexer):
        result = indexer.index_projects([""])
        assert result["status"] == "empty"
        assert result["projects_indexed"] == 0


class TestIndexAchievements:
    def test_one_document_per_bullet(self, indexer):
        result = indexer.index_achievements(ACHIEVEMENTS)
        assert result["status"] == "indexed"
        assert result["achievements_indexed"] == 3
        assert indexer.count() == 3

    def test_tags_chunks_as_achievements(self, indexer):
        indexer.index_achievements(ACHIEVEMENTS)
        for _, metadata in indexer._get_all():
            assert metadata["type"] == ContentType.ACHIEVEMENT.value
            assert metadata["section"] == Section.ACHIEVEMENTS.value

    def test_detects_skills_inside_achievements(self, indexer):
        indexer.index_achievements(ACHIEVEMENTS)
        skills = " ".join(str(m.get("skills", "")) for _, m in indexer._get_all())
        assert "docker" in skills

    @pytest.mark.parametrize("text", ["", "   \n\n  ", None])
    def test_empty_input(self, indexer, text):
        result = indexer.index_achievements(text)
        assert result["status"] == "empty"
        assert indexer.count() == 0


class TestSearch:
    @pytest.fixture(autouse=True)
    def _populate(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        indexer.index_projects(PROJECTS)
        indexer.index_achievements(ACHIEVEMENTS)

    def test_search_returns_scored_hits(self, indexer):
        hits = indexer.search("Python FastAPI")
        assert hits
        assert all(0.0 <= hit.score <= 1.0 for hit in hits)
        assert all(hit.chunk_id for hit in hits)

    def test_hits_are_ordered_best_first(self, indexer):
        scores = [hit.score for hit in indexer.search("Docker Kubernetes")]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_is_respected(self, indexer):
        assert len(indexer.search("Python", top_k=2)) <= 2

    def test_top_k_of_zero_returns_nothing(self, indexer):
        assert indexer.search("Python", top_k=0) == []

    def test_blank_query_returns_nothing(self, indexer):
        assert indexer.search("   ") == []

    def test_search_skills_finds_the_skills_section(self, indexer):
        hits = indexer.search_skills("Python FastAPI Docker")
        assert hits
        assert any(hit.section == Section.SKILLS.value for hit in hits)

    def test_search_experience_finds_work_history(self, indexer):
        hits = indexer.search_experience("microservices at Acme Corp")
        assert hits
        assert any(
            hit.section in (Section.EXPERIENCE.value, Section.PROJECTS.value) for hit in hits
        )

    def test_content_type_filter(self, indexer):
        hits = indexer.search("accounting", content_types=[ContentType.PROJECT.value])
        assert hits
        assert all(hit.content_type == ContentType.PROJECT.value for hit in hits)

    def test_technology_filter_keeps_only_mentions(self, indexer):
        hits = indexer.search_by_technology("chromadb")
        assert hits
        assert all("chromadb" in (hit.text + str(hit.metadata)).lower() for hit in hits)

    def test_technology_filter_with_no_match_returns_empty(self, indexer):
        assert indexer.search_by_technology("cobol") == []

    def test_results_carry_source_and_metadata(self, indexer):
        hit = indexer.search("Python")[0]
        assert hit.source
        assert hit.metadata["document_id"]

    def test_as_context_is_readable(self, indexer):
        hit = indexer.search("Python")[0]
        rendered = hit.as_context()
        assert "relevance" in rendered
        assert hit.text[:20] in rendered


class TestSearchEdgeCases:
    def test_search_on_an_empty_index(self, indexer):
        assert indexer.search("anything") == []
        assert indexer.search_skills("anything") == []
        assert indexer.search_experience("anything") == []

    def test_section_filter_falls_back_when_nothing_matches(self, indexer, tmp_path):
        path = tmp_path / "flat.txt"
        path.write_text("I write Python and deploy with Docker every day.", encoding="utf-8")
        indexer.index_resume(path)
        # Everything landed in `other`, so a skills-only filter matches nothing.
        assert indexer.search_skills("Python") != []

    def test_fallback_can_be_disabled(self, indexer, tmp_path):
        path = tmp_path / "flat.txt"
        path.write_text("I write Python and deploy with Docker every day.", encoding="utf-8")
        indexer.index_resume(path)
        assert (
            indexer.search(
                "Python", sections=[Section.SKILLS.value], fallback_to_all=False
            )
            == []
        )


class TestGetFullContext:
    def test_empty_index_gives_a_clear_message(self, indexer):
        assert indexer.get_full_context() == "No resume data has been indexed yet."

    def test_includes_every_source(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        indexer.index_projects(PROJECTS)
        indexer.index_achievements(ACHIEVEMENTS)

        context = indexer.get_full_context()
        assert "CANDIDATE PROFILE" in context
        assert "Jane Developer" in context
        assert "CareerPilot" in context
        assert "PyCon" in context
        assert "State University" in context

    def test_has_section_headings(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        context = indexer.get_full_context()
        assert "=== SKILLS ===" in context
        assert "=== EXPERIENCE ===" in context

    def test_chunks_are_ordered_within_a_section(self, indexer, tmp_path):
        path = tmp_path / "long.txt"
        body = "\n".join(f"Line {i:03d} about engineering work" for i in range(40))
        path.write_text(f"Experience\n{body}", encoding="utf-8")
        indexer.index_resume(path)

        context = indexer.get_full_context()
        assert context.index("Line 000") < context.index("Line 039")


class TestGetProfile:
    def test_empty_index_returns_a_blank_profile(self, indexer):
        profile = indexer.get_profile()
        assert profile.name is None
        assert profile.skills == []

    def test_reads_back_the_indexed_profile(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        profile = indexer.get_profile()
        assert profile.name == "Jane Developer"
        assert profile.email == "jane.developer@example.com"
        assert profile.experience_years == 7.0
        assert "python" in profile.skills


class TestClearIndex:
    def test_removes_everything(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        assert indexer.count() > 0

        indexer.clear_index()
        assert indexer.count() == 0
        assert indexer.is_empty()

    def test_is_safe_on_an_empty_index(self, indexer):
        indexer.clear_index()
        indexer.clear_index()
        assert indexer.count() == 0

    def test_index_is_usable_again_afterwards(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        indexer.clear_index()
        assert indexer.index_resume(resume_file)["status"] == "indexed"
        assert indexer.count() > 0


class TestStats:
    def test_empty_index(self, indexer):
        stats = indexer.stats()
        assert stats["total_chunks"] == 0
        assert stats["empty"] is True

    def test_counts_by_type_and_section(self, indexer, resume_file):
        indexer.index_resume(resume_file)
        indexer.index_projects(PROJECTS)
        indexer.index_achievements(ACHIEVEMENTS)

        stats = indexer.stats()
        assert stats["empty"] is False
        assert stats["by_type"][ContentType.PROJECT.value] == 2
        assert stats["by_type"][ContentType.ACHIEVEMENT.value] == 3
        assert stats["by_type"][ContentType.PROFILE.value] == 1
        assert Section.SKILLS.value in stats["by_section"]
        assert "jane_developer.txt" in stats["sources"]


class TestEmbedderUsage:
    def test_model_is_not_loaded_on_construction(self):
        # Constructing the default indexer must not import torch or download a model.
        instance = ResumeIndexer(persist=False)
        assert instance._embedder._model is None

    def test_injected_embedder_is_used(self, indexer, embedder, resume_file):
        indexer.index_resume(resume_file)
        assert embedder.calls

    def test_every_chunk_gets_embedded(self, indexer, embedder):
        indexer.index_achievements("- one achievement here\n- two achievement here")
        embedded = sum(len(batch) for batch in embedder.calls)
        assert embedded == 2

    def test_vectors_are_normalised(self, embedder):
        vector = embedder.encode(["python docker"])[0]
        assert abs(sum(value * value for value in vector) - 1.0) < 1e-9
