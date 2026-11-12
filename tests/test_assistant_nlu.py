"""Tests for deterministic role-specific intent and entity recognition."""

from typing import Any

import pytest

from app.agents.workflow_agent import WorkflowAgent
from app.nlu.assistant_nlu import RuleBasedAssistantNLU


@pytest.mark.parametrize(
    ("role", "query", "intent", "entities"),
    [
        (
            "HR",
            "Check my leave balance for employee ID EMP-42.",
            "check_leave_balance",
            {"employee_id": "EMP-42"},
        ),
        (
            "IT Support",
            "My system is unable to connect to the office network.",
            "raise_it_support_ticket",
            {"issue_description": "My system is unable to connect to the office network."},
        ),
        (
            "Admissions",
            "What is the application status for application ID APP-42?",
            "check_application_status",
            {"application_id": "APP-42"},
        ),
    ],
)
def test_recognizes_supported_role_intent_and_entities(
    role: str,
    query: str,
    intent: str,
    entities: dict[str, str],
) -> None:
    result = RuleBasedAssistantNLU().interpret(role, query)

    assert result["selected_role"] == role
    assert result["intent"] == intent
    assert result["entities"] == entities
    assert 0.7 <= result["confidence"] <= 1.0


def test_extracts_numeric_employee_id_when_labeled() -> None:
    result = RuleBasedAssistantNLU().interpret(
        "HR",
        "How much leave do I have? My employee ID is 42.",
    )

    assert result["entities"] == {"employee_id": "42"}


def test_extracts_nonstandard_ids_only_when_labeled() -> None:
    nlu = RuleBasedAssistantNLU()

    employee_result = nlu.interpret(
        "HR",
        "Check my leave balance for employee ID E-42-X.",
    )
    application_result = nlu.interpret(
        "Admissions",
        "Check my application status for application number UG-2026-42.",
    )

    assert employee_result["entities"] == {"employee_id": "E-42-X"}
    assert application_result["entities"] == {"application_id": "UG-2026-42"}


def test_does_not_invent_missing_required_entities() -> None:
    result = RuleBasedAssistantNLU().interpret(
        "Admissions",
        "Please check my application status.",
    )

    assert result["intent"] == "check_application_status"
    assert result["entities"] == {}


def test_confidence_is_a_deterministic_rule_based_score() -> None:
    nlu = RuleBasedAssistantNLU()

    explicit = nlu.interpret("HR", "Check my leave balance.")
    contextual = nlu.interpret("HR", "How much leave do I have?")

    assert explicit["confidence"] == 0.9
    assert contextual["confidence"] == 0.78
    assert explicit["confidence"] > contextual["confidence"]


def test_ambiguous_recognized_intent_receives_low_confidence() -> None:
    result = RuleBasedAssistantNLU().interpret(
        "IT Support",
        "My printer is not working.",
    )

    assert result["intent"] == "raise_it_support_ticket"
    assert result["confidence"] == 0.55
    assert result["entities"] == {"issue_description": "My printer is not working."}


def test_unrecognized_query_returns_unknown_intent() -> None:
    result = RuleBasedAssistantNLU().interpret("HR", "What is the weather today?")

    assert result == {
        "selected_role": "HR",
        "intent": "unknown",
        "entities": {},
        "confidence": 0.0,
    }


@pytest.mark.parametrize(
    ("role", "query"),
    [
        ("", "check leave balance"),
        ("HR", ""),
        ("HR", None),
        ("Finance", "check my balance"),
    ],
)
def test_invalid_role_or_query_is_rejected(role: Any, query: Any) -> None:
    with pytest.raises(ValueError):
        RuleBasedAssistantNLU().interpret(role, query)


def test_clarification_question_uses_entity_specific_wording() -> None:
    question = RuleBasedAssistantNLU.clarification_question(
        ["employee_id", "application_id"]
    )

    assert question == "What is your employee ID? What is your application ID?"


@pytest.mark.parametrize(
    ("role", "query", "intent", "entity_name", "entity_value", "result_key", "result_value"),
    [
        (
            "HR",
            "Check my leave balance for employee ID EMP-42.",
            "check_leave_balance",
            "employee_id",
            "EMP-42",
            "leave_balance_days",
            12,
        ),
        (
            "IT Support",
            "My system is unable to connect to the office network.",
            "raise_it_support_ticket",
            "issue_description",
            "My system is unable to connect to the office network.",
            "ticket_id",
            "IT-1001",
        ),
        (
            "Admissions",
            "Check my application status for application ID APP-42.",
            "check_application_status",
            "application_id",
            "APP-42",
            "application_status",
            "under_review",
        ),
    ],
)
def test_interpretation_dispatches_to_existing_workflow_agent(
    role: str,
    query: str,
    intent: str,
    entity_name: str,
    entity_value: str,
    result_key: str,
    result_value: Any,
) -> None:
    workflow_request = RuleBasedAssistantNLU().interpret(role, query)

    result = WorkflowAgent().execute(**workflow_request)

    assert result["status"] == "success"
    assert result["intent"] == intent
    assert result["data"][entity_name] == entity_value
    assert result["data"][result_key] == result_value
    assert result["data"]["source"] == "mock"


def test_missing_entity_flows_to_agent_and_returns_clarification() -> None:
    workflow_request = RuleBasedAssistantNLU().interpret(
        "Admissions",
        "Please check my application status.",
    )
    result = WorkflowAgent().execute(**workflow_request)

    assert result["status"] == "clarification_required"
    assert result["data"]["missing_entities"] == ["application_id"]
    assert RuleBasedAssistantNLU.clarification_question(
        result["data"]["missing_entities"]
    ) == "What is your application ID?"
