"""SQLite persistence for accounts, conversations, escalation, and prototype metrics."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_ASSISTANT_ROLES = (
    ("HR", "HR"),
    ("IT Support", "IT Support"),
    ("Admissions", "Admissions"),
)
_initialized_paths: set[str] = set()
_initialization_lock = threading.Lock()


@contextmanager
def database_connection(database_path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(database_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=5)
    try:
        os.chmod(path, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


def initialize_database(database_path: str | Path) -> None:
    path_key = str(Path(database_path).resolve())
    with _initialization_lock:
        if path_key in _initialized_paths and Path(database_path).is_file():
            return
        _initialized_paths.discard(path_key)
        with database_connection(database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            user_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(users)")
            }
            if "role" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS assistant_roles (
                    role_key TEXT PRIMARY KEY NOT NULL,
                    display_name TEXT NOT NULL UNIQUE,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(username),
                    selected_role TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'escalated', 'resolved')),
                    pending_intent TEXT,
                    pending_entities TEXT,
                    pending_confidence REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id)
                        ON DELETE CASCADE,
                    sender TEXT NOT NULL CHECK (sender IN ('user', 'assistant', 'agent')),
                    body TEXT NOT NULL,
                    status TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT REFERENCES conversations(id),
                    user_id TEXT NOT NULL REFERENCES users(username),
                    selected_role TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS escalations (
                    id TEXT PRIMARY KEY NOT NULL,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'resolved')),
                    agent_username TEXT REFERENCES users(username),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TEXT,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_username TEXT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                    ON conversations(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);
                CREATE INDEX IF NOT EXISTS idx_escalations_status_created
                    ON escalations(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_workflow_events_created
                    ON workflow_events(created_at);
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO assistant_roles (role_key, display_name)
                VALUES (?, ?)
                """,
                DEFAULT_ASSISTANT_ROLES,
            )
        _initialized_paths.add(path_key)


