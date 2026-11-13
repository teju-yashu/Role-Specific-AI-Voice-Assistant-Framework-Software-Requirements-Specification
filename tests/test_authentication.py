import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from werkzeug.security import check_password_hash

import run

TEST_USERNAME = "test-user"
TEST_PASSWORD = "correct horse battery"


@pytest.fixture
def client(tmp_path) -> FlaskClient:
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="authentication-test-secret",
        SESSION_COOKIE_SECURE=False,
        AUTH_DATABASE=str(tmp_path / "users.sqlite3"),
        BOOTSTRAP_ADMIN_USERNAME=None,
        BOOTSTRAP_ADMIN_PASSWORD=None,
        BOOTSTRAP_AGENT_USERNAME=None,
        BOOTSTRAP_AGENT_PASSWORD=None,
    )
    test_client = run.app.test_client()
    page = test_client.get("/login")
    token = re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        page.get_data(as_text=True),
    )
    assert token is not None
    test_client.environ_base["HTTP_X_CSRF_TOKEN"] = token.group(1)
    return test_client


def register(client: FlaskClient, username: str = TEST_USERNAME):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": TEST_PASSWORD},
    )


def login(client: FlaskClient, password: str = TEST_PASSWORD):
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USERNAME, "password": password},
    )
    if response.status_code == 200:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = response.get_json()["csrf_token"]
    return response


def test_login_and_registration_pages_render_both_account_forms(
    client: FlaskClient,
) -> None:
    for path in ("/login", "/register"):
        response = client.get(path)

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'id="login-form"' in html
        assert 'id="register-form"' in html
        assert 'id="login-form" method="post"' in html
        assert 'id="register-form" method="post"' in html
        assert 'name="csrf-token"' in html


def test_registration_and_login_create_an_authenticated_session(
    client: FlaskClient,
) -> None:
    registration = register(client)

    assert registration.status_code == 201
    assert registration.get_json() == {
        "status": "registered",
        "username": TEST_USERNAME,
    }
    assert client.get("/chat").status_code == 302

    authentication = login(client)

    assert authentication.status_code == 200
    assert authentication.get_json()["status"] == "authenticated"
    assert authentication.get_json()["username"] == TEST_USERNAME
    assert authentication.get_json()["redirect_url"] == "/chat"
    assert client.get("/chat").status_code == 200


def test_duplicate_registration_returns_conflict(client: FlaskClient) -> None:
    assert register(client).status_code == 201

    duplicate = register(client, username=" TEST-USER ")

    assert duplicate.status_code == 409
    assert duplicate.get_json() == {
        "error": "An account with that username already exists."
    }


def test_invalid_credentials_are_rejected_without_account_enumeration(
    client: FlaskClient,
) -> None:
    assert register(client).status_code == 201

    wrong_password = login(client, password="wrong password")
    unknown_user = client.post(
        "/api/auth/login",
        json={"username": "unknown-user", "password": "wrong password"},
    )

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.get_json() == unknown_user.get_json()


def test_logout_clears_session_and_protected_access(client: FlaskClient) -> None:
    assert register(client).status_code == 201
    assert login(client).status_code == 200

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.get_json()["status"] == "logged_out"
    assert client.get("/chat").status_code == 302
    unauthorized = client.post(
        "/api/assistant/execute",
        json={"selected_role": "HR", "query": "check leave balance"},
    )
    assert unauthorized.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/api/assistant/execute", "/api/workflows/execute"],
)
def test_unauthenticated_api_access_returns_json_401(
    client: FlaskClient,
    path: str,
) -> None:
    response = client.post(path, json={})

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json() == {"error": "Authentication required."}
    assert client.get("/chat").status_code == 302


def test_authenticated_user_can_execute_both_existing_apis(
    client: FlaskClient,
) -> None:
    assert register(client).status_code == 201
    assert login(client).status_code == 200

    assistant_response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check leave balance for employee ID EMP-42.",
        },
    )
    workflow_response = client.post(
        "/api/workflows/execute",
        json={
            "selected_role": "HR",
            "intent": "check_leave_balance",
            "entities": {"employee_id": "EMP-42"},
            "confidence": 0.95,
        },
    )

    assert assistant_response.status_code == 200
    assert assistant_response.get_json()["status"] == "success"
    assert workflow_response.status_code == 200
    assert workflow_response.get_json()["status"] == "success"


