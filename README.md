# Role-Specific AI Voice Assistant Framework

A prototype Flask application that provides role-specific HR, IT Support, and Admissions assistants. It combines optional OpenAI language-model capabilities with the project's existing intent validation and registered Python workflows. When OpenAI is disabled or unavailable, the application continues in rule-based mode.

The project uses demonstration integrations and data. It is not connected to a real organization's HR, IT, or admissions systems and is not production-ready.

## Project objectives and problem statement

The project demonstrates how one authenticated assistant interface can route requests according to an authorized assistant role, retain conversation history, ask for missing workflow information, and escalate requests to a human agent. Natural-language understanding should make the interaction more flexible, while validated application code—not the language model—remains responsible for business operations.

## Key features

- User registration, login, logout, role-based access, and CSRF protection.
- Separate HR, IT Support, and Admissions assistant experiences.
- Optional OpenAI interpretation and response generation through the Responses API.
- Rule-based NLU and registered workflows when OpenAI is disabled or unavailable.
- Clarification prompts, conversation history, resume, and conversation ownership checks.
- Demonstration HR, IT, and Admissions integrations.
- Agent escalation queue and admin assistant-role activation controls.
- Browser-provided speech recognition and speech playback where supported.
- SQLite persistence and automated Python and JavaScript tests.

## Supported roles

| Assistant | Demonstration capabilities |
| --- | --- |
| HR Assistant | Leave-balance lookup and HR-related questions. The sample lookup may ask for an employee ID. |
| IT Support Assistant | Create a sample IT ticket, respond to technical questions, and escalate requests that need an agent. |
| Admissions Assistant | Look up a sample application status and answer admissions-related questions. The sample lookup may ask for an application ID. |

These are role-specific application experiences, not separate real-world departments or connected enterprise systems.

## Technology stack

- Python and Flask
- SQLite for accounts, conversations, workflow events, and escalations
- Official OpenAI Python SDK and OpenAI Responses API (optional)
- HTML, CSS, and browser JavaScript
- Browser Web Speech APIs for speech input/output when available
- `pytest` and Node's built-in `node:test` for automated tests

## Architecture and request flow

For an authenticated chat request, the application checks the session and CSRF token, validates the selected assistant, and loads only the current user's conversation. When enabled, the language model can interpret the message and generate natural-language explanations. The application validates any suggested intent against its existing NLU and registered workflow definitions before the workflow agent is allowed to execute it. The registered workflow calls the configured integration, which currently returns demonstration data. A response can then be generated from the verified result and stored with the conversation.

In rule-based mode—or when an OpenAI call cannot be completed—the existing NLU, clarification handling, workflow agent, and response generation remain available. A model suggestion alone cannot authorize an operation or bypass workflow validation and access controls.

## OpenAI and hybrid architecture

- OpenAI is optional and is called only from the Flask server. The API key is never sent to browser JavaScript.
- The OpenAI client uses the Responses API. Set `OPENAI_MODEL` to a model available to your OpenAI API account; the application does not assume a particular model is enabled for every account.
- The model can interpret natural-language requests and explain verified workflow results. The deterministic NLU, intent allowlist, role checks, argument validation, registered workflow agent, and integrations govern business operations.
- Unsupported, malformed, or uncertain model interpretations do not authorize a workflow. Depending on the request, the application can fall back to existing NLU or ask for clarification.
- OpenAI outages, timeouts, rate limits, invalid credentials, and other API failures leave the rule-based assistant available. The chat UI indicates whether OpenAI or fallback mode is active.
- Context is bounded to recent messages from the same user's conversation and includes the selected role and applicable clarification/result information. Do not put sensitive personal information in a prompt.
- HR, IT, and Admissions results are currently from mock integrations. They are demonstration/sample data, not organizational records.
- Automated LLM tests mock OpenAI responses. They do not prove that a live API request, account, or configured model works.

