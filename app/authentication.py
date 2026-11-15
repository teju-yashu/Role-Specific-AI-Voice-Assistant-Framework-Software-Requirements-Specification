"""Persistent account storage and privileged-account bootstrap helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from app.storage import database_connection, initialize_database


class UserStore:
    """Store normalized usernames, roles, and Werkzeug password hashes in SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def create_user(self, username: str, password: str) -> bool:
        initialize_database(self.database_path)
        try:
            with database_connection(self.database_path) as connection:
                connection.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'user')",
                    (username, generate_password_hash(password)),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def authenticate_user(self, username: str, password: str) -> str | None:
        initialize_database(self.database_path)
        with database_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is not None:
            try:
                if check_password_hash(row["password_hash"], password):
                    return str(row["username"])
            except (TypeError, ValueError):
                return None
        return None

    def get_role(self, username: str) -> str | None:
        initialize_database(self.database_path)
        with database_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT role FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            return str(row["role"]) if row is not None else None

    def bootstrap_user(self, username: str, password: str, role: str) -> None:
        if role not in {"admin", "agent"}:
            raise ValueError("Only administrator or agent accounts can be bootstrapped.")
        if not username or not username.isprintable() or len(username) > 128:
            raise ValueError("The configured privileged username is invalid.")
        if len(password) < 12:
            raise ValueError("Privileged account passwords must be at least 12 characters.")

        initialize_database(self.database_path)
        password_hash = generate_password_hash(password)
        with database_connection(self.database_path) as connection:
            existing = connection.execute(
                "SELECT password_hash, role FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, role)
                    VALUES (?, ?, ?)
                    """,
                    (username, password_hash, role),
                )
                return

            if existing["role"] != role:
                raise RuntimeError(
                    "A configured privileged username conflicts with an existing account; "
                    "privileged bootstrap never promotes an existing account."
                )
            connection.execute(
                """
                UPDATE users SET password_hash = ?, role = ? WHERE username = ?
                """,
                (password_hash, role, username),
            )
