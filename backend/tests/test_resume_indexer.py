"""Tests for the pure text-processing helpers in rag.resume_indexer."""

import pytest

from config import settings
from rag.resume_indexer import (
    DocumentParseError,
    Section,
    _build_where,
    _clean_metadata,
    _normalise_project,
    _to_similarity,
    chunk_text,
    detect_section,
    extract_profile,
    extract_text,
    format_as_context,
    new_resume_id,
    split_bullets,
    split_into_sections,
)
from models.career_models import SearchResult


class TestChunkText:
    def test_short_text_stays_a_single_chunk(self):
        assert chunk_text("hello world", chunk_size=100, overlap=10) == ["hello world"]

    def test_splits_long_text(self):
        chunks = chunk_text("a" * 250, chunk_size=100, overlap=0)
        assert [len(c) for c in chunks] == [100, 100, 50]

    def test_chunks_overlap(self):
        chunks = chunk_text("0123456789", chunk_size=5, overlap=2)
        assert chunks[0] == "01234"
        assert chunks[1].startswith("34")

    def test_zero_overlap_is_respected(self):
        # Regression: `overlap or default` treated 0 as "unset".
        assert len(chunk_text("a" * 250, chunk_size=100, overlap=0)) == 3

    def test_empty_text_returns_no_chunks(self):
        assert chunk_text("") == []

    def test_whitespace_only_text_returns_no_chunks(self):
        assert chunk_text("      \n\t  ") == []

    def test_defaults_come_from_settings(self):
        assert settings.CHUNK_SIZE == 250
        assert settings.CHUNK_OVERLAP == 50
        chunks = chunk_text("x" * (settings.CHUNK_SIZE + 10))
        assert len(chunks[0]) == settings.CHUNK_SIZE

    def test_overlap_larger_than_chunk_still_terminates(self):
        assert len(chunk_text("abcdef", chunk_size=2, overlap=10)) == 6

    def test_never_splits_a_word_in_half(self):
        """The whole point of the sentence-aware rewrite.

        Fixed-width slicing turned "LangChain implementation" into "LangCha" +
        "in implementation", so a search for LangChain could not find the chunk
        that was about LangChain.
        """
        text = (
            "Built a RAG system with LangChain implementation. "
            "Used Chroma for vector storage. "
            "Created REST APIs with FastAPI framework."
        )
        words = set(text.replace(".", "").split())
        for chunk in chunk_text(text, chunk_size=60, overlap=15):
            for word in chunk.replace(".", "").split():
                assert word in words, f"{word!r} is a fragment, not a word"

    def test_prefers_to_end_on_a_sentence_boundary(self):
        text = "First sentence here. Second sentence here. Third sentence here."
        chunks = chunk_text(text, chunk_size=45, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert chunk.endswith("."), f"{chunk!r} stops mid-sentence"

    def test_treats_a_newline_as_a_boundary(self):
        # Resumes are bullet lists far more often than they are prose.
        text = "- Built RAG system with LangChain\n- Implemented embeddings pipeline"
        chunks = chunk_text(text, chunk_size=40, overlap=0)
        assert chunks == [
            "- Built RAG system with LangChain",
            "- Implemented embeddings pipeline",
        ]

    def test_a_single_huge_token_is_still_split(self):
        # No boundary to respect, e.g. a long URL: fall back to characters
        # rather than emitting one oversized chunk.
        chunks = chunk_text("x" * 200, chunk_size=50, overlap=0)
        assert [len(c) for c in chunks] == [50, 50, 50, 50]

    def test_no_chunk_exceeds_the_size_limit(self):
        text = ". ".join(f"Sentence number {i} about Python and FastAPI" for i in range(40))
        for chunk in chunk_text(text, chunk_size=120, overlap=30):
            assert len(chunk) <= 120


class TestExtractText:
    def test_reads_plain_text_file(self, tmp_path):
        path = tmp_path / "resume.txt"
        path.write_text("Python engineer", encoding="utf-8")
        assert extract_text(path) == "Python engineer"

    def test_reads_markdown(self, tmp_path):
        path = tmp_path / "resume.md"
        path.write_text("# Jane\nPython", encoding="utf-8")
        assert "Jane" in extract_text(path)

    def test_accepts_a_string_path(self, tmp_path):
        path = tmp_path / "resume.txt"
        path.write_text("hello", encoding="utf-8")
        assert extract_text(str(path)) == "hello"

    def test_tolerates_invalid_encoding(self, tmp_path):
        path = tmp_path / "weird.txt"
        path.write_bytes(b"caf\xe9 python")
        assert "python" in extract_text(path)

    def test_corrupt_pdf_raises_parse_error(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"this is definitely not a pdf")
        with pytest.raises(DocumentParseError):
            extract_text(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(DocumentParseError):
            extract_text(tmp_path / "nope.txt")


def _docx(tmp_path, body: str, name: str = "resume.docx"):
    """A minimal but real .docx: a zip with one WordprocessingML part."""
    import zipfile

    document = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>%s</w:body></w:document>' % body
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    return path


def _para(*runs: str) -> str:
    return "<w:p>%s</w:p>" % "".join("<w:r><w:t>%s</w:t></w:r>" % r for r in runs)


class TestExtractDocx:
    """Word documents are read with the standard library, not python-docx.

    The dependency was avoided on purpose - see the note in ``_extract_docx``.
    These tests exist because that decision only holds if the hand-rolled
    parse is actually correct about the things a library would have handled.
    """

    def test_reads_the_text(self, tmp_path):
        path = _docx(tmp_path, _para("Rahul Medi") + _para("Python engineer"))
        assert "Rahul Medi" in extract_text(path)
        assert "Python engineer" in extract_text(path)

    def test_joins_runs_inside_one_paragraph(self, tmp_path):
        # Word splits a paragraph into runs at every formatting change, and
        # will happily cut a single word in half. Taking only the first run,
        # or joining runs with a space, both corrupt the text: this exact
        # case turns "FastAPI" into "Fast" or "Fast API", and the skill
        # matcher would then miss it.
        path = _docx(tmp_path, _para("I use Fast", "API", " daily"))
        assert "I use FastAPI daily" in extract_text(path)

    def test_keeps_paragraphs_on_separate_lines(self, tmp_path):
        # The section splitter and the bullet splitter both work on line
        # boundaries, so a document flattened into one line loses every
        # heading and every bullet.
        path = _docx(tmp_path, _para("SKILLS") + _para("Python"))
        assert extract_text(path).splitlines()[:2] == ["SKILLS", "Python"]

    def test_a_renamed_doc_says_what_to_do(self, tmp_path):
        path = tmp_path / "old.docx"
        path.write_bytes(b"\xd0\xcf\x11\xe0 an actual .doc")
        with pytest.raises(DocumentParseError, match="save it as .docx or PDF"):
            extract_text(path)

    def test_a_zip_that_is_not_a_word_file_is_rejected(self, tmp_path):
        import zipfile

        path = tmp_path / "photos.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("cat.jpg", "not xml")
        with pytest.raises(DocumentParseError, match="not a Word document"):
            extract_text(path)

    def test_an_image_only_document_is_not_silently_empty(self, tmp_path):
        # Indexing an empty string would look like a successful upload and
        # then quietly score every job at zero.
        path = _docx(tmp_path, "")
        with pytest.raises(DocumentParseError, match="no readable text"):
            extract_text(path)

    def test_a_document_declaring_a_dtd_is_refused(self, tmp_path):
        # ElementTree expands internal entities, so a few hundred bytes can
        # take the process down. Word never emits a DTD, so refusing costs
        # nothing.
        import zipfile

        path = tmp_path / "bomb.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]><w:p/>',
            )
        with pytest.raises(DocumentParseError, match="declares a DTD"):
            extract_text(path)

    def test_a_zip_bomb_is_refused_before_it_is_unpacked(self, tmp_path):
        import zipfile

        path = tmp_path / "bomb.docx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            # Compresses to a few hundred bytes; refused on its declared
            # uncompressed size, so it is never actually expanded.
            archive.writestr("word/document.xml", "a" * (11 * 1024 * 1024))
        with pytest.raises(DocumentParseError, match="too large to be a resume"):
            extract_text(path)


class TestDetectSection:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("Skills", Section.SKILLS),
            ("TECHNICAL SKILLS", Section.SKILLS),
            ("Tech Stack", Section.SKILLS),
            ("Work Experience", Section.EXPERIENCE),
            ("Professional Experience:", Section.EXPERIENCE),
            ("Education", Section.EDUCATION),
            ("Projects", Section.PROJECTS),
            ("## Achievements", Section.ACHIEVEMENTS),
            ("Certifications", Section.ACHIEVEMENTS),
            ("Summary", Section.SUMMARY),
            # Banner headings. get_full_context() writes this style, so failing
            # to recognise it made every reconstructed resume parse as one
            # undifferentiated block.
            ("=== ACHIEVEMENTS ===", Section.ACHIEVEMENTS),
            ("==== EXPERIENCE ====", Section.EXPERIENCE),
            ("= Skills =", Section.SKILLS),
        ],
    )
    def test_recognises_headings(self, line, expected):
        assert detect_section(line) == expected

    def test_reconstructed_context_keeps_its_sections(self, indexer, resume_file):
        """A resume that goes through the index must come back parseable.

        The agents downstream all work section by section. When this broke they
        did not error -- they returned empty results, which is far harder to
        notice.
        """
        indexer.index_resume(resume_file)
        sections = {
            section for section, _ in split_into_sections(indexer.get_full_context())
        }
        assert Section.EXPERIENCE in sections
        assert Section.SKILLS in sections
        assert len(sections) > 1

    def test_body_text_is_not_a_heading(self):
        assert detect_section("Built microservices with Python and Docker") is None

    def test_long_lines_are_never_headings(self):
        assert detect_section("Skills " + "x" * 60) is None

    def test_blank_line(self):
        assert detect_section("   ") is None


