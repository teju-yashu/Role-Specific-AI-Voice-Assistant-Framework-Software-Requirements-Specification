# Role-Specific GenAI Voice Assistant Framework

## Overview
The **Role-Specific GenAI Voice Assistant Framework** is a customizable AI-powered voice and text assistant designed to support organizational roles such as **HR, IT Support, and Admissions**.

This repository currently contains a Flask prototype with deterministic, rule-based query recognition and response generation, plus mock HR, IT Support, and Admissions workflows. The broader GenAI, voice, security, database, and administration capabilities below are project goals; they should not be read as implemented functionality.

## Problem Statement
Organizations handle many repetitive queries and routine workflows manually. Generic assistants may not understand department-specific responsibilities, permissions, and workflows.

This project develops a **role-aware GenAI voice assistant framework** that understands natural-language requests, identifies intent, executes authorized workflows, and responds through voice or text.

## Project Scope and Implementation Status

### Present in this prototype
- Flask `GET /`, `GET /health`, `POST /api/workflows/execute`, and `POST /api/assistant/execute` endpoints.
- Rule-based intent recognition and entity extraction for the three configured workflows.
- Deterministic confidence heuristics, role-specific response instructions, response rendering, and limited rule-based response checks.
- Mock workflow integrations; no real organizational services are called.

### Planned or not currently implemented
- Live LLM-based natural-language understanding or response generation.
- Speech-to-Text, voice input, or Text-to-Speech.
- User authentication, RBAC, MySQL/database integration, conversation history, or administration/analytics dashboard.
- Production organizational APIs and human-agent handoff infrastructure.

### Configured demonstration workflows

**HR Assistant**
- Mock leave-balance lookup

**IT Support Assistant**
- Mock support-ticket creation

**Admissions Assistant**
- Mock application-status lookup

## Target System Architecture

The diagram below describes the broader intended architecture, not the current
implemented end-to-end system.

```text
User (Voice / Text)
        |
        v
Speech Processing (STT)
        |
        v
GenAI / LLM
(Prompt + Context + Intent)
        |
        v
AI Agent
(Tool Selection / Function Calling)
        |
        v
Workflow Automation Engine
        |
   +----+----+
   |         |
   v         v
Org APIs   MySQL
   |
   v
Result Validation
        |
        v
Response Generation + TTS
        |
        v
      User

Low Confidence / Failure
        |
        v
Human Agent Escalation
```

## Technology Stack

The listed stack includes target technologies. The current backend is written
in Python and uses Flask and Flask-Cors; see `requirements.txt` for the
project's declared dependencies.

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python, Flask
- **Database:** MySQL
- **AI:** LLM, Prompt Engineering, AI Agents, Tool Calling
- **Speech:** STT, TTS
- **Integration:** REST APIs, Mock/Sandbox Services
- **Analytics:** Chart.js
- **Tools:** Git, GitHub, VS Code

## Target System Workflow

The following is a target workflow. Voice input, LLM processing, data storage,
and several other stages are not implemented in the current prototype.

1. User logs in.
2. User selects an organizational assistant.
3. User submits a voice or text query.
4. Voice input is converted to text using STT.
5. The LLM analyzes the request using role-specific prompts.
6. Intent and required entities are identified.
7. The AI agent determines whether a tool/workflow is required.
8. An authorized workflow is executed.
9. The result is validated.
10. The LLM generates a natural-language response.
11. The response is displayed and/or converted to speech.
12. Unsupported or low-confidence requests are escalated.
13. Interaction data is stored for history and analytics.

## GenAI & Prompt Engineering Module

The current implementation provides deterministic, rule-based behavior for
Yashas's GenAI & Prompt Engineering module responsibilities:

- Role-specific system prompts for HR, IT Support, and Admissions.
- Role-specific intent recognition limited to the configured workflows.
- Extraction of labeled employee/application IDs and the IT issue description.
- Heuristic confidence scores, passed to the existing workflow agent for its
  configured confidence threshold and escalation handling.
- Clarification questions based on the workflow agent's missing-entity result.
- Natural-language response rendering from actual workflow results, with no
  invented IDs, statuses, balances, or integration outcomes.
- Deterministic relevance checks for role, intent, required facts, and outcome
  consistency. If a generated response fails, the API replaces it with a
  deterministic safe response and reports that replacement.
  The evaluation score is the fraction of deterministic checks passed, from
  `0.0` to `1.0`.

The phrase matching and confidence values are deterministic heuristics; they
are not produced by a trained model and are not calibrated probabilities.
Response relevance evaluation is also an explainable rule-based check, not an
ML evaluator.

No real LLM provider, SDK, endpoint, or credentials are configured. The
response provider abstraction defaults explicitly to a deterministic provider
(`response_source: "deterministic"`). A provider passed to the abstraction is
not automatically assumed to be a real LLM. A live provider requires a
separately reviewed implementation and configuration; requests fail safely
when an explicitly selected provider is unavailable rather than silently
switching providers. Unit tests require neither credentials nor network access.

### Natural-Language Assistant API

`POST /api/assistant/execute` accepts:

```json
{
  "selected_role": "HR",
  "query": "Check my leave balance for employee ID EMP-42."
}
```

