"""Flask API tests for role-specific workflow execution."""

from typing import Any

import pytest
from flask.testing import FlaskClient

import run
from app.agents.workflow_agent import WorkflowAgent
from app.integrations.mock_integrations import IntegrationError, MockIntegrations
from app.nlu.response_generator import ResponseGenerator, ResponseProviderUnavailable
from app.workflows.registry import create_default_workflow_registry


@pytest.fixture
def client() -> FlaskClient:
    """Provide an isolated Flask test client."""
    run.app.config.update(TESTING=True)
    return run.app.test_client()


def _request_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "selected_role": "HR",
        "intent": "check_leave_balance",
        "entities": {"employee_id": "EMP-42"},
        "confidence": 0.95,
    }
    payload.update(overrides)
    return payload


def test_workflow_api_executes_successfully(client: FlaskClient) -> None:
    response = client.post("/api/workflows/execute", json=_request_payload())

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "role": "HR",
        "intent": "check_leave_balance",
        "message": "The workflow completed successfully.",
        "data": {
            "employee_id": "EMP-42",
            "leave_balance_days": 12,
            "source": "mock",
        },
        "escalation": {"required": False},
    }


def test_assistant_api_recognizes_query_and_executes_workflow(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check my leave balance for employee ID EMP-42.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert response.get_json()["intent"] == "check_leave_balance"
    assert response.get_json()["data"]["employee_id"] == "EMP-42"
    assert response.get_json()["data"]["source"] == "mock"
    assert response.get_json()["response"] == (
        "Your leave balance for employee EMP-42 is 12 days."
    )
    assert response.get_json()["response_source"] == "deterministic"
    assert response.get_json()["response_evaluation"]["relevant"] is True


def test_assistant_api_replaces_unsupported_leave_approval_claim(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnsupportedClaimProvider:
        name = "test_provider"

        def generate(
            self,
            system_prompt: str,
            user_prompt: str,
            context: dict[str, Any],
        ) -> str:
            return (
                "Your leave balance for employee EMP-42 is 12 days. "
                "Your leave was approved."
            )

    monkeypatch.setattr(
        run,
        "response_generator",
        ResponseGenerator(provider=UnsupportedClaimProvider()),
    )

    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check leave balance for employee ID EMP-42.",
        },
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["status"] == "success"
    assert result["response"] == (
        "Your leave balance for employee EMP-42 is 12 days."
    )
    assert result["response_replaced"] is True
    assert result["response_evaluation"]["relevant"] is True


def test_assistant_api_asks_for_missing_required_entity(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "Admissions",
            "query": "Please check my application status.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "clarification_required"
    assert response.get_json()["data"]["missing_entities"] == ["application_id"]
    assert response.get_json()["clarification_question"] == "What is your application ID?"


def test_assistant_api_returns_unknown_intent_for_unsupported_query(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/assistant/execute",
        json={"selected_role": "HR", "query": "What is the weather today?"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "unknown_intent"
    assert response.get_json()["intent"] == "unknown"


def test_assistant_api_rejects_malformed_json(client: FlaskClient) -> None:
    response = client.post(
        "/api/assistant/execute",
        data='{"selected_role":',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Request body must be a JSON object."}


def test_assistant_api_escalates_when_recognized_intent_is_low_confidence(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/assistant/execute",
        json={"selected_role": "IT Support", "query": "My printer is not working."},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "escalation_required"
    assert response.get_json()["escalation"]["reason"] == "low_confidence"
    assert response.get_json()["response_evaluation"]["relevant"] is True


def test_assistant_api_preserves_workflow_failure_and_generates_safe_response(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run.workflow_agent,
        "execute",
        lambda **kwargs: {
            "status": "integration_error",
            "role": "HR",
            "intent": "check_leave_balance",
            "message": "The required integration could not complete the request.",
            "data": {"failure_category": "integration_error"},
            "escalation": {"required": True, "reason": "integration_failure"},
        },
    )

    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check leave balance for employee ID EMP-42.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "integration_error"
    assert "couldn’t complete" in response.get_json()["response"]
    assert response.get_json()["response_evaluation"]["relevant"] is True


def test_assistant_api_replaces_irrelevant_generated_response(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IrrelevantProvider:
        name = "test_provider"

        def generate(
            self,
            system_prompt: str,
            user_prompt: str,
            context: dict[str, Any],
        ) -> str:
            return "IT Support says your leave balance is 999 days."

    monkeypatch.setattr(
        run,
        "response_generator",
        ResponseGenerator(provider=IrrelevantProvider()),
    )

    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check leave balance for employee ID EMP-42.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert response.get_json()["response"] == (
        "Your leave balance for employee EMP-42 is 12 days."
    )
    assert response.get_json()["response_source"] == "deterministic_fallback"
    assert response.get_json()["response_replaced"] is True
    assert response.get_json()["response_evaluation"]["relevant"] is True


def test_assistant_api_fails_safely_when_selected_provider_is_unavailable(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls = 0
    original_execute = run.workflow_agent.execute

    def tracked_execute(**kwargs: Any) -> dict[str, Any]:
        nonlocal execute_calls
        execute_calls += 1
        return original_execute(**kwargs)

    class UnavailableProvider:
        name = "requested_provider"

        def generate(
            self,
            system_prompt: str,
            user_prompt: str,
            context: dict[str, Any],
        ) -> str:
            raise ResponseProviderUnavailable("private provider details")

    monkeypatch.setattr(run.workflow_agent, "execute", tracked_execute)
    monkeypatch.setattr(
        run,
        "response_generator",
        ResponseGenerator(provider=UnavailableProvider()),
    )

    response = client.post(
        "/api/assistant/execute",
        json={
            "selected_role": "HR",
            "query": "Check leave balance for employee ID EMP-42.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert response.get_json()["response_source"] == "unavailable"
    assert response.get_json()["response_generation_status"] == "unavailable"
    assert "workflow outcome is available" in response.get_json()["response"]
    assert "private provider details" not in response.get_data(as_text=True)
    assert execute_calls == 1


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        ({}, ["selected_role", "query"]),
        ({"selected_role": "HR"}, ["query"]),
        ({"query": "check leave"}, ["selected_role"]),
    ],
)
def test_assistant_api_rejects_missing_fields(
    client: FlaskClient,
    payload: dict[str, Any],
    expected_fields: list[str],
) -> None:
    response = client.post("/api/assistant/execute", json=payload)

    assert response.status_code == 400
    assert response.get_json()["fields"] == expected_fields


@pytest.mark.parametrize(
    "payload",
    [
        {"selected_role": "HR", "query": ""},
        {"selected_role": "Finance", "query": "check my balance"},
        {"selected_role": "HR", "query": 42},
    ],
)
def test_assistant_api_rejects_invalid_role_or_query(
    client: FlaskClient,
    payload: dict[str, Any],
) -> None:
    response = client.post("/api/assistant/execute", json=payload)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_workflow_api_rejects_missing_request_fields(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        json={"selected_role": "HR", "intent": "check_leave_balance"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Missing required fields.",
        "fields": ["entities", "confidence"],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_role", 42),
        ("intent", None),
        ("entities", []),
        ("confidence", True),
        ("confidence", "0.95"),
    ],
)
def test_workflow_api_rejects_invalid_field_types(
    client: FlaskClient,
    field: str,
    value: Any,
) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(**{field: value}),
    )

    assert response.status_code == 400
    assert response.is_json
    assert "error" in response.get_json()


@pytest.mark.parametrize(
    "confidence",
    [-0.1, 1.1, float("nan"), float("inf"), 10**1000],
)
def test_workflow_api_rejects_out_of_range_confidence(
    client: FlaskClient,
    confidence: Any,
) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(confidence=confidence),
    )

    assert response.status_code == 400
    assert response.get_json()["status"] == "invalid_input"


def test_workflow_api_rejects_malformed_json(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        data='{"selected_role":',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Request body must be a JSON object."}


@pytest.mark.parametrize("payload", [[], "not an object"])
def test_workflow_api_rejects_non_object_json(
    client: FlaskClient,
    payload: Any,
) -> None:
    response = client.post("/api/workflows/execute", json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Request body must be a JSON object."}


def test_workflow_api_rejects_json_null(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        data="null",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Request body must be a JSON object."}


def test_workflow_api_returns_clarification_for_missing_workflow_entities(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(entities={}),
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "clarification_required"
    assert response.get_json()["data"] == {"missing_entities": ["employee_id"]}


def test_workflow_api_preserves_low_confidence_escalation(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(confidence=0.2),
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "escalation_required"
    assert response.get_json()["escalation"]["required"] is True
    assert response.get_json()["escalation"]["reason"] == "low_confidence"


def test_workflow_api_returns_unknown_intent(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(intent="approve_expense"),
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "unknown_intent"
    assert response.get_json()["escalation"] == {"required": False}


def test_workflow_api_returns_bad_request_for_unknown_role(client: FlaskClient) -> None:
    response = client.post(
        "/api/workflows/execute",
        json=_request_payload(selected_role="Finance"),
    )

    assert response.status_code == 400
    assert response.get_json()["status"] == "invalid_role"


def test_workflow_api_returns_escalated_integration_failure(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise IntegrationError("Mock integration unavailable.")

    registry = create_default_workflow_registry(FailingIntegrations())
    monkeypatch.setattr(
        run,
        "workflow_agent",
        WorkflowAgent(workflow_registry=registry),
    )

    response = client.post("/api/workflows/execute", json=_request_payload())

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "integration_error",
        "role": "HR",
        "intent": "check_leave_balance",
        "message": "The required integration could not complete the request.",
        "data": {"failure_category": "integration_error"},
        "escalation": {
            "required": True,
            "reason": "integration_failure",
            "failure_category": "integration_error",
        },
    }


def test_workflow_api_returns_safe_response_for_unexpected_failure(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Internal exception with private details.")

    registry = create_default_workflow_registry(FailingIntegrations())
    monkeypatch.setattr(
        run,
        "workflow_agent",
        WorkflowAgent(workflow_registry=registry),
    )

    response = client.post("/api/workflows/execute", json=_request_payload())

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "execution_error",
        "role": "HR",
        "intent": "check_leave_balance",
        "message": "The workflow could not be completed.",
        "data": {"failure_category": "execution_error"},
        "escalation": {
            "required": True,
            "reason": "workflow_execution_failure",
            "failure_category": "execution_error",
        },
    }
    assert "private details" not in response.get_data(as_text=True)


def test_workflow_api_preserves_cors_for_cross_origin_requests(
    client: FlaskClient,
) -> None:
    origin = "https://client.example"
    response = client.options(
        "/api/workflows/execute",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


@pytest.mark.parametrize(
    "endpoint",
    ["/", "/health"],
)
def test_existing_get_endpoints_remain_available(
    client: FlaskClient,
    endpoint: str,
) -> None:
    response = client.get(endpoint)

    assert response.status_code == 200
    if endpoint == "/":
        assert response.get_json() == {
            "project_name": run.PROJECT_NAME,
            "status": "Backend is running",
        }
    else:
        assert response.get_json() == {
            "status": "healthy",
            "service": run.PROJECT_NAME,
        }
