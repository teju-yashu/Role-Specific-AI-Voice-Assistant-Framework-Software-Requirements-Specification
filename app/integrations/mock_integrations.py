"""Deterministic mock integrations for demonstrating registered workflows."""

from __future__ import annotations

from typing import Any


class IntegrationError(Exception):
    """Raised when a mock integration cannot process a workflow request."""


class MockIntegrations:
    """Return predictable demonstration data without calling external services."""

    def check_leave_balance(self, entities: dict[str, Any]) -> dict[str, Any]:
        """Return a sample leave balance for the requested employee."""
        employee_id = entities["employee_id"]
        return {
            "employee_id": employee_id,
            "leave_balance_days": 12,
            "source": "mock",
        }

    def raise_it_support_ticket(self, entities: dict[str, Any]) -> dict[str, Any]:
        """Return a sample IT ticket for the supplied issue description."""
        return {
            "ticket_id": "IT-1001",
            "issue_description": entities["issue_description"],
            "status": "open",
            "source": "mock",
        }

    def check_application_status(self, entities: dict[str, Any]) -> dict[str, Any]:
        """Return a sample admissions application status."""
        application_id = entities["application_id"]
        return {
            "application_id": application_id,
            "application_status": "under_review",
            "source": "mock",
        }
