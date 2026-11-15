"""Tests for the optional OpenAI provider and hybrid assistant route."""

import json
import re
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient

import run
from app.llm.openai_client import OpenAIClient, OpenAIServiceUnavailable
from app.nlu.response_generator import (
    ResponseGenerator,
    ResponseProviderUnavailable,
)


class StubResponses:
    def __init__(self, output_text: str | None = None, error: Exception | None = None):
        self.output_text = output_text
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_text=self.output_text)


class FakeLLM:
    is_enabled = True

    def __init__(self, suggestion: object | Exception):
        self.suggestion = suggestion
        self.contexts: list[dict[str, Any]] = []

    def interpret_request(
        self,
        role: str,
        query: str,
        conversation_context: dict[str, Any],
    ) -> object:
        del role, query
        self.contexts.append(conversation_context)
        if isinstance(self.suggestion, Exception):
            raise self.suggestion
        return self.suggestion


class FakeResponseProvider:
    name = "openai"

    def __init__(self, response: str | Any):
        self.response = response
        self.contexts: list[dict[str, Any]] = []

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> str:
        del system_prompt, user_prompt
        self.contexts.append(context)
        if callable(self.response):
            return self.response(context)
        return self.response


def _client_factory(responses: StubResponses, calls: list[dict[str, Any]]):
    def create_client(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(responses=responses)

    return create_client


def test_openai_client_is_disabled_without_api_key() -> None:
    client = OpenAIClient(api_key=None, model="configured-model")

    assert client.is_enabled is False
    with pytest.raises(OpenAIServiceUnavailable) as error:
        client.interpret_request("HR", "query", {})
    assert error.value.category == "not_configured"


def test_openai_client_lazily_initializes_once_and_uses_responses_api() -> None:
    responses = StubResponses(
        '{"intent":"check_leave_balance","entities":{"employee_id":"EMP-42"},'
        '"confidence":0.95}'
    )
    initializations: list[dict[str, Any]] = []
    client = OpenAIClient(
        api_key="test-key",
        model="test-model",
        enabled=True,
        timeout_seconds=7,
        client_factory=_client_factory(responses, initializations),
    )

    result = client.interpret_request("HR", "Check leave EMP-42", {})
    client.interpret_request("HR", "Check leave EMP-42", {})

    assert result["intent"] == "check_leave_balance"
    assert len(initializations) == 1
    assert initializations[0]["timeout"] == 7
    assert initializations[0]["max_retries"] == 0
    assert responses.calls[0]["model"] == "test-model"
    assert responses.calls[0]["max_output_tokens"] == 300
    assert responses.calls[0]["text"] == {"format": {"type": "json_object"}}
    assert "test-key" not in repr(responses.calls[0])


def test_openai_client_generates_a_text_response() -> None:
    responses = StubResponses("A grounded assistant response.")
    client = OpenAIClient(
        api_key="test-key",
        model="test-model",
        enabled=True,
        client_factory=_client_factory(responses, []),
    )

    answer = client.generate_response("Role instructions", "Verified result")

    assert answer == "A grounded assistant response."
    assert responses.calls[0]["instructions"] == "Role instructions"
    assert responses.calls[0]["input"] == "Verified result"
    assert responses.calls[0]["max_output_tokens"] == 500
    assert "text" not in responses.calls[0]


def test_openai_client_redacts_credential_like_user_text() -> None:
    responses = StubResponses(
        '{"intent":"unknown","entities":{},"confidence":0.2}'
    )
    client = OpenAIClient(
        api_key="test-key",
        model="test-model",
        enabled=True,
        client_factory=_client_factory(responses, []),
    )

    client.interpret_request(
        "HR",
        "My password is private-value. What does leave balance mean?",
        {},
    )

    assert "private-value" not in responses.calls[0]["input"]
    assert "[redacted]" in responses.calls[0]["input"]


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (type("APITimeoutError", (Exception,), {})("private timeout"), "timeout"),
        (type("RateLimitError", (Exception,), {})("private limit"), "rate_limit"),
        (type("AuthenticationError", (Exception,), {})("private key"), "invalid_credentials"),
        (type("APIConnectionError", (Exception,), {})("private connection"), "connection"),
        (type("APIStatusError", (Exception,), {})("private API detail"), "api_error"),
    ],
)
def test_openai_client_sanitizes_api_failures(
    exception: Exception,
    category: str,
) -> None:
    client = OpenAIClient(
        api_key="test-key",
        model="test-model",
        enabled=True,
        client_factory=_client_factory(StubResponses(error=exception), []),
    )

    with pytest.raises(OpenAIServiceUnavailable) as error:
        client.generate_response("system", "prompt")

    assert error.value.category == category
    assert str(exception) not in str(error.value)