class ConversationStore:
    """Persist user-owned conversations and their related workflow records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = database_path

    @staticmethod
    def new_conversation_id() -> str:
        return uuid.uuid4().hex

    def create_conversation(
        self,
        user_id: str,
        selected_role: str,
        first_message: str,
    ) -> str:
        conversation_id = self.new_conversation_id()
        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO conversations
                    (id, user_id, selected_role, title)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, user_id, selected_role, first_message[:80]),
            )
            self._log_activity(
                connection,
                user_id,
                "conversation_started",
                "conversation",
                conversation_id,
            )
        return conversation_id

    def persist_assistant_turn(
        self,
        conversation_id: str,
        user_id: str,
        selected_role: str,
        query: str,
        response: str,
        status: str,
        intent: str,
        outcome: str,
        is_new_conversation: bool,
        pending_intent: str | None,
        pending_entities: dict[str, Any] | None,
        pending_confidence: float | None,
        escalation_reason: str | None = None,
    ) -> dict[str, str | None]:
        """Commit a complete assistant turn and escalation as one transaction."""
        with database_connection(self.database_path) as connection:
            if is_new_conversation:
                connection.execute(
                    """
                    INSERT INTO conversations (id, user_id, selected_role, title)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conversation_id, user_id, selected_role, query[:80]),
                )
                self._log_activity(
                    connection,
                    user_id,
                    "conversation_started",
                    "conversation",
                    conversation_id,
                )
            else:
                owned = connection.execute(
                    """
                    SELECT 1 FROM conversations
                    WHERE id = ? AND user_id = ?
                    """,
                    (conversation_id, user_id),
                ).fetchone()
                if owned is None:
                    raise ValueError("Conversation is not available to this user.")

            connection.executemany(
                """
                INSERT INTO messages (conversation_id, sender, body, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (conversation_id, "user", query, None),
                    (conversation_id, "assistant", response, status),
                ),
            )
            connection.execute(
                """
                UPDATE conversations
                SET pending_intent = ?, pending_entities = ?, pending_confidence = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    status = CASE WHEN status = 'resolved' THEN 'active' ELSE status END
                WHERE id = ? AND user_id = ?
                """,
                (
                    pending_intent,
                    json.dumps(pending_entities, sort_keys=True)
                    if pending_entities is not None
                    else None,
                    pending_confidence,
                    conversation_id,
                    user_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO workflow_events
                    (conversation_id, user_id, selected_role, intent, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, selected_role, intent, outcome),
            )
            self._log_activity(
                connection,
                user_id,
                "workflow_request",
                "conversation",
                conversation_id,
                {"role": selected_role, "intent": intent, "outcome": outcome},
            )

            escalation_id = None
            escalation_status = None
            if escalation_reason is not None:
                existing = connection.execute(
                    """
                    SELECT id, status FROM escalations
                    WHERE conversation_id = ? AND status IN ('pending', 'accepted')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (conversation_id,),
                ).fetchone()
                if existing is None:
                    escalation_id = uuid.uuid4().hex
                    connection.execute(
                        """
                        INSERT INTO escalations (id, conversation_id, reason)
                        VALUES (?, ?, ?)
                        """,
                        (escalation_id, conversation_id, escalation_reason[:1000]),
                    )
                    escalation_status = "pending"
                    self._log_activity(
                        connection,
                        user_id,
                        "escalation_created",
                        "escalation",
                        escalation_id,
                        {"reason": escalation_reason[:1000]},
                    )
                else:
                    escalation_id = str(existing["id"])
                    escalation_status = str(existing["status"])
                connection.execute(
                    """
                    UPDATE conversations
                    SET status = 'escalated'
                    WHERE id = ? AND user_id = ?
                    """,
                    (conversation_id, user_id),
                )

            return {
                "escalation_id": escalation_id,
                "escalation_status": escalation_status,
            }

    def get_conversation(
        self,
        conversation_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = """
            SELECT id, user_id, selected_role, title, status,
                   pending_intent, pending_entities, pending_confidence,
                   created_at, updated_at
            FROM conversations
            WHERE id = ?
        """
        parameters: tuple[str, ...] = (conversation_id,)
        if user_id is not None:
            query += " AND user_id = ?"
            parameters += (user_id,)

        with database_connection(self.database_path) as connection:
            row = connection.execute(query, parameters).fetchone()
            return dict(row) if row is not None else None

    def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        with database_connection(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.selected_role, c.title, c.status,
                       c.created_at, c.updated_at,
                       (SELECT m.body FROM messages AS m
                        WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1)
                           AS last_message,
                       (SELECT e.status FROM escalations AS e
                        WHERE e.conversation_id = c.id
                        ORDER BY e.created_at DESC, e.id DESC LIMIT 1)
                           AS escalation_status
                FROM conversations AS c
                WHERE c.user_id = ?
                ORDER BY c.updated_at DESC, c.id DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with database_connection(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT sender, body, status, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 8,
    ) -> list[dict[str, str]]:
        """Return a bounded, chronological context from an owned conversation."""
        safe_limit = max(1, min(limit, 20))
        with database_connection(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT recent.sender, recent.body
                FROM (
                    SELECT m.id, m.sender, m.body
                    FROM messages AS m
                    JOIN conversations AS c ON c.id = m.conversation_id
                    WHERE c.id = ? AND c.user_id = ?
                    ORDER BY m.id DESC
                    LIMIT ?
                ) AS recent
                ORDER BY recent.id
                """,
                (conversation_id, user_id, safe_limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def latest_escalation(self, conversation_id: str) -> dict[str, Any] | None:
        with database_connection(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT id, reason, status, created_at, accepted_at, resolved_at
                FROM escalations
                WHERE conversation_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def add_message(
        self,
        conversation_id: str,
        sender: str,
        body: str,
        status: str | None = None,
    ) -> None:
        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO messages (conversation_id, sender, body, status)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, sender, body, status),
            )
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = CURRENT_TIMESTAMP,
                    status = CASE WHEN status = 'resolved' THEN 'active' ELSE status END
                WHERE id = ?
                """,
                (conversation_id,),
            )

    def set_pending_context(
        self,
        conversation_id: str,
        intent: str | None,
        entities: dict[str, Any] | None,
        confidence: float | None,
    ) -> None:
        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                UPDATE conversations
                SET pending_intent = ?, pending_entities = ?, pending_confidence = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    intent,
                    json.dumps(entities, sort_keys=True) if entities is not None else None,
                    confidence,
                    conversation_id,
                ),
            )

    def record_workflow_event(
        self,
        user_id: str,
        conversation_id: str | None,
        selected_role: str,
        intent: str,
        outcome: str,
    ) -> None:
        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO workflow_events
                    (conversation_id, user_id, selected_role, intent, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, selected_role, intent, outcome),
            )
            self._log_activity(
                connection,
                user_id,
                "workflow_request",
                "conversation" if conversation_id else "workflow",
                conversation_id,
                {"role": selected_role, "intent": intent, "outcome": outcome},
            )

    def create_escalation(
        self,
        conversation_id: str,
        user_id: str,
        reason: str,
    ) -> str:
        with database_connection(self.database_path) as connection:
            existing = connection.execute(
                """
                SELECT id FROM escalations
                WHERE conversation_id = ? AND status IN ('pending', 'accepted')
                ORDER BY created_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
            if existing is not None:
                return str(existing["id"])

            escalation_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO escalations (id, conversation_id, reason)
                VALUES (?, ?, ?)
                """,
                (escalation_id, conversation_id, reason),
            )
            connection.execute(
                """
                UPDATE conversations
                SET status = 'escalated', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (conversation_id,),
            )
            self._log_activity(
                connection,
                user_id,
                "escalation_created",
                "escalation",
                escalation_id,
                {"reason": reason},
            )
            return escalation_id

    def list_escalations(
        self,
        account_role: str,
        username: str,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT e.id, e.conversation_id, e.reason, e.status, e.agent_username,
                   e.created_at, e.accepted_at, e.resolved_at,
                   c.selected_role, c.title
            FROM escalations AS e
            JOIN conversations AS c ON c.id = e.conversation_id
        """
        parameters: tuple[str, ...] = ()
        if account_role != "admin":
            query += """
                WHERE e.status = 'pending'
                   OR (e.status = 'accepted' AND e.agent_username = ?)
            """
            parameters = (username,)
        query += " ORDER BY e.created_at DESC, e.id DESC"

        with database_connection(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
            escalations = []
            for row in rows:
                item = dict(row)
                messages = connection.execute(
                    """
                    SELECT sender, body, status, created_at
                    FROM messages WHERE conversation_id = ? ORDER BY id
                    """,
                    (item["conversation_id"],),
                ).fetchall()
                item["messages"] = [dict(message) for message in messages]
                item["can_resolve"] = (
                    item["status"] == "accepted"
                    and (
                        account_role == "admin"
                        or item["agent_username"] == username
                    )
                )
                escalations.append(item)
            return escalations

    def accept_escalation(
        self,
        escalation_id: str,
        username: str,
    ) -> str:
        with database_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT status FROM escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            if row is None:
                return "not_found"
            if row["status"] != "pending":
                return "conflict"
            updated = connection.execute(
                """
                UPDATE escalations
                SET status = 'accepted', agent_username = ?,
                    accepted_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (username, escalation_id),
            )
            if updated.rowcount != 1:
                return "conflict"
            self._log_activity(
                connection,
                username,
                "escalation_accepted",
                "escalation",
                escalation_id,
            )
            return "accepted"

    def resolve_escalation(
        self,
        escalation_id: str,
        username: str,
        account_role: str,
        response: str,
    ) -> str:
        with database_connection(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT conversation_id, status, agent_username
                FROM escalations WHERE id = ?
                """,
                (escalation_id,),
            ).fetchone()
            if row is None:
                return "not_found"
            if row["status"] != "accepted":
                return "conflict"
            if account_role != "admin" and row["agent_username"] != username:
                return "forbidden"

            updated = connection.execute(
                """
                UPDATE escalations SET status = 'resolved',
                    resolved_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'accepted'
                """,
                (escalation_id,),
            )
            if updated.rowcount != 1:
                return "conflict"
            connection.execute(
                """
                INSERT INTO messages (conversation_id, sender, body, status)
                VALUES (?, 'agent', ?, 'resolved')
                """,
                (row["conversation_id"], response),
            )
            connection.execute(
                """
                UPDATE conversations SET status = 'resolved',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["conversation_id"],),
            )
            self._log_activity(
                connection,
                username,
                "escalation_resolved",
                "escalation",
                escalation_id,
            )
            return "resolved"

    def set_role_active(
        self,
        role_key: str,
        active: bool,
        actor: str,
    ) -> bool:
        with database_connection(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE assistant_roles
                SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE role_key = ?
                """,
                (int(active), role_key),
            )
            if cursor.rowcount != 1:
                return False
            self._log_activity(
                connection,
                actor,
                "assistant_role_activated" if active else "assistant_role_deactivated",
                "assistant_role",
                role_key,
                {"active": active},
            )
            return True

    def list_roles(self, active_only: bool = False) -> list[dict[str, Any]]:
        query = """
            SELECT role_key, display_name, is_active, updated_at
            FROM assistant_roles
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY role_key"
        with database_connection(self.database_path) as connection:
            return [
                dict(row) for row in connection.execute(query).fetchall()
            ]

    def dashboard_metrics(self) -> dict[str, Any]:
        with database_connection(self.database_path) as connection:
            conversations = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN status = 'escalated' THEN 1 ELSE 0 END) AS escalated,
                       SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved
                FROM conversations
                """
            ).fetchone()
            workflow_totals = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome IN
                           ('success', 'integration_error', 'execution_error')
                           THEN 1 ELSE 0 END) AS executions,
                       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successful
                FROM workflow_events
                """
            ).fetchone()
            escalation_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM escalations GROUP BY status ORDER BY status
                """
            ).fetchall()
            role_rows = connection.execute(
                """
                SELECT r.role_key, r.display_name, r.is_active,
                       COUNT(DISTINCT c.id) AS conversations,
                       COUNT(DISTINCT w.id) AS workflow_requests
                FROM assistant_roles AS r
                LEFT JOIN conversations AS c ON c.selected_role = r.role_key
                LEFT JOIN workflow_events AS w ON w.selected_role = r.role_key
                GROUP BY r.role_key
                ORDER BY r.role_key
                """
            ).fetchall()
            outcome_rows = connection.execute(
                """
                SELECT selected_role, intent, outcome, COUNT(*) AS count
                FROM workflow_events
                GROUP BY selected_role, intent, outcome
                ORDER BY selected_role, intent, outcome
                """
            ).fetchall()
            activity_rows = connection.execute(
                """
                SELECT COALESCE(u.role, 'system') AS actor_role,
                       a.action, a.entity_type, a.entity_id, a.created_at
                FROM activity_log AS a
                LEFT JOIN users AS u ON u.username = a.actor_username
                ORDER BY a.id DESC LIMIT 50
                """
            ).fetchall()
            return {
                "conversations": {
                    key: int(conversations[key] or 0)
                    for key in ("total", "active", "escalated", "resolved")
                },
                "workflow_requests": int(workflow_totals["total"] or 0),
                "workflow_executions": int(workflow_totals["executions"] or 0),
                "successful_workflow_requests": int(
                    workflow_totals["successful"] or 0
                ),
                "escalations": {
                    row["status"]: int(row["count"]) for row in escalation_rows
                },
                "roles": [dict(row) for row in role_rows],
                "workflow_outcomes": [dict(row) for row in outcome_rows],
                "recent_activity": [dict(row) for row in activity_rows],
            }

    @staticmethod
    def _log_activity(
        connection: sqlite3.Connection,
        actor: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO activity_log
                (actor_username, action, entity_type, entity_id, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(details or {}, sort_keys=True),
            ),
        )
