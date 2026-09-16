"""Accounts, sessions, and the isolation they are there to provide.

Two kinds of test live here. The first kind checks the primitives: that a
password is stored as a slow salted hash rather than anything reversible, and
that a session token is only ever kept as a digest. The second kind is the one
that actually matters to a user -- that with two real accounts signed in, one
cannot reach the other's data, however the request is phrased.

This is also the only module that removes ``conftest.signed_in_by_default``.
Everywhere else that override keeps the existing endpoint tests focused on
their own subject; here the 401 path *is* the subject.
"""

import sqlite3
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient

import main
from utils import auth as auth_module
from utils.auth import (
    DuplicateUserError,
    InvalidCredentialsError,
    UserStore,
    WeakPasswordError,
    hash_password,
    hash_token,
    normalise_email,
    validate_email,
    verify_password,
)

BASE = "/api/auth"
CAREER = "/api/career"


@pytest.fixture
def store(tmp_path):
    """A UserStore in its own file, so nothing here touches real accounts."""
    return UserStore(db_path=tmp_path / "users.db")


@pytest.fixture
def fast_hash(monkeypatch):
    """Drop the PBKDF2 work factor for the duration of a test.

    600k iterations is the right number in production and the wrong number in
    a test suite: every signup and every login would cost 0.18s, and this file
    does dozens. The algorithm under test is unchanged -- only the cost is.
    Tests that are specifically about the work factor do not use this.
    """
    monkeypatch.setattr(auth_module, "PBKDF2_ITERATIONS", 1_000)


@pytest.fixture
def anon(store, monkeypatch):
    """A client with no session, talking to an isolated user store."""
    monkeypatch.setattr(auth_module, "user_store", store)
    main.app.dependency_overrides.pop(main.current_user, None)
    with TestClient(main.app) as client:
        yield client


# --------------------------------------------------------------------------- #
# Password storage
# --------------------------------------------------------------------------- #
class TestPasswordHashing:
    def test_the_password_is_not_recoverable_from_what_is_stored(self, fast_hash):
        derived = hash_password("correct horse battery staple")
        assert b"correct horse" not in derived["password_hash"]
        assert b"correct horse" not in derived["salt"]

    def test_a_password_verifies_against_its_own_hash(self, fast_hash):
        derived = hash_password("s3cret-passphrase")
        assert verify_password(
            "s3cret-passphrase",
            derived["password_hash"],
            derived["salt"],
            derived["iterations"],
        )

    def test_a_wrong_password_does_not(self, fast_hash):
        derived = hash_password("s3cret-passphrase")
        assert not verify_password(
            "s3cret-passphrasE",
            derived["password_hash"],
            derived["salt"],
            derived["iterations"],
        )

    def test_the_same_password_hashes_differently_twice(self, fast_hash):
        """Distinct salts. Otherwise equal hashes would reveal equal passwords."""
        first = hash_password("same-password-here")
        second = hash_password("same-password-here")
        assert first["salt"] != second["salt"]
        assert first["password_hash"] != second["password_hash"]

    def test_the_iteration_count_is_stored_alongside_the_hash(self, fast_hash):
        """So the cost can be raised later without locking existing users out."""
        assert hash_password("another-password")["iterations"] == 1_000

    def test_the_shipped_work_factor_meets_the_owasp_floor(self):
        assert auth_module.PBKDF2_ITERATIONS >= 600_000

    def test_the_salt_is_long_enough(self, fast_hash):
        assert len(hash_password("another-password")["salt"]) >= 16


class TestPasswordRules:
    def test_a_short_password_is_refused(self):
        with pytest.raises(WeakPasswordError):
            auth_module.validate_password("short")

    def test_a_long_enough_password_is_accepted(self):
        assert auth_module.validate_password("long-enough-1") == "long-enough-1"

    def test_an_absurdly_long_password_is_refused(self):
        """Each attempt costs 0.18s of CPU; a megabyte password is a DoS."""
        with pytest.raises(WeakPasswordError):
            auth_module.validate_password("x" * 5000)

    def test_a_passphrase_with_no_digits_or_symbols_is_fine(self):
        """NIST SP 800-63B: length, not composition rules."""
        assert auth_module.validate_password("correct horse battery staple")