class TestSplitIntoSections:
    def test_groups_lines_under_headings(self):
        sections = dict(split_into_sections("Skills\nPython\n\nEducation\nBSc"))
        assert sections[Section.SKILLS] == "Python"
        assert sections[Section.EDUCATION] == "BSc"

    def test_text_before_any_heading_is_kept(self):
        sections = dict(split_into_sections("Jane Developer\nSkills\nPython"))
        assert sections[Section.OTHER] == "Jane Developer"

    def test_repeated_heading_merges_content(self):
        sections = dict(split_into_sections("Skills\nPython\nEducation\nBSc\nSkills\nDocker"))
        assert sections[Section.SKILLS] == "Python\nDocker"

    def test_blank_input(self):
        assert split_into_sections("") == []

    def test_headings_with_no_body_are_dropped(self):
        assert split_into_sections("Skills\n\nEducation\n") == []


class TestExtractProfile:
    def test_pulls_out_the_main_fields(self):
        from tests.conftest import SAMPLE_RESUME

        profile = extract_profile(SAMPLE_RESUME)
        assert profile.name == "Jane Developer"
        assert profile.email == "jane.developer@example.com"
        assert profile.experience_years == 7.0
        assert {"python", "fastapi", "docker"} <= set(profile.skills)

    def test_takes_the_largest_years_figure(self):
        assert extract_profile("3 years here, 11 years there").experience_years == 11.0

    def test_handles_plus_notation(self):
        assert extract_profile("8+ years of Python").experience_years == 8.0

    def test_no_details_gives_an_empty_profile(self):
        profile = extract_profile("...")
        assert profile.name is None
        assert profile.email is None
        assert profile.experience_years is None
        assert profile.skills == []

    def test_lines_with_digits_are_not_treated_as_names(self):
        assert extract_profile("555 Main Street\nBuilt things").name is None

    def test_sentence_fragments_are_not_treated_as_names(self):
        assert extract_profile("Built things for people").name is None


