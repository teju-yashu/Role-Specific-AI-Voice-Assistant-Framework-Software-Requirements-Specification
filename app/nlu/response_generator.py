"""Response generation with an explicit deterministic offline provider."""

from __future__ import annotations

from typing import Any, Protocol

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
        if status == "unknown_intent":
            return (
                f"I couldn’t identify a supported request for the {role} "
                "assistant. Please rephrase your request."
            )
        if status != "success":
            return "I couldn’t process this request safely."

        data = result.get("data") or {}
        if role == "HR" and intent == "check_leave_balance":
            return (
                f"Your leave balance for employee {data['employee_id']} is "
                f"{data['leave_balance_days']} days."
            )
        if role == "IT Support" and intent == "raise_it_support_ticket":
            return (
                f"I created support ticket {data['ticket_id']} with status "
                f"{data['status']} for: {data['issue_description']}"
            )
        if role == "Admissions" and intent == "check_application_status":
            return (
                f"Application {data['application_id']} is "
                f"{data['application_status']}."
            )
        return "The workflow completed, but I can’t summarize this result safely."


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
    ) -> str:
        """Create a response without exposing provider exceptions to callers."""
        role = canonical_role(selected_role)
        context: dict[str, Any] = {
            "role": role,
            "intent": intent,
            "workflow_result": workflow_result,
            "clarification_question": clarification_question,
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