class TestEmailRules:
    def test_case_and_spacing_do_not_make_a_new_account(self):
        assert normalise_email("  Alice@Example.COM ") == "alice@example.com"

    @pytest.mark.parametrize("bad", ["", "alice", "alice@", "@example.com", "a b@c.com"])
    def test_rubbish_is_refused(self, bad):
        with pytest.raises(Exception):
            validate_email(bad)

    def test_a_normal_address_is_accepted(self):
        assert validate_email("alice@example.com") == "alice@example.com"


# --------------------------------------------------------------------------- #
# Token storage
# --------------------------------------------------------------------------- #
class TestTokenStorage:
    def test_the_plain_token_is_never_written_to_the_database(
        self, store, fast_hash
    ):
        """Someone who steals the file must not be able to sign in with it."""
        user = store.create_user("alice@example.com", "long-enough-1")
        token = store.create_session(user["user_id"])["token"]

        raw = sqlite3.connect(str(store.db_path)).execute(
            "SELECT token_hash FROM sessions"
        ).fetchone()[0]
        assert token not in str(raw)
        assert raw == hash_token(token)

    def test_two_sessions_get_different_tokens(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        first = store.create_session(user["user_id"])["token"]
        second = store.create_session(user["user_id"])["token"]
        assert first != second

    def test_a_token_is_long_enough_to_be_unguessable(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        assert len(store.create_session(user["user_id"])["token"]) >= 32


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class TestUserStore:
    def test_a_new_account_comes_back_without_its_hash(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1", "Alice")
        assert user["email"] == "alice@example.com"
        assert "password_hash" not in user
        assert "salt" not in user

    def test_the_same_email_twice_is_refused(self, store, fast_hash):
        store.create_user("alice@example.com", "long-enough-1")
        with pytest.raises(DuplicateUserError):
            store.create_user("alice@example.com", "different-password")

    def test_the_same_email_in_different_case_is_still_a_duplicate(
        self, store, fast_hash
    ):
        store.create_user("alice@example.com", "long-enough-1")
        with pytest.raises(DuplicateUserError):
            store.create_user("ALICE@example.com", "different-password")

    def test_authenticate_accepts_the_right_password(self, store, fast_hash):
        created = store.create_user("alice@example.com", "long-enough-1")
        assert store.authenticate("alice@example.com", "long-enough-1")[
            "user_id"
        ] == created["user_id"]

    def test_authenticate_refuses_the_wrong_password(self, store, fast_hash):
        store.create_user("alice@example.com", "long-enough-1")
        with pytest.raises(InvalidCredentialsError):
            store.authenticate("alice@example.com", "wrong-password-x")

    def test_an_unknown_email_raises_the_same_error_as_a_wrong_password(
        self, store, fast_hash
    ):
        """Different messages would confirm which addresses are registered."""
        store.create_user("alice@example.com", "long-enough-1")
        with pytest.raises(InvalidCredentialsError) as unknown:
            store.authenticate("nobody@example.com", "long-enough-1")
        with pytest.raises(InvalidCredentialsError) as wrong:
            store.authenticate("alice@example.com", "wrong-password-x")
        assert str(unknown.value) == str(wrong.value)

    def test_an_unknown_email_still_pays_for_a_hash(self, store, monkeypatch):
        """The timing must not answer the question the message refuses to.

        Asserted by counting hash calls rather than by timing the clock, which
        would be flaky on a shared machine.
        """
        calls = []
        original = auth_module.hash_password

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(auth_module, "PBKDF2_ITERATIONS", 1_000)
        monkeypatch.setattr(auth_module, "hash_password", counting)

        with pytest.raises(InvalidCredentialsError):
            store.authenticate("nobody@example.com", "long-enough-1")
        assert calls, "no hash was computed for an unknown email"

    def test_resolve_session_finds_the_account(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        token = store.create_session(user["user_id"])["token"]
        assert store.resolve_session(token)["user_id"] == user["user_id"]

    def test_a_made_up_token_resolves_to_nothing(self, store, fast_hash):
        assert store.resolve_session("not-a-real-token") is None

    def test_an_empty_token_resolves_to_nothing(self, store, fast_hash):
        assert store.resolve_session("") is None

    def test_an_expired_session_stops_working(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        token = store.create_session(user["user_id"], ttl_hours=-1)["token"]
        assert store.resolve_session(token) is None

    def test_signing_out_revokes_immediately(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        token = store.create_session(user["user_id"])["token"]
        assert store.delete_session(token) is True
        assert store.resolve_session(token) is None

    def test_deleting_expired_sessions_leaves_live_ones(self, store, fast_hash):
        user = store.create_user("alice@example.com", "long-enough-1")
        live = store.create_session(user["user_id"])["token"]
        store.create_session(user["user_id"], ttl_hours=-1)
        assert store.delete_expired_sessions() == 1
        assert store.resolve_session(live) is not None


# --------------------------------------------------------------------------- #
# The endpoints
# --------------------------------------------------------------------------- #
class TestSignup:
    def test_creates_an_account_and_signs_it_in(self, anon):
        response = anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1",
                  "name": "Alice"},
        )
        assert response.status_code == 201
        assert response.json()["email"] == "alice@example.com"
        assert anon.get("%s/me" % BASE).status_code == 200

    def test_the_response_never_carries_a_hash_or_a_salt(self, anon):
        body = anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        ).json()
        assert "password" not in body
        assert "password_hash" not in body
        assert "salt" not in body

    def test_a_duplicate_email_is_refused(self, anon):
        payload = {"email": "alice@example.com", "password": "long-enough-1"}
        assert anon.post("%s/signup" % BASE, json=payload).status_code == 201
        assert anon.post("%s/signup" % BASE, json=payload).status_code == 409

    def test_a_short_password_is_refused(self, anon):
        response = anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "short"},
        )
        assert response.status_code == 422

    def test_a_malformed_email_is_refused(self, anon):
        response = anon.post(
            "%s/signup" % BASE,
            json={"email": "not-an-email", "password": "long-enough-1"},
        )
        assert response.status_code in (400, 422)


class TestLogin:
    def test_the_right_password_signs_in(self, anon):
        anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        anon.post("%s/logout" % BASE)
        response = anon.post(
            "%s/login" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        assert response.status_code == 200

    def test_a_wrong_password_and_an_unknown_email_look_identical(self, anon):
        anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        anon.post("%s/logout" % BASE)

        wrong = anon.post(
            "%s/login" % BASE,
            json={"email": "alice@example.com", "password": "wrong-password-x"},
        )
        unknown = anon.post(
            "%s/login" % BASE,
            json={"email": "nobody@example.com", "password": "long-enough-1"},
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_a_short_password_is_not_rejected_by_the_schema(self, anon):
        """A 422 here would leak the length rule to someone guessing.

        Signup enforces the minimum; login must answer 401 like any other
        failure, or it becomes an oracle for which passwords are worth trying.
        """
        response = anon.post(
            "%s/login" % BASE, json={"email": "alice@example.com", "password": "x"}
        )
        assert response.status_code == 401


class TestLogoutAndMe:
    def test_me_needs_a_session(self, anon):
        assert anon.get("%s/me" % BASE).status_code == 401

    def test_me_describes_the_signed_in_account(self, anon):
        anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1",
                  "name": "Alice"},
        )
        body = anon.get("%s/me" % BASE).json()
        assert body["email"] == "alice@example.com"
        assert body["name"] == "Alice"

    def test_logout_ends_the_session(self, anon):
        anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        assert anon.post("%s/logout" % BASE).status_code == 200
        assert anon.get("%s/me" % BASE).status_code == 401

    def test_logout_without_a_session_is_not_an_error(self, anon):
        """Signing out twice is not a failure worth reporting."""
        assert anon.post("%s/logout" % BASE).status_code == 200

    def test_a_revoked_token_stops_working_immediately(self, anon, store):
        anon.post(
            "%s/signup" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        token = anon.cookies.get(main.SESSION_COOKIE)
        anon.post("%s/logout" % BASE)
        assert store.resolve_session(token) is None


# --------------------------------------------------------------------------- #
# The point of the whole exercise
# --------------------------------------------------------------------------- #
class TestProtectedRoutes:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "%s/status" % CAREER),
            ("get", "%s/my-jobs" % CAREER),
            ("get", "%s/my-applications" % CAREER),
            ("get", "%s/analytics" % CAREER),
            ("post", "%s/clear" % CAREER),
            ("post", "%s/save-job" % CAREER),
            ("post", "%s/create-application" % CAREER),
        ],
    )
    def test_no_session_means_no_data(self, anon, method, path):
        kwargs = {"json": {}} if method == "post" else {}
        assert getattr(anon, method)(path, **kwargs).status_code == 401

    def test_health_stays_open(self, anon):
        """Monitoring must not need credentials."""
        assert anon.get("/health").status_code == 200