class TestSplitBullets:
    @pytest.mark.parametrize("bullet", ["- ", "* ", "\u2022 ", "1. ", "2) "])
    def test_strips_bullet_markers(self, bullet):
        assert split_bullets(f"{bullet}Shipped the thing") == ["Shipped the thing"]

    def test_one_entry_per_line(self):
        assert len(split_bullets("- one thing\n- two thing\n- three thing")) == 3

    def test_ignores_blank_and_tiny_lines(self):
        assert split_bullets("\n\n-\nok\nSomething real") == ["Something real"]

    def test_empty_text(self):
        assert split_bullets("") == []


class TestNormaliseProject:
    def test_dict_entry(self):
        name, body, technologies = _normalise_project(
            {
                "name": "CareerPilot",
                "description": "A resume assistant",
                "technologies": ["FastAPI", "ChromaDB"],
                "role": "Lead",
            },
            0,
        )
        assert name == "CareerPilot"
        assert "A resume assistant" in body
        assert "Lead" in body
        assert technologies == ["FastAPI", "ChromaDB"]

    def test_technologies_given_as_a_string(self):
        _, _, technologies = _normalise_project({"name": "X", "tech": "python, docker"}, 0)
        assert technologies == ["python", "docker"]

    def test_string_entry_infers_skills(self):
        name, body, technologies = _normalise_project("Built a Django app with Redis", 0)
        assert name.startswith("Built a Django")
        assert body == "Built a Django app with Redis"
        assert set(technologies) == {"django", "redis"}

    def test_unnamed_dict_falls_back_to_position(self):
        name, _, _ = _normalise_project({"description": "no name"}, 4)
        assert name == "Project 5"


