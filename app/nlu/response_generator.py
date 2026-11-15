"""Response generation with an explicit deterministic offline provider."""

from __future__ import annotations

from typing import Any, Protocol

from app.llm.openai_client import OpenAIClient
from app.nlu.role_prompts import build_response_prompt, canonical_role


class ResponseProviderUnavailable(RuntimeError):
    """Raised when an explicitly selected response provider cannot be used."""


class ResponseProvider(Protocol):
    """Contract for providers that generate a response from role prompts."""

    name: str

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> str: ...


class DeterministicResponseProvider:
    """Render safe responses from structured data without calling an LLM."""

    name = "deterministic"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> str:
        del system_prompt, user_prompt
        role = canonical_role(context["role"])
        intent = context.get("intent")
        result = context["workflow_result"]
        status = result.get("status")

        if status == "clarification_required":
            question = context.get("clarification_question")
            return question or "Please provide the missing information."
        if status == "escalation_required":
            return (
                "I’m not confident enough to proceed, so this request needs "
                "human review."
            )
        if status in {"integration_error", "execution_error"}:
            return (
                "I couldn’t complete the requested workflow. The request "
                "needs assistance."
            )
        if status == "invalid_input":
            return "I couldn’t safely process that request. Please check the provided information."
        if status == "unknown_intent":
            return (
                f"I couldn’t identify a supported request for the {role} "
                "assistant. Please rephrase your request."
            )
        if status == "general_question":
            return (
                f"I can share general {role} information, but I don’t have "
                "access to your organization’s specific policies or records. "
                "Please check with the appropriate department for authoritative "
                "guidance."
            )
        if status != "success":
            return "I couldn’t process this request safely."

        data = result.get("data") or {}
        if role == "HR" and intent == "check_leave_balance":
            response = (
                f"Your leave balance for employee {data['employee_id']} is "
                f"{data['leave_balance_days']} days."
            )
        elif role == "IT Support" and intent == "raise_it_support_ticket":
            response = (
                f"I created support ticket {data['ticket_id']} with status "
                f"{data['status']} for: {data['issue_description']}"
            )
        elif role == "Admissions" and intent == "check_application_status":
            response = (
                f"Application {data['application_id']} is "
                f"{data['application_status']}."
            )
        else:
            return "The workflow completed, but I can’t summarize this result safely."
        if data.get("source") == "mock":
            response += " This is demonstration data from a mock integration."
        return response


class OpenAIResponseProvider:
    """Generate natural-language responses using the server-side OpenAI client."""

    name = "openai"

    def __init__(self, client: OpenAIClient) -> None:
        self.client = client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> str:
        del context
        try:
            return self.client.generate_response(system_prompt, user_prompt)
        except Exception as error:
            raise ResponseProviderUnavailable(
                "The configured response provider is unavailable."
            ) from error


class ResponseGenerator:
    """Generate a role-aware response using an explicitly selected provider."""

    def __init__(self, provider: ResponseProvider | None = None) -> None:
        self.provider = (
            provider if provider is not None else DeterministicResponseProvider()
        )

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def generate(
        self,
        selected_role: object,
        query: str,
        intent: str | None,
        workflow_result: dict[str, Any],
        clarification_question: str | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> str:
        """Create a response without exposing provider exceptions to callers."""
        role = canonical_role(selected_role)
        context: dict[str, Any] = {
            "role": role,
            "intent": intent,
            "workflow_result": _safe_workflow_context(
                role,
                intent,
                workflow_result,
            ),
            "clarification_question": clarification_question,
            "conversation_context": _safe_conversation_context(
                conversation_context
            ),
        }
        system_prompt, user_prompt = build_response_prompt(role, query, context)
        try:
            response = self.provider.generate(system_prompt, user_prompt, context)
        except ResponseProviderUnavailable as error:
            raise ResponseProviderUnavailable(
                "The configured response provider is unavailable."
            ) from error
        except Exception as error:
            raise ResponseProviderUnavailable(
                "The configured response provider is unavailable."
            ) from error
        if not isinstance(response, str) or not response.strip():
            raise ResponseProviderUnavailable(
                "The configured response provider returned no usable response."
            )
        return response.strip()


def _safe_workflow_context(
    role: str,
    intent: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        data = {}
    if result.get("status") == "success":
        fields = {
            ("HR", "check_leave_balance"): (
                "employee_id",
                "leave_balance_days",
                "source",
            ),
            ("IT Support", "raise_it_support_ticket"): (
                "ticket_id",
                "issue_description",
                "status",
                "source",
            ),
            ("Admissions", "check_application_status"): (
                "application_id",
                "application_status",
                "source",
            ),
        }.get((role, intent), ())
    else:
        fields = ("missing_entities", "invalid_entities", "failure_category")
    return {
        "status": result.get("status"),
        "role": role,
        "intent": intent,
        "message": result.get("message"),
        "data": {key: data[key] for key in fields if key in data},
    }


def _safe_conversation_context(
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    messages = context.get("recent_messages")
    if not isinstance(messages, list):
        messages = []
    recent_messages = [
        {"sender": message["sender"], "body": message["body"][-500:]}
        for message in messages[-4:]
        if isinstance(message, dict)
        and message.get("sender") in {"user", "assistant", "agent"}
        and isinstance(message.get("body"), str)
    ]
    pending = context.get("pending_clarification")
    safe_pending = None
    if isinstance(pending, dict):
        pending_intent = pending.get("intent")
        pending_entities = pending.get("entities")
        safe_pending = {
            "intent": pending_intent if isinstance(pending_intent, str) else None,
            "entities": (
                {
                    key: value[:1000]
                    for key, value in pending_entities.items()
                    if key
                    in {"employee_id", "application_id", "issue_description"}
                    and isinstance(value, str)
                }
                if isinstance(pending_entities, dict)
                else {}
            ),
        }
    return {
        "recent_messages": recent_messages,
        "pending_clarification": safe_pending,
    }
