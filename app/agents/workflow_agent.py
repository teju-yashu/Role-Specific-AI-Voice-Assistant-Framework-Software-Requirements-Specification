"""Validate recognized intents and dispatch them to role-specific workflows."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.integrations.mock_integrations import IntegrationError
from app.workflows.registry import WorkflowRegistry, create_default_workflow_registry

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
SUPPORTED_ROLES = ("HR", "IT Support", "Admissions")


class WorkflowAgent:
    """Validate workflow requests and return JSON-compatible execution results.

    The confidence threshold can be adjusted when constructing an agent, which
    allows callers to apply application-specific escalation policies.
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        workflow_registry: WorkflowRegistry | None = None,
    ) -> None:
        if (
            isinstance(confidence_threshold, bool)
            or not isinstance(confidence_threshold, (int, float))
            or not 0 <= confidence_threshold <= 1
        ):
            raise ValueError("confidence_threshold must be a finite number from 0 to 1.")

        self.confidence_threshold = float(confidence_threshold)
        self.workflow_registry = (
            workflow_registry
            if workflow_registry is not None
            else create_default_workflow_registry()
        )

    def execute(
        self,
        selected_role: object,
        intent: object,
        entities: object,
        confidence: object,
    ) -> dict[str, Any]:
        """Validate a recognized request and execute its registered workflow."""
        role = self._normalize_role(selected_role)
        normalized_intent = intent.strip().lower() if isinstance(intent, str) else None

        if role is None:
            return self._result(
                "invalid_role",
                selected_role if isinstance(selected_role, str) else None,
                normalized_intent,
                "The selected role is not supported.",
                data={"supported_roles": list(SUPPORTED_ROLES)},
            )

        if not isinstance(normalized_intent, str) or not normalized_intent:
            return self._result(
                "unknown_intent",
                role,
                normalized_intent,
                "The intent is missing or invalid.",
            )

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            return self._result(
                "invalid_input",
                role,
                normalized_intent,
                "Confidence must be a finite number from 0 to 1.",
            )

        if confidence < self.confidence_threshold:
            return self._result(
                "escalation_required",
                role,
                normalized_intent,
                "Intent confidence is below the configured threshold.",
                escalation={
                    "required": True,
                    "reason": "low_confidence",
                    "confidence": confidence,
                    "threshold": self.confidence_threshold,
                },
            )

        workflow = self.workflow_registry.get(role, normalized_intent)
        if workflow is None:
            return self._result(
                "unknown_intent",
                role,
                normalized_intent,
                "No workflow is registered for this role and intent.",
            )

        if not isinstance(entities, dict):
            return self._result(
                "invalid_input",
                role,
                normalized_intent,
                "Entities must be provided as an object.",
            )

        missing_entities = []
        invalid_entities = []
        for entity in workflow.required_entities:
            if entity not in entities or entities[entity] is None:
                missing_entities.append(entity)
            elif not isinstance(entities[entity], str):
                invalid_entities.append(entity)
            elif not entities[entity].strip():
                missing_entities.append(entity)

        if invalid_entities:
            return self._result(
                "invalid_input",
                role,
                normalized_intent,
                "Required entities must be provided as non-empty strings.",
                data={"invalid_entities": invalid_entities},
            )

        if missing_entities:
            return self._result(
                "clarification_required",
                role,
                normalized_intent,
                "Additional information is required before this workflow can run.",
                data={"missing_entities": missing_entities},
            )

        try:
            data = workflow.execute(entities)
        except IntegrationError as error:
            return self._failure_result(
                "integration_error",
                role,
                normalized_intent,
                "integration_failure",
                "The required integration could not complete the request.",
                error,
            )
        except Exception as error:
            return self._failure_result(
                "execution_error",
                role,
                normalized_intent,
                "workflow_execution_failure",
                "The workflow could not be completed.",
                error,
            )

        return self._result(
            "success",
            role,
            normalized_intent,
            "The workflow completed successfully.",
            data=data,
        )

    @staticmethod
    def _failure_result(
        status: str,
        role: str,
        intent: str,
        reason: str,
        message: str,
        error: Exception,
    ) -> dict[str, Any]:
        """Log failure details and return a safe, escalation-required result."""
        failure_record = {
            "role": role,
            "intent": intent,
            "failure_category": status,
            "error_type": type(error).__name__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        LOGGER.error("%s", json.dumps(failure_record, sort_keys=True))

        return WorkflowAgent._result(
            status,
            role,
            intent,
            message,
            data={"failure_category": status},
            escalation={
                "required": True,
                "reason": reason,
                "failure_category": status,
            },
        )

    @staticmethod
    def _normalize_role(role: object) -> str | None:
        if not isinstance(role, str):
            return None

        normalized = " ".join(role.split()).casefold()
        return next((supported for supported in SUPPORTED_ROLES if supported.casefold() == normalized), None)

    @staticmethod
    def _result(
        status: str,
        role: str | None,
        intent: str | None,
        message: str,
        data: dict[str, Any] | None = None,
        escalation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a result with the same keys for every outcome."""
        return {
            "status": status,
            "role": role,
            "intent": intent,
            "message": message,
            "data": data,
            "escalation": escalation or {"required": False},
        }
