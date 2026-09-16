"""Tests for the FastAPI endpoints in main.py."""

import pytest
from fastapi.testclient import TestClient

from config import settings
from tests.conftest import SAMPLE_JOB_TEXT, SAMPLE_RESUME


class TestMetaEndpoints:
    def test_root_returns_links(self, client):
        body = client.get("/").json()
        assert body["app"] == settings.APP_NAME
        assert body["health"] == "/health"

    def test_health_is_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == settings.APP_VERSION
        assert body["timestamp"]

    def test_cors_headers_are_returned_for_allowed_origin(self, client):
        origin = settings.CORS_ORIGINS[0]
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin


class TestUploadResume:
    url = "/api/career/upload-resume"

    def test_extension_check_is_case_insensitive(self, career_client):
        """An uppercase extension is the same extension.

        Kept as its own class because the check lives in ``_store_upload``,
        and a user who saves as ``RESUME.PDF`` should not be told the type is
        unsupported. The upload is refused later for having no extractable
        text, which is a different and honest complaint.
        """
        response = career_client.post(
            self.url, files={"file": ("RESUME.PDF", b"%PDF-", "application/pdf")}
        )
        assert response.status_code != 400


# --------------------------------------------------------------------------- #
# /api/career
# --------------------------------------------------------------------------- #
@pytest.fixture
def career_client(indexer):
    """A client whose career endpoints use the offline in-memory indexer."""
    import main

    main._user_workflows.clear()
    main._ANALYSIS_HISTORY.clear()
    main.app.dependency_overrides[main.get_indexer] = lambda: indexer
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    main._user_workflows.clear()
    main._ANALYSIS_HISTORY.clear()


@pytest.fixture
def indexed_client(career_client):
    career_client.post(
        "/api/career/upload-resume",
        files={"file": ("jane.txt", SAMPLE_RESUME.encode(), "text/plain")},
    )
    return career_client