def test_password_is_hashed_and_never_returned_or_logged(
    client: FlaskClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registration = register(client)
    database_path = run.app.config["AUTH_DATABASE"]

    with sqlite3.connect(database_path) as connection:
        stored_username, stored_hash = connection.execute(
            "SELECT username, password_hash FROM users"
        ).fetchone()

    assert registration.status_code == 201
    assert stored_username == TEST_USERNAME
    assert stored_hash != TEST_PASSWORD
    assert check_password_hash(stored_hash, TEST_PASSWORD)
    assert TEST_PASSWORD not in registration.get_data(as_text=True)
    authentication = login(client)
    assert TEST_PASSWORD not in authentication.get_data(as_text=True)
    assert stored_hash not in authentication.get_data(as_text=True)
    assert TEST_PASSWORD not in caplog.text
    assert stored_hash not in caplog.text


def test_authentication_and_protected_api_requests_require_csrf_token(
    client: FlaskClient,
) -> None:
    client.environ_base.pop("HTTP_X_CSRF_TOKEN")

    registration = register(client)
    assert registration.status_code == 403

    client.environ_base["HTTP_X_CSRF_TOKEN"] = re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        client.get("/login").get_data(as_text=True),
    ).group(1)
    assert register(client).status_code == 201
    assert login(client).status_code == 200
    client.environ_base.pop("HTTP_X_CSRF_TOKEN")

    protected = client.post("/api/assistant/execute", json={})

    assert protected.status_code == 403
    assert protected.get_json() == {"error": "A valid CSRF token is required."}


def test_session_cookie_has_secure_attributes_when_enabled(
    tmp_path,
) -> None:
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="authentication-cookie-test-secret",
        SESSION_COOKIE_SECURE=True,
        AUTH_DATABASE=str(tmp_path / "cookie-users.sqlite3"),
    )
    secure_client = run.app.test_client()

    response = secure_client.get("/login", base_url="https://localhost")
    set_cookie = response.headers["Set-Cookie"]

    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "Secure" in set_cookie


def test_login_session_is_permanent_with_configured_lifetime(
    client: FlaskClient,
) -> None:
    assert register(client).status_code == 201
    assert login(client).status_code == 200
    with client.session_transaction() as authenticated_session:
        assert authenticated_session.permanent is True
    assert run.app.permanent_session_lifetime.total_seconds() == 12 * 60 * 60


def test_malformed_stored_password_hash_fails_closed(
    client: FlaskClient,
) -> None:
    assert register(client).status_code == 201
    with sqlite3.connect(run.app.config["AUTH_DATABASE"]) as connection:
        connection.execute(
            "UPDATE users SET password_hash = 'invalid-hash' WHERE username = ?",
            (TEST_USERNAME,),
        )

    response = login(client)
    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid username or password."}


def test_bootstrap_does_not_promote_an_existing_user(
    client: FlaskClient,
) -> None:
    assert register(client).status_code == 201
    with pytest.raises(RuntimeError, match="never promotes an existing account"):
        run.user_store().bootstrap_user(TEST_USERNAME, TEST_PASSWORD, "admin")

    assert run.user_store().get_role(TEST_USERNAME) == "user"


def test_corrupted_sqlite_database_returns_safe_error(tmp_path) -> None:
    database_path = tmp_path / "corrupted.sqlite3"
    database_path.write_bytes(b"not a sqlite database")
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="corrupted-database-test-secret",
        SESSION_COOKIE_SECURE=False,
        AUTH_DATABASE=str(database_path),
        BOOTSTRAP_ADMIN_USERNAME=None,
        BOOTSTRAP_ADMIN_PASSWORD=None,
        BOOTSTRAP_AGENT_USERNAME=None,
        BOOTSTRAP_AGENT_PASSWORD=None,
    )

    response = run.app.test_client().get("/login")
    assert response.status_code == 503
    assert b"temporarily unavailable" in response.data
    assert b"not a sqlite database" not in response.data


