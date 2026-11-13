"""Persistence, escalation, and role-based access tests."""

import os
import re
import sqlite3
import subprocess
import sys

import pytest
from flask.testing import FlaskClient
from werkzeug.security import check_password_hash

import run

USER_PASSWORD = "user-test-password"
ADMIN_PASSWORD = "admin-test-passphrase"
AGENT_PASSWORD = "agent-test-passphrase"


def _set_csrf_from_login_page(client: FlaskClient) -> None:
    page = client.get("/login")
    match = re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        page.get_data(as_text=True),
    )
    assert match is not None
    client.environ_base["HTTP_X_CSRF_TOKEN"] = match.group(1)


def _login(client: FlaskClient, username: str, password: str) -> None:
    _set_csrf_from_login_page(client)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    client.environ_base["HTTP_X_CSRF_TOKEN"] = response.get_json()["csrf_token"]


@pytest.fixture
def database_path(tmp_path) -> str:
    return str(tmp_path / "assistant.sqlite3")


@pytest.fixture
def client(database_path: str) -> FlaskClient:
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="conversation-test-secret",
        SESSION_COOKIE_SECURE=False,
        AUTH_DATABASE=database_path,
        BOOTSTRAP_ADMIN_USERNAME=None,
        BOOTSTRAP_ADMIN_PASSWORD=None,
        BOOTSTRAP_AGENT_USERNAME=None,
        BOOTSTRAP_AGENT_PASSWORD=None,
    )
    test_client = run.app.test_client()
    _set_csrf_from_login_page(test_client)
    registration = test_client.post(
        "/api/auth/register",
        json={"username": "conversation-user", "password": USER_PASSWORD},
    )
    assert registration.status_code == 201
    _login(test_client, "conversation-user", USER_PASSWORD)
    return test_client


@pytest.fixture
def staff_clients(database_path: str) -> dict[str, FlaskClient]:
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="conversation-test-secret",
        SESSION_COOKIE_SECURE=False,
        AUTH_DATABASE=database_path,
        BOOTSTRAP_ADMIN_USERNAME="prototype-admin",
        BOOTSTRAP_ADMIN_PASSWORD=ADMIN_PASSWORD,
        BOOTSTRAP_AGENT_USERNAME="prototype-agent",
        BOOTSTRAP_AGENT_PASSWORD=AGENT_PASSWORD,
    )
    clients = {
        "admin": run.app.test_client(),
        "agent": run.app.test_client(),
    }
    _login(clients["admin"], "prototype-admin", ADMIN_PASSWORD)
    _login(clients["agent"], "prototype-agent", AGENT_PASSWORD)
    return clients


def _assistant_request(
    client: FlaskClient,
    role: str,
    query: str,
    conversation_id: str | None = None,
):
    payload = {"selected_role": role, "query": query}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return client.post("/api/assistant/execute", json=payload)


def test_conversation_messages_are_persisted_and_history_is_user_scoped(
    client: FlaskClient,
) -> None:
    executed = _assistant_request(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    )
    conversation_id = executed.get_json()["conversation_id"]

    history = client.get("/api/conversations")
    detail = client.get(f"/api/conversations/{conversation_id}")
    assert executed.status_code == 200
    assert history.status_code == 200
    assert [item["id"] for item in history.get_json()["conversations"]] == [
        conversation_id
    ]
    assert detail.status_code == 200
    result = detail.get_json()
    assert result["conversation"]["selected_role"] == "HR"
    assert [message["sender"] for message in result["messages"]] == [
        "user",
        "assistant",
    ]
    assert result["messages"][0]["body"] == "Check leave balance for employee ID EMP-42."
    assert "user_id" not in result["conversation"]


def test_conversation_history_survives_a_separate_process(
    client: FlaskClient,
) -> None:
    response = _assistant_request(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    )
    conversation_id = response.get_json()["conversation_id"]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3, sys; "
                "db = sqlite3.connect(sys.argv[1]); "
                "row = db.execute('SELECT COUNT(*) FROM messages "
                "WHERE conversation_id = ?', (sys.argv[2],)).fetchone(); "
                "print(row[0])"
            ),
            run.app.config["AUTH_DATABASE"],
            conversation_id,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "2"


def test_database_schema_is_recreated_if_file_is_removed(
    client: FlaskClient,
) -> None:
    database_path = run.app.config["AUTH_DATABASE"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0] == 1

    os.unlink(database_path)
    response = client.get("/health")
    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM assistant_roles"
        ).fetchone()[0] == 3