def test_openai_client_rejects_malformed_model_output() -> None:
    client = OpenAIClient(
        api_key="test-key",
        model="test-model",
        enabled=True,
        client_factory=_client_factory(StubResponses("not-json"), []),
    )

    with pytest.raises(OpenAIServiceUnavailable) as error:
        client.interpret_request("HR", "query", {})

    assert error.value.category == "malformed_output"


@pytest.fixture
def client(tmp_path) -> FlaskClient:
    run.app.config.update(
        TESTING=True,
        SECRET_KEY="openai-integration-test-secret",
        SESSION_COOKIE_SECURE=False,
        AUTH_DATABASE=str(tmp_path / "openai-integration.sqlite3"),
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
    registration = test_client.post(
        "/api/auth/register",
        json={"username": "llm-user", "password": "test-user-password"},
    )
    assert registration.status_code == 201
    login = test_client.post(
        "/api/auth/login",
        json={"username": "llm-user", "password": "test-user-password"},
    )
    assert login.status_code == 200
    test_client.environ_base["HTTP_X_CSRF_TOKEN"] = login.get_json()["csrf_token"]
    return test_client


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    suggestion: object | Exception,
    response: str | Any,
) -> tuple[FakeLLM, FakeResponseProvider]:
    llm = FakeLLM(suggestion)
    provider = FakeResponseProvider(response)
    monkeypatch.setattr(run, "openai_client", llm)
    monkeypatch.setattr(run, "response_generator", ResponseGenerator(provider))
    return llm, provider


def _send(
    client: FlaskClient,
    role: str,
    query: str,
    conversation_id: str | None = None,
):
    payload: dict[str, Any] = {"selected_role": role, "query": query}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return client.post("/api/assistant/execute", json=payload)


@pytest.mark.parametrize(
    ("role", "query", "suggestion", "expected_intent", "expected_data"),
    [
        (
            "HR",
            "How many leave days remain for EMP-42?",
            {
                "intent": "check_leave_balance",
                "entities": {"employee_id": "EMP-42"},
                "confidence": 0.95,
            },
            "check_leave_balance",
            {"employee_id": "EMP-42", "leave_balance_days": 12, "source": "mock"},
        ),
        (
            "IT Support",
            "Please help me report that email is unavailable.",
            {
                "intent": "raise_it_support_ticket",
                "entities": {
                    "issue_description": "Please help me report that email is unavailable."
                },
                "confidence": 0.95,
            },
            "raise_it_support_ticket",
            {
                "ticket_id": "IT-1001",
                "issue_description": "Please help me report that email is unavailable.",
                "status": "open",
                "source": "mock",
            },
        ),
        (
            "Admissions",
            "Can you tell me where APP-42 is in the process?",
            {
                "intent": "check_application_status",
                "entities": {"application_id": "APP-42"},
                "confidence": 0.95,
            },
            "check_application_status",
            {
                "application_id": "APP-42",
                "application_status": "under_review",
                "source": "mock",
            },
        ),
    ],
)
def test_llm_suggestions_preserve_registered_workflow_results(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    query: str,
    suggestion: dict[str, Any],
    expected_intent: str,
    expected_data: dict[str, Any],
) -> None:
    def grounded_response(context: dict[str, Any]) -> str:
        data = context["workflow_result"]["data"]
        if "leave_balance_days" in data:
            return (
                f"Your leave balance for employee {data['employee_id']} is "
                f"{data['leave_balance_days']} days. This is demonstration data."
            )
        if "ticket_id" in data:
            return (
                f"I created support ticket {data['ticket_id']} with status "
                f"{data['status']} for: {data['issue_description']}. "
                "This is demonstration data."
            )
        return (
            f"Application {data['application_id']} is "
            f"{data['application_status']}. This is demonstration data."
        )

    _install_fake_llm(monkeypatch, suggestion, grounded_response)

    response = _send(client, role, query)
    result = response.get_json()

    assert response.status_code == 200
    assert result["intent"] == expected_intent
    assert result["status"] == "success"
    assert result["data"] == expected_data
    assert result["llm_mode"] == "openai"
    assert result["response_source"] == "openai"
    assert result["response_evaluation"]["relevant"] is True
    assert "demonstration data" in result["response"].casefold()