class TestCareerUploadResume:
    url = "/api/career/upload-resume"

    def test_indexes_the_resume(self, career_client, indexer):
        response = career_client.post(
            self.url, files={"file": ("jane.txt", SAMPLE_RESUME.encode(), "text/plain")}
        )
        assert response.status_code == 201
        assert response.json() == {
            "status": "success",
            "message": "Resume indexed",
            "file_size": len(SAMPLE_RESUME.encode()),
        }
        assert indexer.count() > 0

    def test_rejects_unsupported_extensions(self, career_client):
        response = career_client.post(
            self.url, files={"file": ("malware.exe", b"data", "application/octet-stream")}
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_rejects_an_empty_file(self, career_client):
        response = career_client.post(
            self.url, files={"file": ("empty.txt", b"", "text/plain")}
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_the_generated_filename_is_not_leaked_in_errors(self, career_client):
        detail = career_client.post(
            self.url, files={"file": ("empty.txt", b"", "text/plain")}
        ).json()["detail"]
        assert "empty.txt" in detail

    def test_rejects_a_file_with_no_extractable_text(self, career_client):
        response = career_client.post(
            self.url, files={"file": ("scanned.txt", b"   \n  \t ", "text/plain")}
        )
        assert response.status_code == 422
        assert "No text could be extracted" in response.json()["detail"]

    def test_a_rejected_upload_leaves_nothing_on_disk(self, career_client):
        career_client.post(self.url, files={"file": ("scanned.txt", b"  \n ", "text/plain")})
        assert list(settings.UPLOAD_DIR.iterdir()) == []

    def test_path_traversal_filename_is_neutralised(self, career_client):
        response = career_client.post(
            self.url,
            files={"file": ("../../etc/passwd.txt", SAMPLE_RESUME.encode(), "text/plain")},
        )
        assert response.status_code == 201
        stored = list(settings.UPLOAD_DIR.iterdir())
        assert len(stored) == 1
        assert stored[0].parent == settings.UPLOAD_DIR

    def test_rejects_files_over_the_size_limit(self, career_client, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.001)
        response = career_client.post(
            self.url, files={"file": ("big.txt", b"x" * 5000, "text/plain")}
        )
        assert response.status_code == 413

    def test_missing_file_field_is_a_validation_error(self, career_client):
        assert career_client.post(self.url).status_code == 422


class TestAnalyzeJob:
    url = "/api/career/analyze-job"

    def test_returns_the_analysis(self, career_client):
        response = career_client.post(self.url, json={"job_description": SAMPLE_JOB_TEXT})
        assert response.status_code == 200
        body = response.json()
        assert body["title"]
        assert "python" in body["required_skills"]
        assert 0.0 <= body["confidence"] <= 1.0

    def test_carries_the_full_analyzer_contract(self, career_client):
        body = career_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        for key in (
            "tech_stack", "experience_years", "experience_level",
            "soft_skills", "education", "role_type", "seniority", "company_size",
        ):
            assert key in body

    def test_rejects_a_missing_field(self, career_client):
        assert career_client.post(self.url, json={}).status_code == 422

    def test_rejects_an_empty_description(self, career_client):
        assert career_client.post(
            self.url, json={"job_description": ""}
        ).status_code == 422

    def test_rejects_an_oversized_description(self, career_client):
        response = career_client.post(
            self.url, json={"job_description": "x" * 50_001}
        )
        assert response.status_code == 422

    def test_a_meaningless_description_is_a_400(self, career_client):
        response = career_client.post(self.url, json={"job_description": "hi"})
        assert response.status_code == 400
        assert response.json()["detail"]


class TestCalculateMatchRemoved:
    url = "/api/career/calculate-match"

    def test_the_endpoint_is_gone(self, indexed_client):
        """It was a strict subset of ``/full-analysis`` that nothing called.

        Asserted rather than simply deleted so that a caller written against
        the old route gets a 404 here, in a named test, instead of a puzzling
        failure in their own code.
        """
        response = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        )
        assert response.status_code == 404


class TestFullAnalysis:
    url = "/api/career/full-analysis"

    def test_returns_the_documented_shape(self, indexed_client):
        response = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        )
        assert response.status_code == 200
        body = response.json()
        assert {
            "overall_match",
            "recommendation",
            "analysis",
            "execution_trace",
            "total_analysis_time_ms",
        } <= set(body)

    def test_analysis_has_the_five_sections(self, indexed_client):
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        assert set(body["analysis"]) == {
            "job_analysis",
            "match_breakdown",
            "gaps",
            "resume_optimizations",
            "interview_prep",
        }

    def test_every_section_is_populated(self, indexed_client):
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        for name, section in body["analysis"].items():
            assert section, f"{name} came back empty"

    def test_the_sections_have_real_content_not_just_keys(self, indexed_client):
        """A populated dict is not the same as a useful one.

        The first version of this test only checked the sections were truthy,
        and passed while the optimiser was returning zero suggestions for every
        indexed resume.
        """
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        analysis = body["analysis"]
        assert analysis["resume_optimizations"]["improvements"]
        assert analysis["interview_prep"]["questions"]
        assert analysis["job_analysis"]["required_skills"]
        assert analysis["match_breakdown"]

    def test_values_are_in_range(self, indexed_client):
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        assert 0.0 <= body["overall_match"] <= 100.0
        assert body["recommendation"] in {"APPLY", "MAYBE", "SKIP"}
        assert body["total_analysis_time_ms"] >= 0

    def test_the_trace_covers_every_node(self, indexed_client):
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        # Seven in the straight line; the branching run adds a learnability
        # check and may add a re-score and a learning plan on top.
        assert 7 <= len(body["execution_trace"]) <= 10

    def test_it_returns_an_id_the_trace_endpoint_accepts(self, indexed_client):
        body = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        follow_up = indexed_client.get(
            f"/api/career/analysis/{body['analysis_id']}/trace"
        )
        assert follow_up.status_code == 200

    def test_ids_are_unique_per_run(self, indexed_client):
        first = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()["analysis_id"]
        second = indexed_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        ).json()["analysis_id"]
        assert first != second

    def test_a_resume_in_the_body_needs_no_index(self, career_client):
        response = career_client.post(
            self.url,
            json={
                "job_description": SAMPLE_JOB_TEXT,
                "resume_text": SAMPLE_RESUME,
            },
        )
        assert response.status_code == 200
        assert response.json()["overall_match"] > 0

    def test_it_accepts_a_multipart_upload(self, career_client):
        response = career_client.post(
            self.url,
            data={"job_description": SAMPLE_JOB_TEXT},
            files={"resume_file": ("jane.txt", SAMPLE_RESUME.encode(), "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["overall_match"] > 0

    def test_it_accepts_a_multipart_form_without_a_file(self, indexed_client):
        response = indexed_client.post(
            self.url, data={"job_description": SAMPLE_JOB_TEXT}
        )
        assert response.status_code == 200

    def test_an_uploaded_file_is_indexed(self, career_client):
        career_client.post(
            self.url,
            data={"job_description": SAMPLE_JOB_TEXT},
            files={"resume_file": ("jane.txt", SAMPLE_RESUME.encode(), "text/plain")},
        )
        assert career_client.get("/api/career/status").json()["resume_indexed"]

    def test_an_unreadable_upload_is_rejected(self, career_client):
        response = career_client.post(
            self.url,
            data={"job_description": SAMPLE_JOB_TEXT},
            files={"resume_file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code in (400, 422)

    def test_conflict_when_there_is_no_resume_anywhere(self, career_client):
        response = career_client.post(
            self.url, json={"job_description": SAMPLE_JOB_TEXT}
        )
        assert response.status_code == 409
        assert "resume" in response.json()["detail"].lower()

    def test_rejects_an_empty_description(self, indexed_client):
        assert (
            indexed_client.post(self.url, json={"job_description": "   "}).status_code
            == 422
        )

    def test_rejects_a_missing_description(self, indexed_client):
        assert indexed_client.post(self.url, json={}).status_code == 422

    def test_rejects_an_oversized_description(self, indexed_client):
        response = indexed_client.post(
            self.url, json={"job_description": "x" * 50_001}
        )
        assert response.status_code == 422

    def test_rejects_malformed_json(self, indexed_client):
        response = indexed_client.post(
            self.url,
            content=b"{not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_rejects_a_json_array(self, indexed_client):
        response = indexed_client.post(self.url, json=["nope"])
        assert response.status_code == 400

    def test_validation_matches_the_other_endpoints(self, indexed_client):
        # Two endpoints returning different codes for the same mistake is the
        # kind of inconsistency that costs an integrator an afternoon.
        for url in (self.url, "/api/career/analyze-job"):
            assert indexed_client.post(url, json={}).status_code == 422

    def test_two_words_are_not_an_advert(self, indexed_client):
        """A perfect score off sixteen characters is a number with nothing
        behind it.

        `/analyze-job` refused "Python developer" as too short to analyse while
        the scoring route once scored it 100.0 APPLY -- "nothing major standing
        in the way" -- because the pipeline caught the analyzer's complaint
        internally and went on with the one skill it had scraped out. Both
        routes ask the same function the same question.
        """
        response = indexed_client.post(
            self.url, json={"job_description": "Python developer"}
        )
        assert response.status_code == 400
        assert "too short" in response.json()["detail"]

    def test_the_refusal_matches_the_analyze_job_route(self, indexed_client):
        """Same input, same verdict, whichever door it comes through."""
        short = {"job_description": "Python developer"}
        assert (
            indexed_client.post("/api/career/analyze-job", json=short).status_code
            == indexed_client.post(self.url, json=short).status_code
        )

    def test_unreadable_input_is_refused_too(self, indexed_client):
        """Long enough to pass the length check, not prose."""
        response = indexed_client.post(
            self.url, json={"job_description": "!@#$%^&*()_+{}|:<>?~`-=[]" * 4}
        )
        assert response.status_code == 400
        assert "readable text" in response.json()["detail"]


class TestAnalysisTrace:
    def url(self, analysis_id):
        return f"/api/career/analysis/{analysis_id}/trace"

    @pytest.fixture
    def analysed(self, indexed_client):
        body = indexed_client.post(
            "/api/career/full-analysis", json={"job_description": SAMPLE_JOB_TEXT}
        ).json()
        return indexed_client, body["analysis_id"]

    def test_returns_a_node_list(self, analysed):
        client, analysis_id = analysed
        response = client.get(self.url(analysis_id))
        assert response.status_code == 200
        assert 7 <= len(response.json()["nodes"]) <= 10

    def test_each_node_has_the_documented_fields(self, analysed):
        client, analysis_id = analysed
        for node in client.get(self.url(analysis_id)).json()["nodes"]:
            assert set(node) == {
                "name",
                "status",
                "duration_ms",
                "output_summary",
            }

    def test_nodes_use_readable_names(self, analysed):
        client, analysis_id = analysed
        names = [n["name"] for n in client.get(self.url(analysis_id)).json()["nodes"]]
        assert names[:5] == [
            "Job Analyzer",
            "Resume Extraction",
            "Match Calculator",
            "Gap Detector",
            "Resume Optimizer",
        ]
        # Whichever branch ran, every name is prose rather than an identifier.
        for name in names:
            assert name and "_" not in name

    def test_summaries_are_filled_in(self, analysed):
        client, analysis_id = analysed
        nodes = client.get(self.url(analysis_id)).json()["nodes"]
        assert all(node["output_summary"] for node in nodes)

    def test_durations_are_integers(self, analysed):
        client, analysis_id = analysed
        for node in client.get(self.url(analysis_id)).json()["nodes"]:
            assert isinstance(node["duration_ms"], int)
            assert node["duration_ms"] >= 0

    def test_an_unknown_id_is_a_404(self, career_client):
        response = career_client.get(self.url("does-not-exist"))
        assert response.status_code == 404
        assert response.json()["detail"]

    def test_a_path_traversal_id_is_a_404_not_a_file_read(self, career_client):
        response = career_client.get(self.url("..%2F..%2Fetc%2Fpasswd"))
        assert response.status_code == 404

    def test_the_trace_is_repeatable(self, analysed):
        client, analysis_id = analysed
        first = client.get(self.url(analysis_id)).json()
        assert first == client.get(self.url(analysis_id)).json()

    def test_the_store_holds_no_personal_data(self, analysed):
        # The trace store is unauthenticated and in-process. It keeps node
        # names and timings; a resume kept here would be personal data sitting
        # behind no access control at all.
        import json

        import main

        client, analysis_id = analysed
        blob = json.dumps(main._ANALYSIS_HISTORY[analysis_id])
        assert "Jane" not in blob
        assert SAMPLE_RESUME[:40] not in blob

    def test_the_store_is_bounded(self, indexed_client):
        import main

        main._ANALYSIS_HISTORY.clear()
        for index in range(main.ANALYSIS_HISTORY_LIMIT + 5):
            main._remember_analysis(
                f"id-{index}", {"trace": {}, "status": "completed"}, "local"
            )
        assert len(main._ANALYSIS_HISTORY) == main.ANALYSIS_HISTORY_LIMIT

    def test_the_oldest_analysis_is_evicted_first(self, indexed_client):
        import main

        main._ANALYSIS_HISTORY.clear()
        for index in range(main.ANALYSIS_HISTORY_LIMIT + 1):
            main._remember_analysis(
                f"id-{index}", {"trace": {}, "status": "completed"}, "local"
            )
        assert "id-0" not in main._ANALYSIS_HISTORY
        assert f"id-{main.ANALYSIS_HISTORY_LIMIT}" in main._ANALYSIS_HISTORY


class TestCareerStatus:
    url = "/api/career/status"

    def test_reports_not_indexed_when_empty(self, career_client):
        response = career_client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            "resume_indexed": False,
            "status": "ready",
            "chunks": 0,
        }

    def test_reports_indexed_after_an_upload(self, indexed_client):
        body = indexed_client.get(self.url).json()
        assert body["resume_indexed"] is True
        assert body["status"] == "ready"
        assert body["chunks"] > 0

    def test_a_broken_index_reports_degraded_rather_than_raising(self, career_client, indexer):
        def explode():
            raise RuntimeError("chroma is unreachable")

        indexer.stats = explode
        response = career_client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            "resume_indexed": False,
            "status": "degraded",
            "chunks": 0,
        }


class TestClearIndex:
    url = "/api/career/clear"

    def test_clears_an_indexed_resume(self, indexed_client, indexer):
        before = indexer.count()
        assert before > 0

        response = indexed_client.post(self.url)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["chunks_removed"] == before
        assert indexer.count() == 0

    def test_status_reflects_the_clear(self, indexed_client):
        indexed_client.post(self.url)
        assert indexed_client.get("/api/career/status").json()["resume_indexed"] is False

    def test_clearing_an_empty_index_is_not_an_error(self, career_client):
        response = career_client.post(self.url)
        assert response.status_code == 200
        assert response.json()["chunks_removed"] == 0


class TestRequestLogging:
    def test_every_response_carries_a_request_id(self, client):
        assert client.get("/health").headers["X-Request-ID"]

    def test_each_request_gets_a_distinct_id(self, client):
        ids = {client.get("/health").headers["X-Request-ID"] for _ in range(3)}
        assert len(ids) == 3

    def test_requests_are_logged_without_the_body(self, career_client, caplog):
        with caplog.at_level("INFO"):
            career_client.post(
                "/api/career/analyze-job", json={"job_description": SAMPLE_JOB_TEXT}
            )
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "POST /api/career/analyze-job -> 200" in logged
        # The advert itself must not appear in the log line.
        assert SAMPLE_JOB_TEXT not in logged

    def test_failures_are_logged_at_warning(self, career_client, caplog):
        with caplog.at_level("WARNING"):
            career_client.post("/api/career/analyze-job", json={})
        assert any("-> 422" in record.getMessage() for record in caplog.records)