def test_assistant_turn_database_writes_roll_back_as_a_unit(
    client: FlaskClient,
) -> None:
    store = run.conversation_store()
    conversation_id = store.new_conversation_id()
    with sqlite3.connect(run.app.config["AUTH_DATABASE"]) as connection:
        connection.execute("DROP TABLE workflow_events")

    with pytest.raises(sqlite3.OperationalError):
        store.persist_assistant_turn(
            conversation_id=conversation_id,
            user_id="conversation-user",
            selected_role="HR",
            query="Check leave balance.",
            response="Response",
            status="success",
            intent="check_leave_balance",
            outcome="success",
            is_new_conversation=True,
            pending_intent=None,
            pending_entities=None,
            pending_confidence=None,
        )

    with sqlite3.connect(run.app.config["AUTH_DATABASE"]) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0] == 0


def test_all_three_assistant_workflows_complete_in_user_conversations(
    client: FlaskClient,
) -> None:
    cases = (
        (
            "HR",
            "Check leave balance for employee ID EMP-42.",
            "check_leave_balance",
        ),
        (
            "IT Support",
            "Please raise a ticket for my email is unavailable.",
            "raise_it_support_ticket",
        ),
        (
            "Admissions",
            "Check application status for application ID APP-42.",
            "check_application_status",
        ),
    )
    for role, query, expected_intent in cases:
        response = _assistant_request(client, role, query)
        assert response.status_code == 200
        assert response.get_json()["status"] == "success"
        assert response.get_json()["intent"] == expected_intent
        assert response.get_json()["response"]
        assert response.get_json()["conversation_id"]


def test_users_cannot_read_or_continue_another_users_conversation(
    client: FlaskClient,
) -> None:
    executed = _assistant_request(
        client,
        "Admissions",
        "Please check my application status.",
    )
    conversation_id = executed.get_json()["conversation_id"]
    client.post("/api/auth/logout")

    _set_csrf_from_login_page(client)
    registration = client.post(
        "/api/auth/register",
        json={"username": "second-user", "password": USER_PASSWORD},
    )
    assert registration.status_code == 201
    _login(client, "second-user", USER_PASSWORD)

    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert client.get("/api/conversations").get_json()["conversations"] == []
    continuation = _assistant_request(
        client,
        "Admissions",
        "APP-42",
        conversation_id,
    )
    assert continuation.status_code == 404