def test_general_role_question_uses_llm_without_running_a_workflow(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(
        monkeypatch,
        {"intent": "general", "entities": {}, "confidence": 0.94},
        "In general, HR teams can explain common leave terminology. "
        "This is general information, not your organization’s policy.",
    )
    execute_calls = 0
    original_execute = run.workflow_agent.execute

    def track_execute(**kwargs: Any) -> dict[str, Any]:
        nonlocal execute_calls
        execute_calls += 1
        return original_execute(**kwargs)

    monkeypatch.setattr(run.workflow_agent, "execute", track_execute)

    response = _send(client, "HR", "What does annual leave mean?")
    result = response.get_json()

    assert result["status"] == "general_question"
    assert result["intent"] == "general"
    assert result["response_source"] == "openai"
    assert execute_calls == 0


def test_response_evaluator_replaces_a_fabricated_workflow_fact(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(
        monkeypatch,
        {
            "intent": "check_leave_balance",
            "entities": {"employee_id": "EMP-42"},
            "confidence": 0.95,
        },
        "Your leave balance for employee EMP-42 is 999 days.",
    )

    result = _send(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    ).get_json()

    assert result["status"] == "success"
    assert result["response_source"] == "deterministic_fallback"
    assert "12 days" in result["response"]
    assert "999" not in result["response"]
    assert result["response_evaluation"]["relevant"] is True


def test_unknown_or_wrong_role_intent_never_executes(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(
        monkeypatch,
        {
            "intent": "raise_it_support_ticket",
            "entities": {},
            "confidence": 0.99,
        },
        "I created a ticket.",
    )
    execute_calls = 0
    original_execute = run.workflow_agent.execute

    def track_execute(**kwargs: Any) -> dict[str, Any]:
        nonlocal execute_calls
        execute_calls += 1
        return original_execute(**kwargs)

    monkeypatch.setattr(run.workflow_agent, "execute", track_execute)

    response = _send(client, "HR", "I need help with something.")

    assert response.get_json()["status"] == "unknown_intent"
    assert execute_calls == 0


def test_model_uncertainty_requests_clarification_without_execution(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(
        monkeypatch,
        {
            "intent": "check_application_status",
            "entities": {},
            "confidence": 0.42,
        },
        "Could you clarify what you need?",
    )
    execute_calls = 0
    original_execute = run.workflow_agent.execute

    def track_execute(**kwargs: Any) -> dict[str, Any]:
        nonlocal execute_calls
        execute_calls += 1
        return original_execute(**kwargs)

    monkeypatch.setattr(run.workflow_agent, "execute", track_execute)

    result = _send(client, "Admissions", "I have a question.").get_json()

    assert result["status"] == "clarification_required"
    assert "?" in result["response"]
    assert execute_calls == 0
    stored = run.conversation_store().get_conversation(result["conversation_id"])
    assert stored["pending_intent"] is None


def test_llm_failure_and_malformed_suggestion_fall_back_to_rule_nlu(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for suggestion in (
        OpenAIServiceUnavailable("timeout"),
        {"intent": "check_leave_balance", "entities": "not-an-object", "confidence": 0.9},
    ):
        _install_fake_llm(
            monkeypatch,
            suggestion,
            "This provider should not be used.",
        )
        result = _send(
            client,
            "HR",
            "Check leave balance for employee ID EMP-42.",
        ).get_json()
        assert result["status"] == "success"
        assert result["intent"] == "check_leave_balance"
        assert result["llm_mode"] == "fallback"
        assert result["response_source"] == "deterministic_fallback"


def test_openai_response_failure_uses_verified_deterministic_fallback(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_context: dict[str, Any]) -> str:
        raise ResponseProviderUnavailable("private provider failure")

    _, provider = _install_fake_llm(
        monkeypatch,
        {
            "intent": "check_leave_balance",
            "entities": {"employee_id": "EMP-42"},
            "confidence": 0.95,
        },
        unavailable,
    )
    assert provider.name == "openai"

    result = _send(
        client,
        "HR",
        "Check leave balance for employee ID EMP-42.",
    ).get_json()

    assert result["status"] == "success"
    assert result["llm_mode"] == "fallback"
    assert result["response_source"] == "deterministic_fallback"
    assert result["response_generation_status"] == "fallback"
    assert "private provider failure" not in result["response"]
    assert "12 days" in result["response"]


def test_clarification_context_and_messages_are_not_duplicated(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm, _ = _install_fake_llm(
        monkeypatch,
        {
            "intent": "check_application_status",
            "entities": {},
            "confidence": 0.95,
        },
        "What is your application ID?",
    )
    first = _send(client, "Admissions", "Check my application status.")
    conversation_id = first.get_json()["conversation_id"]
    assert first.get_json()["status"] == "clarification_required"

    llm.suggestion = {
        "intent": "unknown",
        "entities": {},
        "confidence": 0.8,
    }
    second = _send(client, "Admissions", "APP-42", conversation_id)
    detail = client.get(f"/api/conversations/{conversation_id}").get_json()

    assert second.get_json()["status"] == "success"
    assert llm.contexts[-1]["pending_clarification"]["intent"] == (
        "check_application_status"
    )
    assert llm.contexts[-1]["recent_messages"][-1]["body"] == (
        "What is your application ID?"
    )
    assert len(detail["messages"]) == 4
    assert [message["sender"] for message in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_unowned_conversation_is_rejected_before_llm_context_is_loaded(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm, _ = _install_fake_llm(
        monkeypatch,
        {"intent": "general", "entities": {}, "confidence": 0.9},
        "General answer.",
    )

    response = _send(client, "HR", "Check my history.", "a" * 32)

    assert response.status_code == 404
    assert llm.contexts == []
