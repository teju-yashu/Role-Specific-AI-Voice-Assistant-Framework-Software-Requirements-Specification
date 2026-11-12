from flask import Flask, jsonify, request
from flask_cors import CORS

from app.agents.workflow_agent import WorkflowAgent
from app.nlu.assistant_nlu import RuleBasedAssistantNLU
from app.nlu.response_evaluator import ResponseEvaluator
from app.nlu.response_generator import (
    DeterministicResponseProvider,
    ResponseGenerator,
    ResponseProviderUnavailable,
)

PROJECT_NAME = "Role-Specific AI Voice Assistant Framework for Organizations and Entities"

app = Flask(__name__)
CORS(app)
workflow_agent = WorkflowAgent()
assistant_nlu = RuleBasedAssistantNLU()
response_generator = ResponseGenerator()
response_evaluator = ResponseEvaluator()


@app.get("/")
def index():
    return jsonify(
        {
            "project_name": PROJECT_NAME,
            "status": "Backend is running",
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "healthy",
            "service": PROJECT_NAME,
        }
    )


@app.post("/api/workflows/execute")
def execute_workflow():
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

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

    result = workflow_agent.execute(
        selected_role=selected_role,
        intent=intent,
        entities=entities,
        confidence=confidence,
    )
    status_code = 400 if result["status"] in {"invalid_input", "invalid_role"} else 200
    return jsonify(result), status_code


@app.post("/api/assistant/execute")
def execute_assistant_query():
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    missing_fields = [
        field for field in ("selected_role", "query") if field not in payload
    ]
    if missing_fields:
        return jsonify({"error": "Missing required fields.", "fields": missing_fields}), 400

    try:
        workflow_request = assistant_nlu.interpret(
            selected_role=payload["selected_role"],
            query=payload["query"],
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    if workflow_request["intent"] == "unknown":
        result = {
            "status": "unknown_intent",
            "role": workflow_request["selected_role"],
            "intent": workflow_request["intent"],
            "message": "No supported intent was recognized for this role.",
            "data": None,
            "escalation": {"required": False},
        }
    else:
        result = workflow_agent.execute(**workflow_request)

    clarification_question = None
    if result["status"] == "clarification_required":
        clarification_question = assistant_nlu.clarification_question(
            result["data"]["missing_entities"]
        )
        result["clarification_question"] = clarification_question

    response_generation_status = "success"
    try:
        response_text = response_generator.generate(
            selected_role=workflow_request["selected_role"],
            query=payload["query"],
            intent=workflow_request["intent"],
            workflow_result=result,
            clarification_question=clarification_question,
        )
        evaluation = response_evaluator.evaluate(
            selected_role=workflow_request["selected_role"],
            intent=workflow_request["intent"],
            workflow_result=result,
            response=response_text,
        )
        response_source = response_generator.provider_name
        if not evaluation["relevant"]:
            fallback_generator = ResponseGenerator(
                provider=DeterministicResponseProvider()
            )
            response_text = fallback_generator.generate(
                selected_role=workflow_request["selected_role"],
                query=payload["query"],
                intent=workflow_request["intent"],
                workflow_result=result,
                clarification_question=clarification_question,
            )
            evaluation = response_evaluator.evaluate(
                selected_role=workflow_request["selected_role"],
                intent=workflow_request["intent"],
                workflow_result=result,
                response=response_text,
            )
            response_source = "deterministic_fallback"
            result["response_replaced"] = True
    except ResponseProviderUnavailable:
        response_text = (
            "The workflow outcome is available, but a natural-language response "
            "could not be generated."
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
    return jsonify(result)


if __name__ == "__main__":
    # Use Flask's debug server only for local development.
    app.run(debug=True, port=5000)
