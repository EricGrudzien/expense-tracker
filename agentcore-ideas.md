# AgentCore Integration Ideas — Expense Tracker

Brainstorm of features and changes that leverage Amazon Bedrock AgentCore services
to upgrade the expense tracker's chat and agent capabilities.

---

## 1. AgentCore Runtime — Deploy the chat agent as a managed endpoint

Right now the chat logic lives inside Flask (`chat_via_flow` / `chat_via_model`).
We could extract the agent into a standalone Strands Agents app, deploy it on
AgentCore Runtime, and have Flask call the endpoint. We'd get serverless scaling,
session isolation per user, and no more managing the Bedrock client lifecycle in
Flask. The expense tracker backend becomes a thin API layer over SQLite, and the
AI brain runs separately.

**What changes:**
- Extract chat logic into a Strands Agents app with an `@app.entrypoint`
- Deploy via `agentcore launch`
- Flask `/api/chat` becomes a proxy to the AgentCore Runtime endpoint
- Remove `boto3` Bedrock client management from `app.py`

**Value:** Serverless scaling, session isolation, cleaner separation of concerns.

---

## 2. AgentCore Memory — Multi-turn chat with session persistence

The chat is currently single-turn (each message is independent, no history sent).
AgentCore Memory gives you short-term memory (conversation context within a session)
and long-term memory (semantic facts across sessions). The agent could remember
"last time you asked about airline costs, the total was $1,200" or "you usually
care about Q1 vs Q2 comparisons."

**What changes:**
- Create a memory store with `MemoryClient`
- Store each chat exchange via `create_event`
- Load recent turns via `list_events` before each agent invocation
- Optionally add a semantic memory strategy for long-term fact extraction

**Value:** Most user-visible upgrade. Enables follow-up questions, context
continuity, and personalized responses.

---

## 3. AgentCore Code Interpreter — Replace the code-executor Lambda

We already have a `bedrock-flow-code-executor` Lambda that runs LLM-generated
Python in a sandboxed subprocess. AgentCore Code Interpreter is purpose-built for
exactly this — isolated execution environments for agent-generated code, with no
container management on our side. We could swap the Lambda for Code Interpreter
calls and get better sandboxing, larger execution limits, and pre-installed data
science libraries.

**What changes:**
- Replace `lambda/code-executor` Lambda invocations with Code Interpreter SDK calls
- Remove the custom security scanning (`BLOCKED_PATTERNS`) — Code Interpreter
  handles isolation
- Potentially retire the code-executor Lambda and its Dockerfile

**Value:** Better sandboxing, no container management, pre-installed libraries
(pandas, matplotlib, numpy), larger execution limits.

---

## 4. AgentCore Gateway — Expose queries as MCP tools

Instead of the agent generating raw SQL that Flask validates and executes, we could
wrap our query patterns (get expenses by category, get report totals, date-range
filters) as Lambda-backed tools behind AgentCore Gateway. The agent would discover
and call these tools via MCP rather than generating freeform SQL.

**What changes:**
- Define structured tools: `get_expenses_by_category`, `get_report_totals`,
  `get_date_range_summary`, `get_category_breakdown`, etc.
- Back each tool with a Lambda or API endpoint
- Register tools in AgentCore Gateway with OpenAPI specs
- Agent calls tools via MCP instead of generating SQL
- Remove SQL generation prompts, `validate_sql()`, and raw DB execution from
  the chat path

**Value:** Safer (no SQL injection surface), more reliable (structured tool calls
vs hoping the LLM writes valid SQL), easier to extend with new query capabilities
without changing prompts. Most architecturally interesting change.

---

## 5. AgentCore Identity — Add user-scoped access

The app currently has no auth. AgentCore Identity could handle OAuth flows (Google,
Okta, etc.) and scope the agent's actions per user. The agent would operate on
behalf of the authenticated user, and we'd get token management for free.

**What changes:**
- Set up an identity client and workload identity for the agent
- Configure OAuth credential providers (Google, Okta, Cognito, etc.)
- Add `@requires_access_token` decorators to tools that need user context
- Scope expense data queries to the authenticated user
- Add a login flow to the frontend

**Value:** Multi-user support, proper access controls, production-realistic
security posture. Bigger lift but makes the app deployable for real use.

---

## 6. AgentCore Observability — Trace and debug agent behavior

We're currently logging to `chat.log` with a custom logger. AgentCore
Observability gives OpenTelemetry-based tracing with step-by-step visualization
of agent execution, token usage metrics, latency breakdowns, and error tracking —
all in CloudWatch dashboards.

**What changes:**
- Enable observability in the AgentCore agent configuration
- Set up Transaction Search in CloudWatch (`xray update-trace-segment-destination`)
- Replace custom `chat_logger` calls with structured OpenTelemetry spans
- Use built-in dashboards for session count, latency, token usage, error rates

**Value:** Production-grade monitoring, faster debugging, visibility into agent
reasoning steps. Replaces the manual `chat.log` approach.

---

## 7. AgentCore Browser — Web-based expense import

A stretch idea: use AgentCore Browser to let the agent navigate to a bank or
credit card portal, scrape transaction data, and auto-populate expense reports.
The agent would autonomously browse a web interface to pull in real expense data.

**What changes:**
- Add AgentCore Browser tool to the agent
- Build a "import expenses" flow that navigates to a configured URL
- Parse transaction tables and create expense reports via the existing API
- Add a chat command like "import my latest transactions from Chase"

**Value:** Automated data entry, impressive demo capability. Most ambitious idea
on this list.

---

## Recommended Starting Point

The sweet spot for a demo-worthy project is **1 + 2 + 3**:

1. **Runtime** — Deploy the agent as a managed endpoint
2. **Memory** — Add multi-turn conversation with session persistence
3. **Code Interpreter** — Swap the code-executor Lambda for managed execution

This gives a clear before/after story with visible user impact.

**4 (Gateway as MCP tools)** is the most architecturally interesting change since
it shifts from "LLM generates SQL" to "LLM calls structured tools" — worth
pursuing as a follow-up.