def test_missing_stable_session_secret_stops_server_startup(tmp_path) -> None:
    environment = os.environ.copy()
    environment.pop("FLASK_SECRET_KEY", None)
    environment.pop("FLASK_DEBUG", None)
    environment["AUTH_DATABASE"] = str(tmp_path / "server.sqlite3")
    for key in (
        "BOOTSTRAP_ADMIN_USERNAME",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_AGENT_USERNAME",
        "BOOTSTRAP_AGENT_PASSWORD",
        "CORS_ALLOWED_ORIGINS",
    ):
        environment.pop(key, None)
    result = subprocess.run(
        [sys.executable, str(Path(run.__file__).resolve())],
        cwd=Path(run.__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Set FLASK_SECRET_KEY" in result.stderr
    assert "Application database initialization failed" not in result.stderr


def test_wsgi_requests_fail_closed_without_stable_session_secret(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    run.app.config["TESTING"] = False

    response = run.app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_data(as_text=True) == "The service is not configured."


def test_corrupt_database_stops_startup_without_printing_database_contents(
    tmp_path,
) -> None:
    database_path = tmp_path / "corrupted-startup.sqlite3"
    database_path.write_bytes(b"private database bytes")
    environment = os.environ.copy()
    environment["FLASK_SECRET_KEY"] = "startup-check-secret-value-at-least-32"
    environment["AUTH_DATABASE"] = str(database_path)
    for key in (
        "BOOTSTRAP_ADMIN_USERNAME",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_AGENT_USERNAME",
        "BOOTSTRAP_AGENT_PASSWORD",
        "CORS_ALLOWED_ORIGINS",
    ):
        environment.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(Path(run.__file__).resolve())],
        cwd=Path(run.__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Application database initialization failed" in result.stderr
    assert "private database bytes" not in result.stderr


def test_cors_is_limited_to_configured_exact_origins(tmp_path) -> None:
    allowed_origin = "https://demo.example.edu"
    environment = os.environ.copy()
    environment["CORS_ALLOWED_ORIGINS"] = allowed_origin
    environment["AUTH_DATABASE"] = str(tmp_path / "cors.sqlite3")
    for key in (
        "BOOTSTRAP_ADMIN_USERNAME",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_AGENT_USERNAME",
        "BOOTSTRAP_AGENT_PASSWORD",
    ):
        environment.pop(key, None)
    script = (
        "import run, sys; "
        "run.app.config.update(TESTING=True, AUTH_DATABASE=sys.argv[1]); "
        "response = run.app.test_client().options("
        "'/api/workflows/execute', headers={"
        "'Origin': sys.argv[2], 'Access-Control-Request-Method': 'POST'}); "
        "print(response.headers.get('Access-Control-Allow-Origin', ''))"
    )
    allowed = subprocess.run(
        [sys.executable, "-c", script, environment["AUTH_DATABASE"], allowed_origin],
        cwd=Path(run.__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    denied = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            environment["AUTH_DATABASE"],
            "https://other.example.edu",
        ],
        cwd=Path(run.__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert allowed.stdout.strip() == allowed_origin
    assert not denied.stdout.strip()


def test_unauthenticated_user_and_staff_apis_reject_access(
    client: FlaskClient,
) -> None:
    paths = (
        ("/api/conversations", "GET"),
        ("/api/conversations/" + ("a" * 32), "GET"),
        ("/api/agent/escalations", "GET"),
        ("/api/admin/dashboard", "GET"),
        ("/api/admin/roles/HR/active", "POST"),
        ("/api/agent/escalations/" + ("a" * 32) + "/accept", "POST"),
    )
    guest = run.app.test_client()
    for path, method in paths:
        response = guest.get(path) if method == "GET" else guest.post(path, json={})
        assert response.status_code == 401
        assert response.is_json
        assert response.get_json() == {"error": "Authentication required."}

    assert guest.get("/chat").status_code == 302
    assert guest.get("/agent").status_code == 302
    assert guest.get("/admin").status_code == 302
