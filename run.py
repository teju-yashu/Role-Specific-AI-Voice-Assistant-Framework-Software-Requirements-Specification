import json
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import threading
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge
from flask_cors import CORS

load_dotenv()

from app.agents.workflow_agent import WorkflowAgent
from app.authentication import UserStore
from app.llm.openai_client import OpenAIClient, OpenAIServiceUnavailable
from app.nlu.assistant_nlu import RuleBasedAssistantNLU
from app.nlu.response_evaluator import ResponseEvaluator
from app.nlu.response_generator import (
    DeterministicResponseProvider,
    OpenAIResponseProvider,
    ResponseGenerator,
    ResponseProviderUnavailable,
)
from app.storage import ConversationStore, initialize_database

PROJECT_NAME = "Role-Specific AI Voice Assistant Framework for Organizations and Entities"

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=64 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").casefold()
    not in {"0", "false", "no"},
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_REFRESH_EACH_REQUEST=False,
    AUTH_DATABASE=os.environ.get(
        "AUTH_DATABASE",
        str(Path(app.instance_path) / "user_accounts.sqlite3"),
    ),
    OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY"),
    OPENAI_MODEL=os.environ.get("OPENAI_MODEL", ""),
    OPENAI_ENABLED=os.environ.get("OPENAI_ENABLED"),
    OPENAI_TIMEOUT_SECONDS=os.environ.get("OPENAI_TIMEOUT_SECONDS", "20"),
    BOOTSTRAP_ADMIN_USERNAME=os.environ.get("BOOTSTRAP_ADMIN_USERNAME"),
    BOOTSTRAP_ADMIN_PASSWORD=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD"),
    BOOTSTRAP_AGENT_USERNAME=os.environ.get("BOOTSTRAP_AGENT_USERNAME"),
    BOOTSTRAP_AGENT_PASSWORD=os.environ.get("BOOTSTRAP_AGENT_PASSWORD"),
)
_cors_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
for _origin in _cors_origins:
    try:
        _parsed_origin = urlsplit(_origin)
        _ = _parsed_origin.port
    except ValueError:
        raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid origin.") from None
    if (
        "*" in _origin
        or _parsed_origin.scheme not in {"http", "https"}
        or not _parsed_origin.netloc
        or _parsed_origin.username is not None
        or _parsed_origin.password is not None
        or _parsed_origin.path
        or _parsed_origin.query
        or _parsed_origin.fragment
    ):
        raise ValueError(
            "CORS_ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths or wildcards."
        )
if _cors_origins:
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}})
workflow_agent = WorkflowAgent()
assistant_nlu = RuleBasedAssistantNLU()
openai_client = OpenAIClient.from_environment()
response_generator = ResponseGenerator(
    provider=(
        OpenAIResponseProvider(openai_client)
        if openai_client.is_enabled
        else None
    )
)
response_evaluator = ResponseEvaluator()
ROLE_WORKFLOW_INTENTS = {
    "HR": "check_leave_balance",
    "IT Support": "raise_it_support_ticket",
    "Admissions": "check_application_status",
}
_database_bootstrap_state = {}
_database_bootstrap_lock = threading.Lock()
_bootstrap_signature_key = secrets.token_bytes(32)