def test_clarification_context_is_preserved_across_conversation_turns(
    client: FlaskClient,
) -> None:
    clarification = _assistant_request(
        client,
        "Admissions",
        "Please check my application status.",
    )
    assert clarification.get_json()["status"] == "clarification_required"
    conversation_id = clarification.get_json()["conversation_id"]

    completed = _assistant_request(
        client,
        "Admissions",
        "APP-42",
        conversation_id,
    )
    assert completed.status_code == 200
    assert completed.get_json()["status"] == "success"
    assert completed.get_json()["intent"] == "check_application_status"
    assert completed.get_json()["data"]["application_id"] == "APP-42"

    detail = client.get(f"/api/conversations/{conversation_id}").get_json()
    assert [message["sender"] for message in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_conversation_role_cannot_be_changed_mid_thread(client: FlaskClient) -> None:
    initial = _assistant_request(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    ).get_json()
    response = _assistant_request(
        client,
        "Admissions",
        "Please check my application status.",
        initial["conversation_id"],
    )
    assert response.status_code == 409


def test_escalation_is_queued_accepted_resolved_and_visible_to_user(
    client: FlaskClient,
    staff_clients: dict[str, FlaskClient],
) -> None:
    escalated = _assistant_request(
        client,
        "IT Support",
        "My printer is not working.",
    )
    result = escalated.get_json()
    escalation_id = result["escalation_id"]
    conversation_id = result["conversation_id"]
    assert result["escalation_status"] == "pending"

    assert client.get("/api/agent/escalations").status_code == 403
    agent = staff_clients["agent"]
    queue = agent.get("/api/agent/escalations").get_json()["escalations"]
    assert len(queue) == 1
    assert queue[0]["id"] == escalation_id
    assert queue[0]["status"] == "pending"

    accepted = agent.post(f"/api/agent/escalations/{escalation_id}/accept")
    assert accepted.status_code == 200
    assert agent.post(f"/api/agent/escalations/{escalation_id}/accept").status_code == 409
    run.user_store().bootstrap_user(
        "unassigned-agent",
        "unassigned-agent-passphrase",
        "agent",
    )
    unassigned_agent = run.app.test_client()
    _login(unassigned_agent, "unassigned-agent", "unassigned-agent-passphrase")
    assert unassigned_agent.get("/api/agent/escalations").get_json()["escalations"] == []
    assert unassigned_agent.post(
        f"/api/agent/escalations/{escalation_id}/resolve",
        json={"response": "Not assigned."},
    ).status_code == 403
    assert agent.post(
        f"/api/agent/escalations/{escalation_id}/resolve",
        json={"response": "Please restart the printer and try again."},
    ).status_code == 200

    detail = client.get(f"/api/conversations/{conversation_id}").get_json()
    assert detail["escalation"]["status"] == "resolved"
    assert detail["messages"][-1]["sender"] == "agent"
    assert detail["messages"][-1]["body"] == "Please restart the printer and try again."


def test_escalation_input_and_acceptance_conflicts_are_reported(
    client: FlaskClient,
    staff_clients: dict[str, FlaskClient],
) -> None:
    result = _assistant_request(
        client,
        "IT Support",
        "My printer is not working.",
    ).get_json()
    agent = staff_clients["agent"]
    escalation_id = result["escalation_id"]

    invalid = agent.post(
        f"/api/agent/escalations/{escalation_id}/resolve",
        json={"response": "  "},
    )
    assert invalid.status_code == 400
    assert agent.post(
        f"/api/agent/escalations/{'0' * 32}/accept"
    ).status_code == 404
    assert agent.post(
        f"/api/agent/escalations/{escalation_id}/resolve",
        json={"response": "Not accepted yet"},
    ).status_code == 409


def test_admin_agent_permissions_bootstrap_and_dashboard_metrics(
    client: FlaskClient,
    staff_clients: dict[str, FlaskClient],
) -> None:
    _assistant_request(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    )
    _assistant_request(client, "IT Support", "My printer is not working.")

    assert client.get("/admin").status_code == 403
    assert client.get("/agent").status_code == 403
    assert client.get("/api/admin/dashboard").status_code == 403
    assert staff_clients["agent"].get("/admin").status_code == 403
    assert staff_clients["admin"].get("/admin").status_code == 200
    assert staff_clients["agent"].get("/agent").status_code == 200

    metrics = staff_clients["admin"].get("/api/admin/dashboard").get_json()
    assert metrics["prototype_metrics"] is True
    assert metrics["conversations"]["total"] == 2
    assert metrics["workflow_requests"] == 2
    assert metrics["workflow_executions"] == 1
    assert metrics["escalations"]["pending"] == 1
    assert {role["role_key"] for role in metrics["roles"]} == {
        "HR",
        "IT Support",
        "Admissions",
    }
    assert metrics["recent_activity"]

    with sqlite3.connect(run.app.config["AUTH_DATABASE"]) as connection:
        rows = connection.execute(
            "SELECT username, role, password_hash FROM users "
            "WHERE username IN ('prototype-admin', 'prototype-agent')"
        ).fetchall()
    stored = {username: (role, password_hash) for username, role, password_hash in rows}
    assert stored["prototype-admin"][0] == "admin"
    assert stored["prototype-agent"][0] == "agent"
    assert stored["prototype-admin"][1] != ADMIN_PASSWORD
    assert check_password_hash(stored["prototype-admin"][1], ADMIN_PASSWORD)
    assert stored["prototype-agent"][1] != AGENT_PASSWORD


def test_registration_cannot_select_a_privileged_account_role(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "self-promoting-user",
            "password": USER_PASSWORD,
            "role": "admin",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Account roles are assigned by the system."


def test_agent_and_admin_state_changes_require_csrf_token(
    staff_clients: dict[str, FlaskClient],
) -> None:
    admin = staff_clients["admin"]
    agent = staff_clients["agent"]
    admin.environ_base.pop("HTTP_X_CSRF_TOKEN")
    agent.environ_base.pop("HTTP_X_CSRF_TOKEN")

    assert admin.post(
        "/api/admin/roles/HR/active",
        json={"active": False},
    ).status_code == 403
    assert agent.post(
        f"/api/agent/escalations/{'0' * 32}/accept"
    ).status_code == 403


def test_admin_role_configuration_is_validated_and_enforced(
    client: FlaskClient,
    staff_clients: dict[str, FlaskClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/api/admin/roles/HR/active",
        json={"active": False},
    ).status_code == 403

    admin = staff_clients["admin"]
    invalid_type = admin.post(
        "/api/admin/roles/HR/active",
        json={"active": "false"},
    )
    assert invalid_type.status_code == 400
    assert admin.post(
        "/api/admin/roles/Finance/active",
        json={"active": True},
    ).status_code == 400

    original_registry = run.workflow_agent.workflow_registry
    monkeypatch.setattr(
        original_registry,
        "get",
        lambda role, intent: None,
    )
    invalid_activation = admin.post(
        "/api/admin/roles/HR/active",
        json={"active": True},
    )
    assert invalid_activation.status_code == 400
    monkeypatch.undo()

    deactivated = admin.post(
        "/api/admin/roles/HR/active",
        json={"active": False},
    )
    assert deactivated.status_code == 200
    inactive_request = _assistant_request(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    )
    assert inactive_request.status_code == 409
    assert admin.post(
        "/api/admin/roles/HR/active",
        json={"active": True},
    ).status_code == 200
