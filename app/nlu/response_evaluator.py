"""Explainable deterministic checks for response relevance and consistency."""

from __future__ import annotations

import re
from typing import Any

from app.nlu.role_prompts import canonical_role


_OTHER_ROLES = {
    "HR": ("IT Support", "Admissions"),
    "IT Support": ("HR", "Admissions"),
    "Admissions": ("HR", "IT Support"),
}

_LEAVE_APPROVAL_CLAIM = re.compile(
    r"\b(?:leave|time off)\b[^.!?]{0,80}"
    r"\b(?:approv\w*|grant\w*|authori[sz]\w*|deni\w*|reject\w*)\b"
    r"|\b(?:approv\w*|grant\w*|authori[sz]\w*|deni\w*|reject\w*)\b"
    r"[^.!?]{0,80}\b(?:leave|time off)\b",
    re.IGNORECASE,
)
_GENERAL_RECORD_CLAIM = re.compile(
    r"\b(?:your|employee)\s+(?:leave balance|application status|application|ticket)"
    r"\s+(?:is|was|has|shows|stands)\b|\b(?:created|opened)\s+(?:your\s+)?"
    r"(?:support\s+)?ticket\b",
    re.IGNORECASE,
)
_GENERAL_POLICY_CLAIM = re.compile(
    r"\b(?:your|our|the organization(?:'s|’s))\b[^.!?]{0,40}\b"
    r"(?:policy|policies|records?|guidelines?)\s+"
    r"(?:is|are|allows?|requires?|states?|provides?|shows?)\b",
    re.IGNORECASE,
)


class ResponseEvaluator:
    """Evaluate response checks; score is the fraction passed on a 0-to-1 scale."""

    def evaluate(
        self,
        selected_role: object,
        intent: str | None,
        workflow_result: dict[str, Any],
        response: object,
    ) -> dict[str, Any]:
        role = canonical_role(selected_role)
        text = response if isinstance(response, str) else ""
        lowered = text.casefold()
        status = workflow_result.get("status")
        checks: dict[str, bool] = {
            "non_empty": bool(text.strip()),
            "role_consistent": self._role_consistent(
                role, workflow_result, lowered
            ),
            "outcome_consistent": self._outcome_consistent(status, lowered),
            "intent_relevant": self._intent_relevant(
                role, intent, workflow_result, lowered
            ),
            "workflow_facts_supported": self._facts_supported(
                intent, workflow_result, text
            ),
        }
        score = sum(checks.values()) / len(checks)
        relevant = all(checks.values())
        return {
            "relevant": relevant,
            "score": round(score, 2),
            "reason": (
                "Response passed all deterministic relevance checks."
                if relevant
                else "Response failed one or more deterministic relevance checks."
            ),
            "checks": checks,
            "method": "deterministic_rule_checks",
        }

    @staticmethod
    def _role_consistent(
        role: str,
        result: dict[str, Any],
        lowered_response: str,
    ) -> bool:
        response_without_user_data = lowered_response
        data = result.get("data") or {}
        for value in data.values():
            if isinstance(value, str) and value:
                response_without_user_data = re.sub(
                    re.escape(value.casefold()),
                    "",
                    response_without_user_data,
                )
        return not any(
            other.casefold() in response_without_user_data
            for other in _OTHER_ROLES[role]
        )

    @staticmethod
    def _outcome_consistent(status: object, text: str) -> bool:
        if status == "success":
            return (
                any(word in text for word in (" is ", " created ", "completed"))
                and not any(
                    phrase in text
                    for phrase in ("couldn’t complete", "could not complete", "failed")
                )
            )
        if status == "clarification_required":
            return "?" in text and "completed successfully" not in text
        if status == "escalation_required":
            return (
                any(word in text for word in ("review", "escalat", "assistance"))
                and "completed successfully" not in text
            )
        if status in {"integration_error", "execution_error"}:
            return (
                any(word in text for word in ("couldn’t", "could not", "failed", "unable"))
                and "completed successfully" not in text
                and " created " not in text
            )
        if status == "invalid_input":
            return (
                any(word in text for word in ("couldn’t", "could not", "unable"))
                and "completed successfully" not in text
                and " created " not in text
            )
        if status == "unknown_intent":
            return (
                any(word in text for word in ("couldn’t identify", "unsupported", "rephrase"))
                and "completed successfully" not in text
            )
        if status == "general_question":
            has_general_caveat = any(
                phrase in text
                for phrase in (
                    "general information",
                    "general guidance",
                    "do not have access",
                    "don't have access",
                    "don’t have access",
                    "not authoritative",
                )
            )
            return (
                has_general_caveat
                and not any(
                    phrase in text
                    for phrase in ("completed successfully", "workflow succeeded")
                )
                and _GENERAL_RECORD_CLAIM.search(text) is None
                and _GENERAL_POLICY_CLAIM.search(text) is None
            )
        return False

    @staticmethod
    def _intent_relevant(
        role: str,
        intent: str | None,
        result: dict[str, Any],
        text: str,
    ) -> bool:
        status = result.get("status")
        if status == "general_question":
            return True
        if status != "success":
            if status == "clarification_required":
                missing = (result.get("data") or {}).get("missing_entities", [])
                if not isinstance(missing, list):
                    return False
                if not missing:
                    return "?" in text
                entity_terms = {
                    "employee_id": "employee id",
                    "application_id": "application id",
                    "issue_description": "issue",
                }
                required_terms = [
                    entity_terms.get(
                        str(entity),
                        str(entity).replace("_", " ").casefold(),
                    )
                    for entity in missing
                ]
                return all(term in text for term in required_terms)
            return True

        expected_terms = {
            ("HR", "check_leave_balance"): ("leave",),
            ("IT Support", "raise_it_support_ticket"): ("ticket",),
            ("Admissions", "check_application_status"): ("application",),
        }.get((role, intent))
        return bool(expected_terms and any(term in text for term in expected_terms))

    @staticmethod
    def _facts_supported(
        intent: str | None,
        result: dict[str, Any],
        response: str,
    ) -> bool:
        if result.get("status") != "success":
            return True

        data = result.get("data") or {}
        trusted_values = {str(value) for value in data.values()}
        lowered_response = response.casefold()
        numbers = re.findall(r"\b\d+\b", response)
        supported_numbers = all(
            number in " ".join(trusted_values)
            or any(number in value for value in trusted_values)
            for number in numbers
        )
        required_result_values = [
            str(value).casefold()
            for key, value in data.items()
            if key != "source" and value is not None
        ]
        supported_result = all(
            value in lowered_response for value in required_result_values
        )
        claims_supported = not (
            intent == "check_leave_balance"
            and _LEAVE_APPROVAL_CLAIM.search(lowered_response)
        )
        if data.get("source") == "mock":
            claims_supported = claims_supported and any(
                marker in lowered_response
                for marker in ("demonstration data", "sample data")
            )
        return supported_numbers and supported_result and claims_supported
