"""Role-specific workflow definitions and registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.integrations.mock_integrations import MockIntegrations

WorkflowHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class WorkflowDefinition:
    """Describe the entities and integration handler needed by a workflow."""

    role: str
    intent: str
    required_entities: tuple[str, ...]
    execute: WorkflowHandler


class WorkflowRegistry:
    """Store workflows by their normalized role and recognized intent."""

    def __init__(self) -> None:
        self._workflows: dict[tuple[str, str], WorkflowDefinition] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        """Register a workflow, replacing any existing definition for its key."""
        key = (workflow.role.casefold(), workflow.intent.casefold())
        self._workflows[key] = workflow

    def get(self, role: str, intent: str) -> WorkflowDefinition | None:
        """Return the matching workflow, if one has been registered."""
        return self._workflows.get((role.casefold(), intent.casefold()))


def create_default_workflow_registry(
    integrations: MockIntegrations | None = None,
) -> WorkflowRegistry:
    """Build the HR, IT support, and admissions demonstration workflows."""
    mock_integrations = integrations if integrations is not None else MockIntegrations()
    registry = WorkflowRegistry()

    registry.register(
        WorkflowDefinition(
            role="HR",
            intent="check_leave_balance",
            required_entities=("employee_id",),
            execute=mock_integrations.check_leave_balance,
        )
    )
    registry.register(
        WorkflowDefinition(
            role="IT Support",
            intent="raise_it_support_ticket",
            required_entities=("issue_description",),
            execute=mock_integrations.raise_it_support_ticket,
        )
    )
    registry.register(
        WorkflowDefinition(
            role="Admissions",
            intent="check_application_status",
            required_entities=("application_id",),
            execute=mock_integrations.check_application_status,
        )
    )
    return registry