@app.before_request
def prepare_database():
    if not app.testing:
        configured_secret = os.environ.get("FLASK_SECRET_KEY")
        if not configured_secret or len(configured_secret) < 32:
            app.logger.error("A stable FLASK_SECRET_KEY is required to serve requests.")
            if request.path.startswith("/api/"):
                return jsonify({"error": "The service is not configured."}), 503
            return "The service is not configured.", 503

    database_path = app.config["AUTH_DATABASE"]
    bootstrap_pairs = (
        (
            app.config.get("BOOTSTRAP_ADMIN_USERNAME"),
            app.config.get("BOOTSTRAP_ADMIN_PASSWORD"),
            "admin",
        ),
        (
            app.config.get("BOOTSTRAP_AGENT_USERNAME"),
            app.config.get("BOOTSTRAP_AGENT_PASSWORD"),
            "agent",
        ),
    )
    state_key = str(Path(database_path).resolve())
    signature_payload = json.dumps(
        bootstrap_pairs,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(
        _bootstrap_signature_key,
        signature_payload,
        hashlib.sha256,
    ).digest()
    with _database_bootstrap_lock:
        initialize_database(database_path)
        if _database_bootstrap_state.get(state_key) == signature:
            return
        configured_usernames = [
            username.strip().casefold()
            for username, password, _ in bootstrap_pairs
            if username and password
        ]
        if len(configured_usernames) != len(set(configured_usernames)):
            raise RuntimeError(
                "Administrator and agent bootstrap accounts must be distinct."
            )
        store = user_store()
        for username, password, role in bootstrap_pairs:
            if username is None and password is None:
                continue
            if not isinstance(username, str) or not isinstance(password, str):
                raise RuntimeError(
                    "Both username and password are required for bootstrap accounts."
                )
            store.bootstrap_user(username.strip().casefold(), password, role)
        _database_bootstrap_state[state_key] = signature


def get_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def has_valid_csrf_token() -> bool:
    expected = session.get("_csrf_token")
    supplied = request.headers.get("X-CSRF-Token", "")
    return (
        isinstance(expected, str)
        and bool(supplied)
        and secrets.compare_digest(expected, supplied)
    )


def require_roles_api(*allowed_roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            username = session.get("username")
            if not isinstance(username, str):
                return jsonify({"error": "Authentication required."}), 401
            account_role = user_store().get_role(username)
            if account_role is None:
                session.clear()
                return jsonify({"error": "Authentication required."}), 401
            if allowed_roles and account_role not in allowed_roles:
                return jsonify({"error": "You are not authorized for this action."}), 403
            if (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and not has_valid_csrf_token()
            ):
                return jsonify({"error": "A valid CSRF token is required."}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorate


def require_authenticated_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        username = session.get("username")
        if not isinstance(username, str):
            return jsonify({"error": "Authentication required."}), 401
        account_role = user_store().get_role(username)
        if account_role is None:
            session.clear()
            return jsonify({"error": "Authentication required."}), 401
        if account_role != "user":
            return jsonify({"error": "You are not authorized for this action."}), 403
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and not has_valid_csrf_token()
        ):
            return jsonify({"error": "A valid CSRF token is required."}), 403
        return view(*args, **kwargs)

    return wrapped


def require_page_role(*allowed_roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            username = session.get("username")
            if not isinstance(username, str):
                return redirect(url_for("login_page"))
            account_role = user_store().get_role(username)
            if account_role is None:
                session.clear()
                return redirect(url_for("login_page"))
            if account_role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


def parse_json_object():
    if not request.is_json:
        return None, (jsonify({"error": "Request body must be valid JSON."}), 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "Request body must be a JSON object."}), 400)
    return payload, None


def _active_role(role: str) -> bool:
    canonical_role = assistant_nlu.SUPPORTED_ROLES.get(
        " ".join(role.split()).casefold()
    )
    if canonical_role is None:
        return False
    return any(
        item["role_key"] == canonical_role and item["is_active"]
        for item in conversation_store().list_roles()
    )


def conversation_store() -> ConversationStore:
    return ConversationStore(app.config["AUTH_DATABASE"])


def portal_url_for(username: str) -> str:
    account_role = user_store().get_role(username)
    if account_role == "admin":
        return url_for("admin_page")
    if account_role == "agent":
        return url_for("agent_page")
    if account_role is None:
        return url_for("login_page")
    return url_for("chat")


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.error("Database operation failed (%s).", type(error).__name__)
    if request.path.startswith("/api/"):
        return jsonify({"error": "The service is temporarily unavailable."}), 503
    return "The service is temporarily unavailable.", 503


@app.errorhandler(RequestEntityTooLarge)
def handle_oversized_request(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Request body exceeds the allowed size."}), 413
    return "Request body exceeds the allowed size.", 413


def _valid_conversation_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and re.fullmatch(r"[a-fA-F0-9]{32}", value) is not None
    )


def _account_role() -> str | None:
    username = session.get("username")
    return user_store().get_role(username) if isinstance(username, str) else None


def _escalation_http_status(outcome: str) -> int:
    return {"not_found": 404, "conflict": 409, "forbidden": 403}.get(outcome, 200)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _validated_llm_request(
    suggestion: object,
    role: str,
    query: str,
    rule_entities: dict[str, Any],
) -> dict[str, Any] | None:
    """Accept only registered intents and entities grounded in this message."""
    if not isinstance(suggestion, dict):
        return None
    intent = suggestion.get("intent")
    confidence = suggestion.get("confidence")
    entities = suggestion.get("entities")
    if (
        not isinstance(intent, str)
        or not _is_finite_number(confidence)
        or not 0 <= confidence <= 1
        or not isinstance(entities, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in entities.items())
    ):
        return None

    intent = intent.strip().casefold()
    if intent == "general":
        if entities:
            return None
        return {
            "selected_role": role,
            "intent": "general",
            "entities": {},
            "confidence": float(confidence),
        }

    workflow = workflow_agent.workflow_registry.get(role, intent)
    if workflow is None:
        return None
    allowed_entities = set(workflow.required_entities)
    if not set(entities).issubset(allowed_entities):
        return None

    merged_entities = dict(rule_entities)
    for entity, value in entities.items():
        normalized_value = value.strip()
        if (
            not normalized_value
            or len(normalized_value) > 1000
            or normalized_value.casefold() not in query.casefold()
        ):
            return None
        if entity in {"employee_id", "application_id"} and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}",
            normalized_value,
        ) is None:
            return None
        if any(
            ord(character) < 32 and character not in "\t\n\r"
            for character in normalized_value
        ):
            return None
        merged_entities[entity] = normalized_value

    for entity, value in merged_entities.items():
        if (
            entity not in allowed_entities
            or not isinstance(value, str)
            or not value.strip()
            or len(value) > 1000
            or any(
                ord(character) < 32 and character not in "\t\n\r"
                for character in value
            )
        ):
            return None
        if entity in {"employee_id", "application_id"} and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}",
            value.strip(),
        ) is None:
            return None

    return {
        "selected_role": role,
        "intent": intent,
        "entities": merged_entities,
        "confidence": float(confidence),
    }


