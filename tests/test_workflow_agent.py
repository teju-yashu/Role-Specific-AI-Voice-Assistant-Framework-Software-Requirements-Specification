"""Tests for request validation and role-specific workflow execution."""

import json
from datetime import datetime
from typing import Any

import pytest

from app.agents.workflow_agent import WorkflowAgent
from app.integrations.mock_integrations import IntegrationError, MockIntegrations
from app.workflows.registry import WorkflowRegistry, create_default_workflow_registry


@pytest.mark.parametrize(
    ("role", "intent", "entities", "expected_data"),
    [
        (
            "HR",
            "check_leave_balance",
            {"employee_id": "EMP-42"},
            {"employee_id": "EMP-42", "leave_balance_days": 12, "source": "mock"},
        ),
        (
            "IT Support",
            "raise_it_support_ticket",
            {"issue_description": "Cannot connect to office Wi-Fi."},
            {
                "ticket_id": "IT-1001",
                "issue_description": "Cannot connect to office Wi-Fi.",
                "status": "open",
                "source": "mock",
            },
        ),
        (
            "Admissions",
            "check_application_status",
            {"application_id": "APP-42"},
            {
                "application_id": "APP-42",
                "application_status": "under_review",
                "source": "mock",
            },
        ),
    ],
)
def test_registered_workflows_execute_successfully(
    role: str,
    intent: str,
    entities: dict[str, Any],
    expected_data: dict[str, Any],
) -> None:
    agent = WorkflowAgent()

    result = agent.execute(role, intent, entities, confidence=0.95)

    assert result == {
        "status": "success",
        "role": role,
        "intent": intent,
        "message": "The workflow completed successfully.",
        "data": expected_data,
        "escalation": {"required": False},
    }


def test_missing_required_entity_requests_clarification() -> None:
    result = WorkflowAgent().execute(
        "HR",
        "check_leave_balance",
        {},
        confidence=0.95,
    )

    assert result["status"] == "clarification_required"
    assert result["data"] == {"missing_entities": ["employee_id"]}
    assert result["escalation"] == {"required": False}


@pytest.mark.parametrize("employee_id", [None, "", "   "])
def test_blank_required_entity_requests_clarification(employee_id: Any) -> None:
    result = WorkflowAgent().execute(
        "HR",
        "check_leave_balance",
        {"employee_id": employee_id},
        confidence=0.95,
    )

    assert result["status"] == "clarification_required"
    assert result["data"] == {"missing_entities": ["employee_id"]}


@pytest.mark.parametrize(
    "employee_id",
    [["EMP-42"], {"id": "EMP-42"}, 42, True],
)
def test_non_string_required_entity_is_rejected_before_workflow_execution(
    employee_id: Any,
) -> None:
    class TrackingIntegrations(MockIntegrations):
        called = False

        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            self.called = True
            return super().check_leave_balance(entities)

    integrations = TrackingIntegrations()
    result = WorkflowAgent(
        workflow_registry=create_default_workflow_registry(integrations)
    ).execute(
        "HR",
        "check_leave_balance",
        {"employee_id": employee_id},
        confidence=0.95,
    )

    assert result["status"] == "invalid_input"
    assert result["data"] == {"invalid_entities": ["employee_id"]}
    assert integrations.called is False


def test_low_confidence_requests_escalation_before_execution() -> None:
    result = WorkflowAgent(confidence_threshold=0.8).execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.6,
    )

    assert result["status"] == "escalation_required"
    assert result["escalation"] == {
        "required": True,
        "reason": "low_confidence",
        "confidence": 0.6,
        "threshold": 0.8,
    }


def test_confidence_at_threshold_executes_workflow() -> None:
    result = WorkflowAgent().execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.7,
    )

    assert result["status"] == "success"
    assert result["data"]["source"] == "mock"


@pytest.mark.parametrize(
    "confidence",
    [True, -0.1, 1.1, float("nan"), float("inf"), "0.9", 10**1000],
)
def test_invalid_confidence_returns_invalid_input(confidence: Any) -> None:
    result = WorkflowAgent().execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=confidence,
    )

    assert result["status"] == "invalid_input"
    assert result["message"] == "Confidence must be a finite number from 0 to 1."


@pytest.mark.parametrize(
    "confidence_threshold",
    [True, -0.1, 1.1, float("nan"), float("inf"), 10**1000],
)
def test_invalid_confidence_threshold_is_rejected(confidence_threshold: Any) -> None:
    with pytest.raises(ValueError, match="confidence_threshold"):
        WorkflowAgent(confidence_threshold=confidence_threshold)