class TestSmallHelpers:
    def test_similarity_inverts_distance(self):
        assert _to_similarity(0.0) == 1.0
        assert _to_similarity(0.25) == 0.75

    def test_similarity_is_clamped(self):
        assert _to_similarity(5.0) == 0.0
        assert _to_similarity(-1.0) == 1.0
        assert _to_similarity(None) == 0.0

    def test_clean_metadata_drops_none_and_joins_lists(self):
        cleaned = _clean_metadata({"a": None, "b": ["x", "y"], "c": 3, "d": True})
        assert cleaned == {"b": "x, y", "c": 3, "d": True}

    def test_clean_metadata_drops_empty_lists(self):
        assert _clean_metadata({"skills": []}) == {}

    def test_build_where_with_nothing(self):
        assert _build_where(None, None) is None

    def test_build_where_single_value_avoids_in_operator(self):
        assert _build_where(["resume"], None) == {"type": "resume"}

    def test_build_where_multiple_values(self):
        assert _build_where(None, ["skills", "projects"]) == {
            "section": {"$in": ["skills", "projects"]}
        }

    def test_build_where_combines_with_and(self):
        where = _build_where(["resume"], ["skills"])
        assert where == {"$and": [{"type": "resume"}, {"section": "skills"}]}

    def test_format_as_context_on_empty_results(self):
        assert "No relevant information" in format_as_context([])

    def test_format_as_context_includes_scores(self):
        hit = SearchResult(chunk_id="a:0", text="Python expert", score=0.87, section="skills")
        assert format_as_context([hit]) == "[skills | relevance 0.87] Python expert"


class TestNewResumeId:
    def test_returns_a_32_character_hex_string(self):
        resume_id = new_resume_id()
        assert len(resume_id) == 32
        int(resume_id, 16)

    def test_ids_are_unique(self):
        assert len({new_resume_id() for _ in range(100)}) == 100