OpenAI API usage is billed separately from a ChatGPT subscription. A typical LLM-enabled turn may make separate interpretation and response-generation requests; usage and cost depend on the configured model and conversation. Consult [OpenAI API pricing](https://openai.com/api/pricing/) and monitor your API account.

## Repository structure

```text
.
├── app/
│   ├── agents/workflow_agent.py
│   ├── integrations/mock_integrations.py
│   ├── llm/openai_client.py
│   ├── nlu/
│   │   ├── assistant_nlu.py
│   │   ├── response_evaluator.py
│   │   ├── response_generator.py
│   │   └── role_prompts.py
│   ├── workflows/registry.py
│   ├── authentication.py
│   └── storage.py
├── static/
│   ├── css/style.css
│   └── js/
│       ├── auth.js
│       ├── chat.js
│       └── portal.js
├── templates/
│   ├── admin.html
│   ├── agent.html
│   ├── auth.html
│   └── index.html
├── tests/
│   ├── frontend/chat.test.js
│   └── ... Python tests
├── .env.example
├── .gitignore
├── requirements.txt
└── run.py
```

The repository also contains project requirements/specification PDFs at its root. There is no `LICENSE` file in the repository.

## System requirements and prerequisites

- Python 3.10 or later (use a version supported by the installed Flask and OpenAI SDK dependencies).
- Node.js 18 or later to run the frontend tests; Node.js is not required to run the Flask application.
- A modern browser for the web interface. Microphone and speech features depend on browser support and permissions.
- An OpenAI API key and a model available to your API account only if you want to enable live OpenAI calls.

## Installation

From a Linux shell, Codespace, or compatible environment:

```bash
git clone https://github.com/teju-yashu/Role-Specific-AI-Voice-Assistant-Framework-Software-Requirements-Specification.git
cd Role-Specific-AI-Voice-Assistant-Framework-Software-Requirements-Specification

python -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
cp .env.example .env
```

Generate a secret locally, then copy its output into `FLASK_SECRET_KEY` in `.env`:

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Do not commit `.env`. The checked-in `.env.example` contains placeholders only.

## Environment configuration

`run.py` loads environment values from `.env`. Set them in that file or in the process environment.

| Variable | Purpose | Local/demo guidance |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | Signs Flask session cookies. The application requires a stable secret of at least 32 characters. | Generate a private random value; do not use a public example or commit it. |
| `SESSION_COOKIE_SECURE` | Marks session cookies as HTTPS-only. | `false` for local plain-HTTP development; use `true` behind HTTPS. |
| `AUTH_DATABASE` | SQLite database path. | Defaults to `instance/user_accounts.sqlite3`; keep runtime database files out of Git. |
| `OPENAI_ENABLED` | Enables optional OpenAI interpretation and response generation. | `false` runs the rule-based assistant and is the `.env.example` default. |
| `OPENAI_API_KEY` | Server-side OpenAI API credential. | Leave blank in fallback mode. Obtain a key through the [OpenAI API platform](https://platform.openai.com/api-keys); never put it in frontend code or source control. |
| `OPENAI_MODEL` | Model name sent to the Responses API. | Required for live LLM use; choose one available to your API account. There is no assumed model default. |
| `OPENAI_TIMEOUT_SECONDS` | Timeout for OpenAI requests. | Defaults to 20 seconds; supported range is 1–120. |
| `FLASK_DEBUG` | Enables Flask debug mode. | Defaults to `false`; use only for local development. |
| `CORS_ALLOWED_ORIGINS` | Optional allowlist for configured cross-origin API access. | Leave unset for the usual same-origin browser setup. |
| `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_PASSWORD` | Optional bootstrap credentials for the admin account. | Configure both before startup if required; bootstrap password must be at least 12 characters. |
| `BOOTSTRAP_AGENT_USERNAME`, `BOOTSTRAP_AGENT_PASSWORD` | Optional bootstrap credentials for an agent account. | Configure both before startup if required; bootstrap password must be at least 12 characters. |

To enable OpenAI, set `OPENAI_ENABLED=true`, provide `OPENAI_API_KEY`, and set `OPENAI_MODEL` to a model available to your account. Restart the application after changing configuration. To run without OpenAI, leave the key/model blank and use `OPENAI_ENABLED=false`.

## Start the application

With the virtual environment activated and `.env` configured:

```bash
python run.py
```

The application listens on port **5000**. Open `http://127.0.0.1:5000` locally. In GitHub Codespaces, use the **Ports** panel to open forwarded port 5000; keep its visibility private unless you intentionally need to share it. The application is a development prototype, not a production deployment server.

## Register and log in

1. Open the application and choose the registration link.
2. Register a normal account with a username and password. Normal registration does not grant agent or admin privileges.
3. Log in with that account to use the chat interface.
4. To demonstrate staff views, configure bootstrap agent/admin credentials in `.env` before startup, then sign in with those accounts. The admin can also use the agent queue.

Do not reuse real credentials for a demonstration. Bootstrap credentials should be private and changed or removed when no longer needed.

## Use the chat interface

Choose HR Assistant, IT Support Assistant, or Admissions Assistant from the role selector, then enter a message or use voice input if available. The interface displays conversation history, supports resuming an existing conversation, and shows whether it is using OpenAI or rule-based fallback mode. Follow clarification prompts with the requested employee or application identifier. A role must be active in the admin controls to be available.

## Demonstration guide

For deterministic walkthroughs and predictable sample results, set `OPENAI_ENABLED=false`. The same registered workflows remain protected when OpenAI is enabled, but natural-language phrasing and conversational responses may vary. No screenshots are included because no project screenshots were supplied.

### Demo A: HR Assistant

1. Register and log in as a normal user.
2. Select **HR Assistant** and ask: `What is my leave balance?`
3. If prompted, provide the employee ID: `EMP-001`.
4. The mock integration returns a balance of **12 days**. This is fixed demonstration data, not a lookup in a real HR system.

### Demo B: IT Support Assistant

1. Select **IT Support Assistant**.
2. To exercise ticket creation, enter: `Please raise a ticket for my email is unavailable.`
3. The mock integration returns ticket **IT-1001** with status **open**. It is a sample ticket, not a record in a real IT service system.
4. A question asking only how to raise a ticket may receive an informational answer when OpenAI is enabled; use the explicit “Please raise a ticket…” request above to demonstrate the registered creation workflow.

### Demo C: Admissions Assistant

1. Select **Admissions Assistant** and ask: `Please check my application status.`
2. If prompted, provide an application ID such as `APP-42`.
3. The mock integration returns **under_review**. This is sample data and is not retrieved from a real admissions system.

### Demo D: Agent dashboard

1. Configure and log in with the bootstrap agent credentials. Admin accounts may also access the agent queue.
2. For a predictable escalation demonstration, use rule-based mode and ask an assistant: `My printer is not working.`
3. Open the agent dashboard. Inspect the pending escalation, accept it, then resolve it with a response.
4. The response is appended to the user's conversation and can be seen when that user returns to the chat. The dashboard operates on prototype escalation records, not an external support queue.

With OpenAI enabled, the model can interpret that wording differently, so the exact escalation path may vary. Rule-based mode is recommended for this scripted demonstration.

### Demo E: Admin dashboard

1. Configure and log in using the bootstrap admin username and password.
2. Open the admin dashboard and use the implemented controls to activate or deactivate the HR, IT Support, and Admissions assistant roles.
3. Return to the user chat and confirm that only active assistant roles are available.

The dashboard does not provide general user/role editing or other unimplemented administrative functions.

### Demo F: Browser voice

1. Open the chat in a browser that supports the Web Speech APIs and grant microphone permission.
2. Use the microphone control to dictate a request. Use the playback control to hear assistant speech where available.
3. Voice recognition depends on browser implementation, operating system, network, and permission settings. The project does not provide its own speech-to-text or text-to-speech service; browser support is not universal. Use typed chat if voice controls are unavailable.

## Agent dashboard

An authenticated agent or admin can open the agent dashboard to inspect escalations, accept pending items, and resolve accepted items with a response. Agents are restricted to their authorized queue; admin access is also supported. Replies are stored with the associated conversation and returned to the user through the conversation history.

## Admin dashboard

An authenticated admin can inspect the prototype dashboard and activate or deactivate the three configured assistant roles. These controls affect role availability in chat. The dashboard does not imply a full identity-management, audit, or enterprise administration system.

## Run automated tests

From the repository root, with dependencies installed:

```bash
python -m pytest -q
node --test tests/frontend/chat.test.js
node --check static/js/chat.js
node --check static/js/portal.js
node --check static/js/auth.js
python -m compileall -q run.py app tests
git diff --check
```

OpenAI-related automated tests mock SDK responses and do not require a key or incur OpenAI API charges. They do not constitute a live API test. A live API check requires your own API key, a model available to your account, and a deliberate request; no live request is claimed by this documentation.

## API endpoints and example requests

The browser uses authenticated session cookies and CSRF protection for state-changing requests. Sign in through the web UI to establish a session and obtain the CSRF token, then send it in the `X-CSRF-Token` header for protected POST requests. Do not expose cookies or CSRF tokens in shared logs or examples.

| Method and path | Purpose | Access |
| --- | --- | --- |
| `GET /` | Application information. | Public |
| `GET /health` | Health response. | Public |
| `GET /login`, `GET /register` | Authentication pages. | Public |
| `POST /api/auth/register` | Register a normal user. | Public page flow; CSRF protected |
| `POST /api/auth/login` | Authenticate and establish a session. | Public page flow; CSRF protected |
| `POST /api/auth/logout` | End the current session. | Authenticated; CSRF protected |
| `POST /api/assistant/execute` | Process a role-specific user message. | Authenticated; CSRF protected |
| `POST /api/workflows/execute` | Execute a supported registered workflow. | Authenticated; CSRF protected |
| `GET /api/conversations` | List the current user's conversations. | Authenticated |
| `GET /api/conversations/<conversation_id>` | Read a conversation owned by the current user. | Authenticated; ownership enforced |
| `GET /api/agent/escalations` | Inspect the authorized escalation queue. | Agent or admin |
| `POST /api/agent/escalations/<id>/accept` | Accept an escalation. | Agent or admin; CSRF protected |
| `POST /api/agent/escalations/<id>/resolve` | Resolve an escalation with a response. | Agent or admin; CSRF protected |
| `GET /api/admin/dashboard` | Read admin dashboard data. | Admin |
| `POST /api/admin/roles/<role>/active` | Activate or deactivate a configured assistant role. | Admin; CSRF protected |

Example assistant request body:

```json
{
  "selected_role": "HR",
  "query": "What is my leave balance?",
  "conversation_id": null
}
```

`conversation_id` is optional; omit it to start a conversation. Role values and accepted workflow fields are validated by the application. A successful response includes the assistant message and conversation information; response fields also report workflow/LLM status as appropriate. Do not treat generated prose as a substitute for the verified workflow result.

Example workflow request body:

```json
{
  "selected_role": "IT Support",
  "intent": "raise_it_support_ticket",
  "confidence": 0.9,
  "entities": {
    "issue_description": "Email is unavailable"
  }
}
```

These bodies illustrate the request format; they are not complete unauthenticated `curl` commands. Requests must include a valid user session and CSRF token as required by the route.

## Database and persistence

SQLite is used for user accounts, configured assistant roles, conversations and messages, workflow activity, and escalations. The default database path is `instance/user_accounts.sqlite3`; override it with `AUTH_DATABASE`. Database tables are initialized by the application. Conversation reads and resumes are scoped to the authenticated user. Back up or remove local prototype data deliberately; database files can contain personal conversation content and must not be committed.

## Security considerations

- Keep `.env`, API keys, passwords, session cookies, CSRF tokens, and SQLite runtime data out of source control.
- The OpenAI key is used only server-side. Do not include secrets or unnecessary personal data in prompts.
- The application checks authentication, CSRF, role permissions, conversation ownership, supported intents, and workflow arguments before business operations.
- A language model does not directly execute arbitrary Python functions or grant permissions.
- For local HTTP development, `SESSION_COOKIE_SECURE=false` is needed for the browser to send the session cookie. Use HTTPS and secure cookies for any hosted environment.
- Use a unique, stable `FLASK_SECRET_KEY`; do not use Flask debug mode or the development server for public production deployment.
- This prototype has not undergone production security or privacy review. It does not replace organization-specific access controls, retention policies, monitoring, or deployment hardening.

## Current limitations and future improvements

- Integrations currently return fixed mock/demo data; no real HR, IT ticketing, or admissions backend is configured.
- OpenAI requires user-supplied API credentials and a model available to that API account. Automated tests are mocked; live account/model access was not verified here.
- Speech features depend on browser Web Speech API support and permissions.
- The application is a prototype. Production use would require deployment hardening, operational monitoring, privacy/retention decisions, and integration-specific authorization and validation.
- Possible future work includes approved organizational integrations, broader browser testing, and production deployment controls.

## Troubleshooting

- **Startup says the Flask secret is missing or invalid:** set `FLASK_SECRET_KEY` in `.env` to a stable, private value of at least 32 characters.
- **The assistant says it is in fallback mode:** check `OPENAI_ENABLED`, `OPENAI_API_KEY`, and `OPENAI_MODEL`; confirm that the key and selected model are available to your OpenAI API account. The application remains usable with fallback mode.
- **OpenAI calls time out or fail:** verify connectivity, API account/model access, key validity, and `OPENAI_TIMEOUT_SECONDS`. Do not paste credentials into issue reports.
- **A protected API request fails with a CSRF error:** reload or sign in through the application so the browser has a current session and token.
- **A page does not load in Codespaces:** confirm the process is running and open forwarded port 5000 from the Ports panel.
- **The browser does not send the local session:** for local plain HTTP, set `SESSION_COOKIE_SECURE=false`; do not disable secure cookies for HTTPS deployments.
- **Microphone or speech playback is unavailable:** check browser compatibility, microphone permissions, and device settings; use the text chat instead.
- **A lookup returns a surprising value:** HR, ticket, and admissions records are fixed mock values, not live organization data.
