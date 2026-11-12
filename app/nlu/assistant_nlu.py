"""Deterministic, rule-based intent recognition and entity extraction."""

from __future__ import annotations

import re
from typing import Any


class RuleBasedAssistantNLU:
    """Recognize the project's supported workflows without an external model."""

    SUPPORTED_ROLES = {
        "hr": "HR",
        "it support": "IT Support",
        "admissions": "Admissions",
    }

    _INTENT_RULES = {
        "HR": {
            "intent": "check_leave_balance",
            "explicit": (
                "leave balance",
                "remaining leave",
                "available leave",
                "leave days",
                "check leave",
            ),
            "contextual": ("how much leave", "how many days off", "leave left"),
        },
        "IT Support": {
            "intent": "raise_it_support_ticket",
            "explicit": (
                "raise a ticket",
                "create a ticket",
                "open a ticket",
                "support ticket",
                "report an issue",
            ),
            "contextual": (
                "cannot connect",
                "can't connect",
                "unable to connect",
                "cannot access",
                "can't access",
            ),
            "low_confidence": (
                "not working",
                "issue with",
                "problem with",
            ),
        },
        "Admissions": {
            "intent": "check_application_status",
            "explicit": (
                "application status",
                "status of my application",
                "status of the application",
                "check my application",
                "track my application",
            ),
            "contextual": (
                "admission application",
                "application number",
                "application id",
            ),
        },
    }

    _ENTITY_PATTERNS = {
        "HR": re.compile(
            r"\b(?:employee\s+id|id)\s*(?:is|:|#)?\s*"
            r"([A-Z0-9][A-Z0-9_-]*)\b|\bemployee\s+"
            r"(EMP[- ]?[A-Z0-9]+|\d+)\b|\b(EMP[- ]?[A-Z0-9]+)\b",
            re.IGNORECASE,
        ),
        "Admissions": re.compile(
            r"\b(?:application\s+(?:id|number)|app(?:lication)?[- ]?id)"
            r"\s*(?:is|:|#)?\s*([A-Z0-9][A-Z0-9_-]*)\b"
            r"|\b(APP[- ]\d+)\b",
            re.IGNORECASE,
        ),
    }

    _CLARIFICATION_QUESTIONS = {
        "employee_id": "What is your employee ID?",
        "issue_description": "Please describe the IT issue you are experiencing.",
        "application_id": "What is your application ID?",
    }

    def interpret(self, selected_role: object, query: object) -> dict[str, Any]:
        """Return fields accepted by WorkflowAgent.execute for a user query."""
        if not isinstance(selected_role, str) or not selected_role.strip():
            raise ValueError("selected_role must be a non-empty string.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")

        role_key = " ".join(selected_role.split()).casefold()
        role = self.SUPPORTED_ROLES.get(role_key)
        if role is None:
            raise ValueError("selected_role is not supported.")

        normalized_query = " ".join(query.casefold().split())
        rules = self._INTENT_RULES[role]
        explicit_matches = [
            cue for cue in rules["explicit"] if self._contains_phrase(normalized_query, cue)
        ]
        contextual_matches = [
            cue for cue in rules["contextual"] if self._contains_phrase(normalized_query, cue)
        ]
        low_confidence_matches = [
            cue
            for cue in rules.get("low_confidence", ())
            if self._contains_phrase(normalized_query, cue)
        ]

        intent = "unknown"
        confidence = 0.0
        entities: dict[str, Any] = {}
        if explicit_matches or contextual_matches or low_confidence_matches:
            intent = rules["intent"]
            if explicit_matches:
                confidence = min(
                    0.99,
                    0.90
                    + 0.03 * (len(explicit_matches) - 1)
                    + 0.02 * len(contextual_matches),
                )
            elif contextual_matches:
                confidence = min(0.99, 0.76 + 0.02 * len(contextual_matches))
            else:
                confidence = min(0.69, 0.55 + 0.02 * (len(low_confidence_matches) - 1))
            entities = self._extract_entities(role, query)
            if role == "IT Support":
                entities["issue_description"] = query.strip()

        return {
            "selected_role": role,
            "intent": intent,
            "entities": entities,
            "confidence": round(confidence, 2),
        }

    @classmethod
    def clarification_question(cls, missing_entities: object) -> str:
        """Build a short prompt for entities reported missing by WorkflowAgent."""
        if not isinstance(missing_entities, list) or not missing_entities:
            raise ValueError("missing_entities must be a non-empty list.")
        questions = [
            cls._CLARIFICATION_QUESTIONS.get(
                entity,
                f"Please provide {entity.replace('_', ' ')}.",
            )
            for entity in missing_entities
            if isinstance(entity, str) and entity
        ]
        if not questions:
            raise ValueError("missing_entities must contain entity names.")
        return " ".join(questions)

    @staticmethod
    def _contains_phrase(query: str, phrase: str) -> bool:
        return re.search(rf"\b{re.escape(phrase)}\b", query) is not None

    def _extract_entities(self, role: str, query: str) -> dict[str, str]:
        if role == "IT Support":
            return {}

        entity_name = "employee_id" if role == "HR" else "application_id"
        match = self._ENTITY_PATTERNS[role].search(query)
        if match is None:
            return {}

        value = next((group for group in match.groups() if group is not None), None)
        return {entity_name: value.strip()} if value else {}