class TestOneUserCannotReachAnother:
    """The forged-id checks. This is what "my data is private" has to mean."""

    @staticmethod
    def _signup(client, email):
        response = client.post(
            "%s/signup" % BASE, json={"email": email, "password": "long-enough-1"}
        )
        assert response.status_code == 201
        return response.json()["user_id"]

    def test_a_query_string_user_id_cannot_read_another_account(self, anon, store):
        alice = self._signup(anon, "alice@example.com")
        anon.post(
            "%s/create-application" % CAREER,
            json={"job_id": "job_1", "analysis_data": {}},
        )
        assert anon.get("%s/my-applications" % CAREER).json()["total"] == 1
        anon.post("%s/logout" % BASE)

        self._signup(anon, "bob@example.com")
        stolen = anon.get(
            "%s/my-applications" % CAREER, params={"user_id": alice}
        ).json()
        assert stolen["total"] == 0
        assert stolen["user_id"] != alice

    def test_a_body_user_id_cannot_write_into_another_account(self, anon):
        alice = self._signup(anon, "alice@example.com")
        anon.post("%s/logout" % BASE)

        self._signup(anon, "bob@example.com")
        anon.post(
            "%s/create-application" % CAREER,
            json={"job_id": "job_1", "analysis_data": {}, "user_id": alice},
        )
        anon.post("%s/logout" % BASE)

        anon.post(
            "%s/login" % BASE,
            json={"email": "alice@example.com", "password": "long-enough-1"},
        )
        assert anon.get("%s/my-applications" % CAREER).json()["total"] == 0

    def test_another_accounts_application_id_is_a_404(self, anon):
        self._signup(anon, "alice@example.com")
        app_id = anon.post(
            "%s/create-application" % CAREER,
            json={"job_id": "job_1", "analysis_data": {}},
        ).json()["application_id"]
        anon.post("%s/logout" % BASE)

        self._signup(anon, "bob@example.com")
        response = anon.get("%s/application/%s/history" % (CAREER, app_id))
        assert response.status_code == 404

    def test_another_accounts_analysis_trace_is_a_404(self, anon):
        """Same 404 as an unknown id, so ids cannot be probed for existence."""
        alice = self._signup(anon, "alice@example.com")
        main._ANALYSIS_HISTORY.clear()
        main._remember_analysis("trace-1", {"trace": {}, "status": "completed"}, alice)
        assert anon.get("%s/analysis/trace-1/trace" % CAREER).status_code == 200
        anon.post("%s/logout" % BASE)

        self._signup(anon, "bob@example.com")
        mine = anon.get("%s/analysis/trace-1/trace" % CAREER)
        missing = anon.get("%s/analysis/nope/trace" % CAREER)
        assert mine.status_code == missing.status_code == 404

    def test_each_account_gets_its_own_resume_collection(self, anon):
        """The CV is the most personal thing here, so isolation is structural.

        Separate Chroma collections mean a lookup for the wrong account finds
        nothing, rather than depending on a filter being remembered at every
        read path.
        """
        alice = self._signup(anon, "alice@example.com")
        anon.post("%s/logout" % BASE)
        bob = self._signup(anon, "bob@example.com")

        assert main._collection_for(alice) != main._collection_for(bob)

    def test_a_collection_name_cannot_be_poisoned(self):
        """The id is server-generated, but it is still filtered before use."""
        assert "/" not in main._collection_for("../../etc/passwd")
        assert " " not in main._collection_for("a b; drop table")

    def test_each_account_gets_its_own_analysis_pipeline(self):
        """The pipeline holds a retriever, so sharing one shares a resume.

        ``CompleteWorkflow.node_extract_resume`` reads the CV out of its
        retriever in preference to the text it was handed. A single cached
        instance therefore ran every account's full analysis against whichever
        resume index was attached first -- the leak this guards against.
        """
        main._user_workflows.clear()
        try:
            alice = main.get_complete_workflow("usr_alice", indexer="alice-index")
            bob = main.get_complete_workflow("usr_bob", indexer="bob-index")

            assert alice is not bob
            assert alice.retriever == "alice-index"
            assert bob.retriever == "bob-index"
            # The same account keeps its own, rather than rebuilding each call.
            assert main.get_complete_workflow("usr_alice", indexer="alice-index") is alice
        finally:
            main._user_workflows.clear()