def _valid_workflow_arguments(workflow_request: dict[str, Any]) -> bool:
    workflow = workflow_agent.workflow_registry.get(
        workflow_request["selected_role"],
        workflow_request["intent"],
    )
    entities = workflow_request.get("entities")
    if workflow is None or not isinstance(entities, dict):
        return False
    allowed_entities = set(workflow.required_entities)
    if not set(entities).issubset(allowed_entities):
        return False
    for entity, value in entities.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 1000
            or any(
                ord(character) < 32 and character not in "\t\n\r"
                for character in value
            )
        ):
            return False
        if entity in {"employee_id", "application_id"} and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}",
            value.strip(),
        ) is None:
            return False
    return True


def _valid_workflow_result(
    result: object,
    selected_role: str,
    intent: str,
    entities: dict[str, Any],
) -> bool:
    if not isinstance(result, dict):
        return False
    allowed_statuses = {
        "success",
        "clarification_required",
        "escalation_required",
        "integration_error",
        "execution_error",
        "unknown_intent",
        "invalid_input",
        "invalid_role",
    }
    if (
        result.get("status") not in allowed_statuses
        or result.get("role") != selected_role
        or result.get("intent") != intent
        or not isinstance(result.get("message"), str)
        or not isinstance(result.get("escalation"), dict)
    ):
        return False
    if result["status"] != "success":
        return result.get("data") is None or isinstance(result.get("data"), dict)

    data = result.get("data")
    if not isinstance(data, dict):
        return False
    if selected_role == "HR" and intent == "check_leave_balance":
        balance = data.get("leave_balance_days")
        return (
            data.get("employee_id") == entities.get("employee_id")
            and isinstance(balance, (int, float))
            and _is_finite_number(balance)
            and balance >= 0
        )
    if selected_role == "IT Support" and intent == "raise_it_support_ticket":
        return (
            isinstance(data.get("ticket_id"), str)
            and bool(data["ticket_id"].strip())
            and isinstance(data.get("status"), str)
            and bool(data["status"].strip())
            and data.get("issue_description") == entities.get("issue_description")
        )
    if selected_role == "Admissions" and intent == "check_application_status":
        return (
            data.get("application_id") == entities.get("application_id")
            and isinstance(data.get("application_status"), str)
            and bool(data["application_status"].strip())
        )
    return False


def parse_auth_payload():
    if not request.is_json:
        return None, (jsonify({"error": "Request body must be valid JSON."}), 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "Request body must be a JSON object."}), 400)
    return payload, None