def test_unregistered_intent_returns_unknown_intent() -> None:
    result = WorkflowAgent().execute(
        "HR",
        "approve_expense",
        {},
        confidence=0.95,
    )

    assert result["status"] == "unknown_intent"
    assert result["escalation"] == {"required": False}


def test_integration_failure_returns_structured_error() -> None:
    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise IntegrationError("Mock integration unavailable.")

    registry = create_default_workflow_registry(FailingIntegrations())
    result = WorkflowAgent(workflow_registry=registry).execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result == {
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


def test_integration_failure_is_logged_for_administrative_review(caplog: pytest.LogCaptureFixture) -> None:
    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise IntegrationError("Mock integration unavailable.")

    registry = create_default_workflow_registry(FailingIntegrations())

    with caplog.at_level("ERROR", logger="app.agents.workflow_agent"):
        WorkflowAgent(workflow_registry=registry).execute(
            "HR",
            "check_leave_balance",
            {"employee_id": "EMP-42"},
            confidence=0.95,
        )

    failure_record = json.loads(caplog.records[0].getMessage())

    assert failure_record["role"] == "HR"
    assert failure_record["intent"] == "check_leave_balance"
    assert failure_record["failure_category"] == "integration_error"
    assert failure_record["error_type"] == "IntegrationError"
    assert "error_message" not in failure_record
    assert datetime.fromisoformat(failure_record["timestamp"]).utcoffset() is not None
    assert "Mock integration unavailable." not in caplog.text


def test_failure_logging_does_not_expose_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_value = "mock-secret-value"

    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise IntegrationError(f"Integration failed with token {secret_value}.")

    registry = create_default_workflow_registry(FailingIntegrations())

    with caplog.at_level("ERROR", logger="app.agents.workflow_agent"):
        result = WorkflowAgent(workflow_registry=registry).execute(
            "HR",
            "check_leave_balance",
            {"employee_id": "EMP-42"},
            confidence=0.95,
        )

    assert result["status"] == "integration_error"
    assert secret_value not in caplog.text
    assert "IntegrationError" in caplog.text


def test_invalid_role_returns_supported_roles() -> None:
    result = WorkflowAgent().execute(
        "Finance",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result["status"] == "invalid_role"
    assert result["data"] == {"supported_roles": ["HR", "IT Support", "Admissions"]}


def test_invalid_role_type_is_returned_safely() -> None:
    result = WorkflowAgent().execute(
        {"role": "HR"},
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result["status"] == "invalid_role"
    assert result["role"] is None
    assert result["data"] == {"supported_roles": ["HR", "IT Support", "Admissions"]}


def test_non_string_intent_is_returned_safely() -> None:
    result = WorkflowAgent().execute(
        "HR",
        ["check_leave_balance"],
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result["status"] == "unknown_intent"
    assert result["intent"] is None


def test_non_object_entities_return_invalid_input() -> None:
    result = WorkflowAgent().execute(
        "HR",
        "check_leave_balance",
        ["EMP-42"],
        confidence=0.95,
    )

    assert result["status"] == "invalid_input"
    assert result["data"] is None


def test_registry_resolves_supported_workflows_case_insensitively() -> None:
    registry = create_default_workflow_registry()

    assert registry.get("hr", "CHECK_LEAVE_BALANCE") is not None
    assert registry.get("it support", "raise_it_support_ticket") is not None
    assert registry.get("admissions", "check_application_status") is not None
    assert registry.get("finance", "approve_expense") is None


def test_registry_uses_explicit_falsey_integration_adapter() -> None:
    class FalseyIntegrations(MockIntegrations):
        def __bool__(self) -> bool:
            return False

        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            return {"source": "provided"}

    registry = create_default_workflow_registry(FalseyIntegrations())
    workflow = registry.get("HR", "check_leave_balance")

    assert workflow is not None
    assert workflow.execute({"employee_id": "EMP-42"}) == {"source": "provided"}


def test_workflow_agent_uses_explicit_empty_registry() -> None:
    registry = WorkflowRegistry()

    result = WorkflowAgent(workflow_registry=registry).execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result["status"] == "unknown_intent"


def test_unexpected_workflow_failure_returns_structured_error() -> None:
    class FailingIntegrations(MockIntegrations):
        def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Unexpected mock failure.")

    registry = create_default_workflow_registry(FailingIntegrations())
    result = WorkflowAgent(workflow_registry=registry).execute(
        "HR",
        "check_leave_balance",
        {"employee_id": "EMP-42"},
        confidence=0.95,
    )

    assert result["status"] == "execution_error"
    assert result["data"] == {"failure_category": "execution_error"}
    assert result["escalation"] == {
        "required": True,
        "reason": "workflow_execution_failure",
        "failure_category": "execution_error",
    }