class TestTheCachesDoNotGrowForever:
    """Per-account caches are bounded, like every other map in ``main``.

    Each is keyed by user id, so an unbounded one grows once per person who
    ever signs in and never shrinks.
    """

    def test_only_the_most_recent_accounts_stay_warm(self):
        cache = OrderedDict()
        for index in range(main.ACTIVE_ACCOUNT_LIMIT + 5):
            main._remember(cache, "usr_%d" % index, index)

        assert len(cache) == main.ACTIVE_ACCOUNT_LIMIT
        # The oldest went, the newest stayed.
        assert "usr_0" not in cache
        assert "usr_%d" % (main.ACTIVE_ACCOUNT_LIMIT + 4) in cache

    def test_using_an_account_keeps_it_warm(self):
        """Eviction is least-recently-*used*, not merely oldest-created."""
        cache = OrderedDict()
        for index in range(main.ACTIVE_ACCOUNT_LIMIT):
            main._remember(cache, "usr_%d" % index, index)

        main._remember(cache, "usr_0", 0)  # touched again
        main._remember(cache, "newcomer", 1)

        assert "usr_0" in cache
        assert "usr_1" not in cache

    def test_an_evicted_account_is_simply_rebuilt(self):
        """Nothing is lost by eviction, which is why it is safe to do.

        The cached objects are handles onto Chroma and onto the pipeline, not
        state. A dropped account gets a fresh one pointed at the same
        collection.
        """
        main._user_workflows.clear()
        try:
            first = main.get_complete_workflow("usr_evicted", indexer="index")
            main._user_workflows.clear()
            second = main.get_complete_workflow("usr_evicted", indexer="index")

            assert first is not second
            assert second.retriever == "index"
        finally:
            main._user_workflows.clear()


class TestExpiredSessionsAreSweptUp:
    def test_startup_clears_sessions_nobody_will_return_to(self, tmp_path):
        """An expired token is already refused, so this is tidying.

        A session the owner never revisits is never resolved, so the
        resolve-time check never fires and the row would sit in the table
        forever.
        """
        store = UserStore(db_path=str(tmp_path / "users.db"))
        account = store.create_user("sweep@example.com", "a long enough phrase")
        live = store.create_session(account["user_id"])
        stale = store.create_session(account["user_id"], ttl_hours=-1)

        assert store.delete_expired_sessions() == 1
        assert store.resolve_session(live["token"]) is not None
        assert store.resolve_session(stale["token"]) is None

    def test_a_failed_sweep_does_not_stop_the_app(self, monkeypatch):
        """Housekeeping must never be the reason the API will not start."""

        def explode():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(auth_module.user_store, "delete_expired_sessions", explode)
        with TestClient(main.app) as client:
            assert client.get("/health").status_code == 200