def valid_csrf_response():
    if has_valid_csrf_token():
        return None
    return jsonify({"error": "A valid CSRF token is required."}), 403


def user_store() -> UserStore:
    return UserStore(app.config["AUTH_DATABASE"])


@app.get("/")
def index():
    return jsonify(
        {
            "project_name": PROJECT_NAME,
            "status": "Backend is running",
        }
    )


@app.get("/login")
def login_page():
    if isinstance(session.get("username"), str):
        destination = portal_url_for(session["username"])
        if destination != url_for("login_page"):
            return redirect(destination)
        session.clear()
    return render_template("auth.html", csrf_token=get_csrf_token())


@app.get("/register")
def register_page():
    if isinstance(session.get("username"), str):
        destination = portal_url_for(session["username"])
        if destination != url_for("login_page"):
            return redirect(destination)
        session.clear()
    return render_template("auth.html", csrf_token=get_csrf_token())


@app.get("/chat")
def chat():
    if not isinstance(session.get("username"), str):
        return redirect(url_for("login_page"))
    account_role = _account_role()
    if account_role is None:
        session.clear()
        return redirect(url_for("login_page"))
    if account_role != "user":
        return redirect(portal_url_for(session["username"]))
    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        assistant_roles=conversation_store().list_roles(active_only=True),
        openai_configured=openai_client.is_enabled,
    )


@app.get("/agent")
@require_page_role("agent", "admin")
def agent_page():
    return render_template(
        "agent.html",
        csrf_token=get_csrf_token(),
        username=session["username"],
        account_role=_account_role(),
    )


@app.get("/admin")
@require_page_role("admin")
def admin_page():
    return render_template(
        "admin.html",
        csrf_token=get_csrf_token(),
        username=session["username"],
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "healthy",
            "service": PROJECT_NAME,
        }
    )


@app.post("/api/auth/register")
def register_account():
    csrf_error = valid_csrf_response()
    if csrf_error is not None:
        return csrf_error

    payload, error = parse_auth_payload()
    if error is not None:
        return error

    if "role" in payload:
        return jsonify({"error": "Account roles are assigned by the system."}), 400

    missing_fields = [
        field for field in ("username", "password") if field not in payload
    ]
    if missing_fields:
        return jsonify({"error": "Missing required fields.", "fields": missing_fields}), 400

    username = payload["username"]
    password = payload["password"]
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 128:
        return (
            jsonify({"error": "Username must contain between 1 and 128 characters."}),
            400,
        )
    if not username.strip().isprintable():
        return jsonify({"error": "Username contains unsupported characters."}), 400
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        return (
            jsonify({"error": "Password must contain between 8 and 1024 characters."}),
            400,
        )

    normalized_username = username.strip().casefold()
    if not user_store().create_user(normalized_username, password):
        return jsonify({"error": "An account with that username already exists."}), 409

    return jsonify({"status": "registered", "username": normalized_username}), 201


@app.post("/api/auth/login")
def login_account():
    csrf_error = valid_csrf_response()
    if csrf_error is not None:
        return csrf_error

    payload, error = parse_auth_payload()
    if error is not None:
        return error

    missing_fields = [
        field for field in ("username", "password") if field not in payload
    ]
    if missing_fields:
        return (
            jsonify({"error": "Missing required fields.", "fields": missing_fields}),
            400,
        )

    username = payload["username"]
    password = payload["password"]
    if (
        not isinstance(username, str)
        or not username.strip()
        or len(username) > 128
        or not isinstance(password, str)
        or not password
        or len(password) > 1024
    ):
        return jsonify({"error": "Username or password is invalid."}), 400

    authenticated_username = user_store().authenticate_user(
        username.strip().casefold(),
        password,
    )
    if authenticated_username is None:
        return jsonify({"error": "Invalid username or password."}), 401

    session.clear()
    session.permanent = True
    session["username"] = authenticated_username
    session["_csrf_token"] = secrets.token_urlsafe(32)
    account_role = user_store().get_role(authenticated_username)
    return jsonify(
        {
            "status": "authenticated",
            "username": authenticated_username,
            "role": account_role,
            "csrf_token": session["_csrf_token"],
            "redirect_url": portal_url_for(authenticated_username),
        }
    )