The endpoint recognizes the request, prepares the existing workflow API
contract (`selected_role`, `intent`, `entities`, `confidence`), and dispatches
through the shared workflow agent. It adds `response`, `response_source`, and
`response_generation_status`, and `response_evaluation` to the workflow
result. If response generation is unavailable after a workflow completes, the
endpoint still returns HTTP 200 and preserves the workflow `status`; the
separate `response_generation_status` is `"unavailable"` so clients do not
mistake a completed workflow for a failed/retryable operation. Missing
workflow entities also produce a `clarification_question`; uncertain requests
preserve the workflow agent's escalation result. An unsupported request
returns `status: "unknown_intent"` without executing a workflow.
The response evaluator also applies narrow deterministic checks for known
unsupported claims, such as asserting leave approval from a balance-only
result. These checks are specific to configured workflows and are not a
general-purpose hallucination detector.

Example successful response fields:

```json
{
  "status": "success",
  "role": "HR",
  "intent": "check_leave_balance",
  "data": {
    "employee_id": "EMP-42",
    "leave_balance_days": 12,
    "source": "mock"
  },
  "response": "Your leave balance for employee EMP-42 is 12 days.",
  "response_source": "deterministic",
  "response_evaluation": {
    "relevant": true,
    "score": 1.0,
    "reason": "Response passed all deterministic relevance checks.",
    "checks": {
      "non_empty": true,
      "role_consistent": true,
      "outcome_consistent": true,
      "intent_relevant": true,
      "workflow_facts_supported": true
    },
    "method": "deterministic_rule_checks"
  }
}
```

The existing `POST /api/workflows/execute` contract remains unchanged. This
module does not implement voice/STT/TTS, authentication, RBAC, database
integration, or workflow execution itself.

Run the test suite from the repository's configured Python environment with:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m pytest -q
```

## Example

### IT Support Assistant

**User:**  
"My system is unable to connect to the office network."

```text
Speech -> Text
    |
Intent Detection
    |
IT Support Prompt
    |
AI Agent
    |
Troubleshooting Workflow
    |
Result
    |
Natural Language Response
    |
Voice + Text Response
```

## Project Structure

```text
role-specific-genai-voice-assistant/
|
+-- app/
|   +-- routes/
|   +-- models/
|   +-- services/
|   +-- agents/
|   +-- prompts/
|   +-- workflows/
|   +-- integrations/
|   +-- utils/
|
+-- static/
|   +-- css/
|   +-- js/
|   +-- images/
|
+-- templates/
+-- tests/
+-- config/
+-- requirements.txt
+-- .env.example
+-- run.py
+-- README.md
```

> The structure may change as implementation progresses.

## Core Modules

| Module | Description |
|---|---|
| Authentication | Registration and login |
| Role Management | Role-specific assistant selection/configuration |
| Voice Processing | STT and TTS |
| GenAI Engine | LLM understanding and response generation |
| Prompt Engine | Role-specific prompts |
| AI Agent | Tool selection and workflow execution |
| Workflow Engine | Organizational task automation |
| Integration Layer | API and service integration |
| Conversation Manager | Context and history |
| Escalation System | Human-agent transfer |
| Admin Dashboard | Configuration and monitoring |
| Analytics | Usage and workflow statistics |
| RBAC | Access control |

## Security Considerations

- Authentication
- Role-Based Access Control
- Authorized tool/function access
- Secure password storage
- HTTPS support
- Audit logging
- Personal-data protection
- Controlled API access
- Human escalation for uncertain requests

> **Note:** This is an academic prototype and is not intended for production deployment without additional security, scalability, compliance, and reliability testing.

## AI Evaluation Metrics

- Intent Recognition Accuracy
- Entity Extraction Accuracy
- Workflow Success Rate
- Response Relevance
- Escalation Rate
- Response Latency
- Speech Recognition Accuracy
- Tool-Calling Accuracy
- Task Completion Rate

## Future Enhancements

- Multi-language voice support
- More organizational roles
- Real-time organizational API integrations
- Improved AI evaluation and monitoring
- Multi-agent collaboration
- Mobile application
- Enterprise-scale deployment
- Advanced security and compliance
- Continuous learning and feedback

## Academic Context

**Project:** Role-Specific GenAI Voice Assistant Framework  
**Course:** Software Engineering  
**Project Type:** Mini Project  
**Domain:** Generative AI / AI Agents / Voice AI / Software Engineering

## Team

| Member | Role |
|---|---|
| Yashas V | GenAI & Prompt Engineering |
| Sri Kanth G | Voice & Conversation System |
| Varun Kumar H L | AI Agent & Workflow Automation |
| Tejaswi Ganapati Hegde | Backend & Software Engineering |

## Project Goal

Build a **reusable role-specific GenAI assistant framework** that combines conversational AI, voice interaction, AI agents, and workflow automation to simplify routine organizational tasks while maintaining role-based access and human escalation.

## Highlights

```text
GenAI + Prompt Engineering
        +
Voice AI
        +
AI Agents
        +
Tool Calling
        +
Workflow Automation
        +
Role-Based Access
        +
Human Escalation
```

This makes the system more than a basic chatbot by allowing it to **understand requests, select authorized actions, execute workflows, and respond naturally**.
