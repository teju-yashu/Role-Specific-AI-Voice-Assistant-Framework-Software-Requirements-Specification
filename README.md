# Role-Specific GenAI Voice Assistant Framework

## Overview
The **Role-Specific GenAI Voice Assistant Framework** is a customizable AI-powered voice and text assistant designed to support organizational roles such as **HR, IT Support, and Admissions**.

It combines **Generative AI, LLMs, prompt engineering, speech processing, AI agents, tool calling, and workflow automation** to understand user requests, execute authorized workflows, and provide context-aware responses.

## Problem Statement
Organizations handle many repetitive queries and routine workflows manually. Generic assistants may not understand department-specific responsibilities, permissions, and workflows.

This project develops a **role-aware GenAI voice assistant framework** that understands natural-language requests, identifies intent, executes authorized workflows, and responds through voice or text.

## Key Features

### Generative AI & LLM
- LLM-based natural-language understanding
- Context-aware conversations
- Role-specific prompt engineering
- Intent and entity extraction
- Natural-language response generation

### Voice Interaction
- Speech-to-Text (STT)
- Voice-based queries
- Text-to-Speech (TTS)
- Voice and text responses

### AI Agent & Tool Calling
- AI agent for action selection
- Function/tool calling
- Authorized API integration
- Automated workflow execution
- Result validation

### Role-Specific Assistants

**HR Assistant**
- Leave-related queries
- HR policy assistance
- Employee information
- Routine HR workflows

**IT Support Assistant**
- IT issue reporting
- Troubleshooting assistance
- Ticket-related workflows
- Support escalation

**Admissions Assistant**
- Admission-related queries
- Application information
- Process guidance
- Admission workflows

### Security & Access Control
- User authentication
- Role-Based Access Control (RBAC)
- Authorized tool access
- Secure password handling
- Audit logging
- Data privacy

### Administration & Analytics
- Role profile configuration
- Workflow configuration
- Integration management
- Conversation history
- Escalation tracking
- Dashboard and analytics
- Reports

### Human-Agent Escalation
Unsupported or low-confidence requests can be escalated to a human agent.

## System Architecture

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

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python, Flask
- **Database:** MySQL
- **AI:** LLM, Prompt Engineering, AI Agents, Tool Calling
- **Speech:** STT, TTS
- **Integration:** REST APIs, Mock/Sandbox Services
- **Analytics:** Chart.js
- **Tools:** Git, GitHub, VS Code

## System Workflow

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