@app.post("/api/auth/logout")
def logout_account():
    csrf_error = valid_csrf_response()
    if csrf_error is not None:
        return csrf_error
    session.clear()
    return jsonify({"status": "logged_out", "redirect_url": url_for("login_page")})


@app.post("/api/workflows/execute")
@require_authenticated_api
def execute_workflow():
    payload, error = parse_json_object()
    if error is not None:
        return error

    required_fields = ("selected_role", "intent", "entities", "confidence")
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        return jsonify({"error": "Missing required fields.", "fields": missing_fields}), 400

    selected_role = payload["selected_role"]
    intent = payload["intent"]
    entities = payload["entities"]
    confidence = payload["confidence"]

    if not isinstance(selected_role, str) or not selected_role.strip():
        return jsonify({"error": "'selected_role' must be a non-empty string."}), 400
    if not isinstance(intent, str) or not intent.strip():
        return jsonify({"error": "'intent' must be a non-empty string."}), 400
    if not isinstance(entities, dict):
        return jsonify({"error": "'entities' must be a JSON object."}), 400
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return jsonify({"error": "'confidence' must be a number from 0 to 1."}), 400
    if _active_role(selected_role) is False and assistant_nlu.SUPPORTED_ROLES.get(
        " ".join(selected_role.split()).casefold()
    ):
        return jsonify({"error": "The selected assistant role is inactive."}), 409

    result = workflow_agent.execute(
        selected_role=selected_role,
        intent=intent,
        entities=entities,
        confidence=confidence,
    )
    conversation_store().record_workflow_event(
        session["username"],
        None,
        result.get("role") or selected_role,
        result.get("intent") or intent,
        result["status"],
    )
    status_code = 400 if result["status"] in {"invalid_input", "invalid_role"} else 200
    return jsonify(result), status_code


@app.post("/api/assistant/execute")
@require_authenticated_api
def execute_assistant_query():
    payload, error = parse_json_object()
    if error is not None:
        return error

    missing_fields = [
        field for field in ("selected_role", "query") if field not in payload
    ]
    if missing_fields:
        return jsonify({"error": "Missing required fields.", "fields": missing_fields}), 400

    if (
        not isinstance(payload["selected_role"], str)
        or not payload["selected_role"].strip()
        or not isinstance(payload["query"], str)
        or not payload["query"].strip()
        or len(payload["query"]) > 5000
    ):
        return jsonify({"error": "Role and query must be valid non-empty text."}), 400

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and not _valid_conversation_id(conversation_id):
        return jsonify({"error": "conversation_id must be a valid conversation ID."}), 400

    query = payload["query"].strip()
    try:
        rule_request = assistant_nlu.interpret(
            selected_role=payload["selected_role"],
            query=query,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    selected_role = rule_request["selected_role"]
    if not _active_role(selected_role):
        return jsonify({"error": "The selected assistant role is inactive."}), 409

    store = conversation_store()
    username = session["username"]
    is_new_conversation = conversation_id is None
    conversation = None
    if conversation_id is not None:
        conversation = store.get_conversation(conversation_id, username)
        if conversation is None:
            return jsonify({"error": "Conversation not found."}), 404
        if conversation["selected_role"] != selected_role:
            return jsonify({"error": "A conversation cannot change assistant roles."}), 409
    recent_messages = (
        store.get_recent_messages(conversation_id, username, limit=8)
        if conversation is not None
        else []
    )
    pending_intent = conversation["pending_intent"] if conversation else None
    pending_entities = (
        json.loads(conversation["pending_entities"] or "{}")
        if conversation and pending_intent
        else {}
    )
    conversation_context = {
        "recent_messages": recent_messages,
        "pending_clarification": (
            {
                "intent": pending_intent,
                "entities": pending_entities,
                "confidence": conversation["pending_confidence"],
            }
            if pending_intent and conversation
            else None
        ),
    }

    workflow_request = rule_request
    llm_interpretation_succeeded = False
    model_uncertain = False
    general_question = False
    if openai_client.is_enabled:
        try:
            suggestion = openai_client.interpret_request(
                selected_role,
                query,
                conversation_context,
            )
        except OpenAIServiceUnavailable:
            suggestion = None
        else:
            llm_interpretation_succeeded = True
            validated_suggestion = _validated_llm_request(
                suggestion,
                selected_role,
                query,
                rule_request["entities"],
            )
            if validated_suggestion is not None:
                if validated_suggestion["intent"] == "general":
                    if validated_suggestion["confidence"] >= 0.7:
                        workflow_request = validated_suggestion
                        general_question = True
                elif validated_suggestion["confidence"] < 0.7:
                    workflow_request = validated_suggestion
                    model_uncertain = True
                else:
                    workflow_request = validated_suggestion

    if pending_intent and conversation is not None:
        pending_workflow = workflow_agent.workflow_registry.get(
            selected_role,
            pending_intent,
        )
        if pending_workflow is not None:
            follow_up_entities = assistant_nlu.extract_follow_up_entities(
                selected_role,
                query,
                pending_workflow.required_entities,
            )
            merged_pending_entities = dict(pending_entities)
            merged_pending_entities.update(follow_up_entities)
            workflow_request = {
                "selected_role": selected_role,
                "intent": pending_intent,
                "entities": merged_pending_entities,
                "confidence": conversation["pending_confidence"] or 0.9,
            }
            general_question = False
            model_uncertain = False
    else:
        if conversation is None:
            conversation_id = store.new_conversation_id()

    if general_question:
        result = {
            "status": "general_question",
            "role": selected_role,
            "intent": "general",
            "message": "Respond to a general role-related question.",
            "data": None,
            "escalation": {"required": False},
        }
    elif model_uncertain:
        clarification_question = (
            "Could you clarify what you’d like me to do before I proceed?"
        )
        result = {
            "status": "clarification_required",
            "role": selected_role,
            "intent": workflow_request["intent"],
            "message": "The request is not clear enough to run a workflow.",
            "data": {"missing_entities": []},
            "escalation": {"required": False},
            "clarification_question": clarification_question,
        }
    elif workflow_request["intent"] in {"unknown", "general"}:
        result = {
            "status": "unknown_intent",
            "role": workflow_request["selected_role"],
            "intent": workflow_request["intent"],
            "message": "No supported intent was recognized for this role.",
            "data": None,
            "escalation": {"required": False},
        }
    elif not _valid_workflow_arguments(workflow_request):
        result = {
            "status": "invalid_input",
            "role": workflow_request["selected_role"],
            "intent": workflow_request["intent"],
            "message": "Workflow arguments did not pass validation.",
            "data": {"invalid_entities": True},
            "escalation": {"required": False},
        }
    else:
        result = workflow_agent.execute(**workflow_request)
        if not _valid_workflow_result(
            result,
            workflow_request["selected_role"],
            workflow_request["intent"],
            workflow_request["entities"],
        ):
            result = {
                "status": "execution_error",
                "role": workflow_request["selected_role"],
                "intent": workflow_request["intent"],
                "message": "The workflow returned an invalid result.",
                "data": {"failure_category": "invalid_workflow_result"},
                "escalation": {
                    "required": True,
                    "reason": "invalid_workflow_result",
                },
            }

    clarification_question = None
    if (
        result["status"] == "clarification_required"
        and "clarification_question" not in result
    ):
        clarification_question = assistant_nlu.clarification_question(
            result["data"]["missing_entities"]
        )
        result["clarification_question"] = clarification_question
    elif result["status"] == "clarification_required":
        clarification_question = result["clarification_question"]

    response_generation_status = "success"
    response_source = response_generator.provider_name
    llm_mode = "fallback"
    try:
        if (
            response_generator.provider_name == "openai"
            and not llm_interpretation_succeeded
        ):
            raise ResponseProviderUnavailable(
                "The OpenAI service was unavailable during interpretation."
            )
        response_text = response_generator.generate(
            selected_role=workflow_request["selected_role"],
            query=query,
            intent=workflow_request["intent"],
            workflow_result=result,
            clarification_question=clarification_question,
            conversation_context=conversation_context,
        )
        evaluation = response_evaluator.evaluate(
            selected_role=workflow_request["selected_role"],
            intent=workflow_request["intent"],
            workflow_result=result,
            response=response_text,
        )
        if not evaluation["relevant"]:
            fallback_generator = ResponseGenerator(provider=DeterministicResponseProvider())
            response_text = fallback_generator.generate(
                selected_role=workflow_request["selected_role"],
                query=query,
                intent=workflow_request["intent"],
                workflow_result=result,
                clarification_question=clarification_question,
                conversation_context=conversation_context,
            )
            evaluation = response_evaluator.evaluate(
                selected_role=workflow_request["selected_role"],
                intent=workflow_request["intent"],
                workflow_result=result,
                response=response_text,
            )
            response_source = "deterministic_fallback"
            result["response_replaced"] = True
            llm_mode = "fallback"
        elif response_generator.provider_name == "openai":
            response_source = "openai"
            llm_mode = "openai"
    except ResponseProviderUnavailable:
        if response_generator.provider_name == "openai":
            fallback_generator = ResponseGenerator(provider=DeterministicResponseProvider())
            response_text = fallback_generator.generate(
                selected_role=workflow_request["selected_role"],
                query=query,
                intent=workflow_request["intent"],
                workflow_result=result,
                clarification_question=clarification_question,
                conversation_context=conversation_context,
            )
            evaluation = response_evaluator.evaluate(
                selected_role=workflow_request["selected_role"],
                intent=workflow_request["intent"],
                workflow_result=result,
                response=response_text,
            )
            response_source = "deterministic_fallback"
            response_generation_status = "fallback"
        else:
            response_text = (
                "The workflow outcome is available, but a natural-language "
                "response could not be generated."
            )
            evaluation = response_evaluator.evaluate(
                selected_role=workflow_request["selected_role"],
                intent=workflow_request["intent"],
                workflow_result=result,
                response=response_text,
            )
            response_source = "unavailable"
            response_generation_status = "unavailable"

    result["response"] = response_text
    result["response_source"] = response_source
    result["response_generation_status"] = response_generation_status
    result["response_evaluation"] = evaluation
    result["conversation_id"] = conversation_id
    result["llm_mode"] = llm_mode
    escalation = result.get("escalation")
    escalation_reason = None
    if isinstance(escalation, dict) and escalation.get("required"):
        escalation_reason = str(
            escalation.get("reason")
            or result.get("message")
            or "Human review requested."
        )[:1000]

    has_missing_entities = bool(
        result["status"] == "clarification_required"
        and isinstance(result.get("data"), dict)
        and result["data"].get("missing_entities")
    )
    pending_intent_to_store = (
        str(workflow_request["intent"]) if has_missing_entities else None
    )
    pending_entities_to_store = (
        workflow_request["entities"] if has_missing_entities else None
    )
    pending_confidence_to_store = (
        float(workflow_request["confidence"]) if has_missing_entities else None
    )
    persisted_turn = store.persist_assistant_turn(
        conversation_id=conversation_id,
        user_id=username,
        selected_role=selected_role,
        query=query,
        response=response_text,
        status=str(result["status"]),
        intent=str(workflow_request["intent"]),
        outcome=str(result["status"]),
        is_new_conversation=is_new_conversation,
        pending_intent=pending_intent_to_store,
        pending_entities=pending_entities_to_store,
        pending_confidence=pending_confidence_to_store,
        escalation_reason=escalation_reason,
    )
    if persisted_turn["escalation_id"] is not None:
        result["escalation_id"] = persisted_turn["escalation_id"]
        result["escalation_status"] = persisted_turn["escalation_status"]
    return jsonify(result)


@app.get("/api/conversations")
@require_authenticated_api
def list_conversations():
    conversations = conversation_store().list_conversations(session["username"])
    return jsonify({"conversations": conversations})


@app.get("/api/conversations/<conversation_id>")
@require_authenticated_api
def get_conversation(conversation_id):
    if not _valid_conversation_id(conversation_id):
        return jsonify({"error": "Conversation not found."}), 404
    store = conversation_store()
    conversation = store.get_conversation(conversation_id, session["username"])
    if conversation is None:
        return jsonify({"error": "Conversation not found."}), 404

    conversation_summary = {
        key: conversation[key]
        for key in ("id", "selected_role", "title", "status", "created_at", "updated_at")
    }
    return jsonify(
        {
            "conversation": conversation_summary,
            "messages": store.get_messages(conversation_id),
            "escalation": store.latest_escalation(conversation_id),
        }
    )


@app.get("/api/agent/escalations")
@require_roles_api("agent", "admin")
def list_escalations():
    return jsonify(
        {
            "escalations": conversation_store().list_escalations(
                _account_role(),
                session["username"],
            )
        }
    )


@app.post("/api/agent/escalations/<escalation_id>/accept")
@require_roles_api("agent", "admin")
def accept_escalation(escalation_id):
    if not _valid_conversation_id(escalation_id):
        return jsonify({"error": "Escalation not found."}), 404
    outcome = conversation_store().accept_escalation(
        escalation_id,
        session["username"],
    )
    if outcome != "accepted":
        return jsonify({"error": "Escalation is unavailable for acceptance."}), _escalation_http_status(outcome)
    return jsonify({"status": outcome, "escalation_id": escalation_id})


@app.post("/api/agent/escalations/<escalation_id>/resolve")
@require_roles_api("agent", "admin")
def resolve_escalation(escalation_id):
    if not _valid_conversation_id(escalation_id):
        return jsonify({"error": "Escalation not found."}), 404
    payload, error = parse_json_object()
    if error is not None:
        return error
    response_text = payload.get("response")
    if (
        not isinstance(response_text, str)
        or not response_text.strip()
        or len(response_text) > 5000
    ):
        return jsonify({"error": "A non-empty response of at most 5000 characters is required."}), 400

    outcome = conversation_store().resolve_escalation(
        escalation_id,
        session["username"],
        _account_role(),
        response_text.strip(),
    )
    if outcome != "resolved":
        message = {
            "not_found": "Escalation not found.",
            "forbidden": "This escalation is assigned to another agent.",
            "conflict": "Only an accepted escalation can be resolved.",
        }.get(outcome, "The escalation could not be resolved.")
        return jsonify({"error": message}), _escalation_http_status(outcome)
    return jsonify({"status": "resolved", "escalation_id": escalation_id})


@app.get("/api/admin/dashboard")
@require_roles_api("admin")
def admin_dashboard():
    metrics = conversation_store().dashboard_metrics()
    for role in metrics["roles"]:
        workflow_intent = ROLE_WORKFLOW_INTENTS.get(role["role_key"])
        workflow = (
            workflow_agent.workflow_registry.get(role["role_key"], workflow_intent)
            if workflow_intent
            else None
        )
        role["workflow_intent"] = workflow.intent if workflow else None
        role["workflow_status"] = (
            "configured" if workflow is not None else "unavailable"
        )
    metrics["prototype_metrics"] = True
    return jsonify(metrics)


@app.post("/api/admin/roles/<role>/active")
@require_roles_api("admin")
def set_assistant_role_active(role):
    payload, error = parse_json_object()
    if error is not None:
        return error
    active = payload.get("active")
    if not isinstance(active, bool):
        return jsonify({"error": "'active' must be a boolean."}), 400

    canonical_role = assistant_nlu.SUPPORTED_ROLES.get(
        " ".join(role.split()).casefold()
    )
    if canonical_role is None or canonical_role not in ROLE_WORKFLOW_INTENTS:
        return jsonify({"error": "The assistant role is not configurable."}), 400
    workflow = workflow_agent.workflow_registry.get(
        canonical_role,
        ROLE_WORKFLOW_INTENTS[canonical_role],
    )
    if active and workflow is None:
        return jsonify({"error": "The role has no registered workflow."}), 400

    updated = conversation_store().set_role_active(
        canonical_role,
        active,
        session["username"],
    )
    if not updated:
        return jsonify({"error": "The assistant role is not configured."}), 404
    return jsonify({"role": canonical_role, "active": active})


if __name__ == "__main__":
    configured_secret = os.environ.get("FLASK_SECRET_KEY")
    if not configured_secret or len(configured_secret) < 32:
        raise SystemExit(
            "Set FLASK_SECRET_KEY to a stable secret of at least 32 characters "
            "before starting the application."
        )

    debug_enabled = os.environ.get("FLASK_DEBUG", "false").casefold() in {
        "1",
        "true",
        "yes",
    }
    try:
        prepare_database()
    except (sqlite3.Error, OSError):
        raise SystemExit(
            "Application database initialization failed; check the configured "
            "SQLite file and its permissions."
        ) from None
    except (RuntimeError, ValueError) as error:
        raise SystemExit(f"Application configuration is invalid: {error}") from None
    app.run(debug=debug_enabled, port=5000)
