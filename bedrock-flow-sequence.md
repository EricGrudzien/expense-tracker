# Bedrock Flow Chat — Sequence Diagram

This document describes how the chat feature works when routed through the Bedrock Flow
(`USE_BEDROCK_FLOW=true`). It covers both the **text/data** path and the **chart** path.

---

## ASCII Sequence Diagram

```
User types a question in the chat UI (e.g. "Show spending by category" or "Show me a bar chart")

┌────────┐     ┌─────────┐     ┌──────────────────┐     ┌──────────────────────────────────────────────────────────────────────────┐
│Frontend│     │ Flask   │     │ Bedrock Agent     │     │                    Bedrock Flow (FNO4NHO5DT)                             │
│chat.js │     │ app.py  │     │ Runtime           │     │                                                                          │
└───┬────┘     └────┬────┘     └────────┬──────────┘     └──────────────────────────────────────────────────────────────────────────┘
    │               │                   │
    │ POST /api/chat│                   │
    │ {message}     │                   │
    │──────────────>│                   │
    │               │                   │
    │               │  Build system_prompt (DB schema + live categories + date)
    │               │  Combine: <system_prompt>...<user_message>...
    │               │                   │
    │               │  invoke_flow()    │
    │               │──────────────────>│
    │               │                   │
    │               │                   │     ┌──────────────────────────────────────────────────────────────────┐
    │               │                   │     │                  INSIDE THE FLOW                                │
    │               │                   │     │                                                                  │
    │               │                   │     │  ┌──────────────┐                                                │
    │               │                   │     │  │FlowInputNode │ receives combined system_prompt + user_message │
    │               │                   │     │  └──────┬───────┘                                                │
    │               │                   │     │         │                                                        │
    │               │                   │     │         │ (fans out to 3 nodes)                                  │
    │               │                   │     │         │                                                        │
    │               │                   │     │         ├──────────────────────────────────────────────┐          │
    │               │                   │     │         │                                              │          │
    │               │                   │     │         ▼                                              │          │
    │               │                   │     │  ┌──────────────┐                                      │          │
    │               │                   │     │  │Classification│ (Nova Lite)                          │          │
    │               │                   │     │  │ Prompt Node  │                                      │          │
    │               │                   │     │  │              │ → {"classification":"CHART_REQUEST"   │          │
    │               │                   │     │  │              │    or "DATA_LOOKUP", "prompt":"..."}  │          │
    │               │                   │     │  └──────┬───────┘                                      │          │
    │               │                   │     │         │                                              │          │
    │               │                   │     │         ▼                                              │          │
    │               │                   │     │  ┌──────────────────┐                                  │          │
    │               │                   │     │  │ JSON Parser      │ (Lambda: bedrock-flow-json-parser)│         │
    │               │                   │     │  │                  │ Strips code fences, parses JSON   │         │
    │               │                   │     │  └──────┬───────────┘                                  │          │
    │               │                   │     │         │                                              │          │
    │               │                   │     │         ▼                                              │          │
    │               │                   │     │  ┌──────────────────┐                                  │          │
    │               │                   │     │  │ ConditionNode    │                                  │          │
    │               │                   │     │  │                  │                                  │          │
    │               │                   │     │  │ classification   │                                  │          │
    │               │                   │     │  │ =="CHART_REQUEST"│                                  │          │
    │               │                   │     │  └──┬───────────┬──┘                                  │          │
    │               │                   │     │     │           │                                      │          │
    │               │                   │     │     │YES        │NO (default)                          │          │
    │               │                   │     │     ▼           ▼                                      │          │
    │               │                   │     │                                                        │          │
    │               │                   │     │  ═══════════════════════════════════════════════════    │          │
    │               │                   │     │  ║  CHART PATH                 DATA PATH           ║   │          │
    │               │                   │     │  ═══════════════════════════════════════════════════    │          │
    │               │                   │     │                                                        │          │
    │               │                   │     │  ┌──────────────┐      ┌──────────────┐    ◄───────────┘          │
    │               │                   │     │  │ Prompt_Chart │      │ Prompt_Data  │  (receives original       │
    │               │                   │     │  │ (Claude 4.6) │      │ (Claude 4.6) │   input directly from     │
    │               │                   │     │  │              │      │              │   FlowInputNode)          │
    │               │                   │     │  │ Generates:   │      │ Generates:   │                           │
    │               │                   │     │  │ {chartType,  │      │ SELECT ...   │                           │
    │               │                   │     │  │  title,      │      │ (raw SQL)    │                           │
    │               │                   │     │  │  labelField, │      │              │                           │
    │               │                   │     │  │  valueField, │      │              │                           │
    │               │                   │     │  │  sql}        │      │              │                           │
    │               │                   │     │  └──────┬───────┘      └──────┬───────┘                           │
    │               │                   │     │         │                     │                                    │
    │               │                   │     │         ▼                     ▼                                    │
    │               │                   │     │  ┌──────────────────┐  ┌──────────────────┐                       │
    │               │                   │     │  │InlineCode_       │  │InlineCode_       │                       │
    │               │                   │     │  │Transform_Chart   │  │Transform_Data    │                       │
    │               │                   │     │  │                  │  │                  │                       │
    │               │                   │     │  │ Strips fences,   │  │ Strips fences,   │                       │
    │               │                   │     │  │ parses JSON,     │  │ returns:         │                       │
    │               │                   │     │  │ adds type="chart"│  │ {response: sql,  │                       │
    │               │                   │     │  │                  │  │  type:"sql_query"}│                       │
    │               │                   │     │  └──────┬───────────┘  └──────┬───────────┘                       │
    │               │                   │     │         │                     │                                    │
    │               │                   │     │         ▼                     ▼                                    │
    │               │                   │     │  ┌──────────────┐      ┌──────────────┐                           │
    │               │                   │     │  │FlowOutput_   │      │FlowOutput_   │                           │
    │               │                   │     │  │Chart         │      │Data          │                           │
    │               │                   │     │  └──────────────┘      └──────────────┘                           │
    │               │                   │     │                                                                    │
    │               │                   │     └────────────────────────────────────────────────────────────────────┘
    │               │                   │
    │               │  Stream response  │
    │               │<──────────────────│
    │               │  (trace events +  │
    │               │   output document)│
    │               │                   │
    │               │                   │
    │               │  ┌────────────────────────────────────────────────────────────────┐
    │               │  │ BACKEND ROUTING (chat_via_flow)                                │
    │               │  │                                                                │
    │               │  │ Parse flow output → check "type" field                         │
    │               │  │                                                                │
    │               │  │ ┌─────────────────────────────────────────────────────────────┐│
    │               │  │ │ IF type == "sql_query"                                      ││
    │               │  │ │                                                             ││
    │               │  │ │  1. validate_sql(sql)  — must be SELECT only                ││
    │               │  │ │  2. Execute SQL against expenses.db (read-only, 5s timeout) ││
    │               │  │ │  3. call_bedrock() — 2nd call to format answer              ││
    │               │  │ │     (Claude Sonnet 4.5, temp=0)                             ││
    │               │  │ │  4. Return {answer, sql, data}                              ││
    │               │  │ └─────────────────────────────────────────────────────────────┘│
    │               │  │                                                                │
    │               │  │ ┌─────────────────────────────────────────────────────────────┐│
    │               │  │ │ IF type == "chart"                                          ││
    │               │  │ │                                                             ││
    │               │  │ │  1. validate_sql(sql from chart instruction)                ││
    │               │  │ │  2. Execute SQL against expenses.db                         ││
    │               │  │ │  3. Invoke egru-chart-builder Lambda                        ││
    │               │  │ │     (sends chartType, title, labelField, valueField, data)  ││
    │               │  │ │  4. Lambda returns Chart.js config (deterministic, no LLM)  ││
    │               │  │ │  5. Return {answer, chart, sql, data}                       ││
    │               │  │ └─────────────────────────────────────────────────────────────┘│
    │               │  │                                                                │
    │               │  │ ┌─────────────────────────────────────────────────────────────┐│
    │               │  │ │ ELSE (type == "text" or other)                              ││
    │               │  │ │                                                             ││
    │               │  │ │  Return {answer, sql: null, data: null}                     ││
    │               │  │ └─────────────────────────────────────────────────────────────┘│
    │               │  └────────────────────────────────────────────────────────────────┘
    │               │
    │  JSON response│
    │<──────────────│
    │               │
    │  ┌────────────────────────────────────────────────────────┐
    │  │ FRONTEND RENDERING (chat.js)                           │
    │  │                                                        │
    │  │ addAssistantBubble(answer, sql, chart)                 │
    │  │                                                        │
    │  │  • Always: render answer text                          │
    │  │  • If chart config: create <canvas>, call new Chart()  │
    │  │  • If sql: add "▸ Show SQL" toggle with code block     │
    │  └────────────────────────────────────────────────────────┘
    │
    ▼
  User sees answer (+ optional chart + optional SQL toggle)
```

---

## Key Points

- The **Classification** node (Nova Lite, cheap/fast) decides the routing — `CHART_REQUEST` vs everything else.
- The **JSON Parser Lambda** sits between classification and the condition node to clean up LLM output into a proper object the condition node can evaluate.
- Both paths receive the **original input directly** from FlowInputNode (not the classification output) — the condition node only gates which path activates.
- **Prompt_Chart** generates a structured JSON instruction (chartType, title, fields, SQL). **Prompt_Data** generates raw SQL.
- The **InlineCode transform nodes** normalize both outputs — stripping code fences and tagging with `type: "chart"` or `type: "sql_query"`.
- Back in Flask, the `type` field determines the post-processing: data queries get a second Bedrock call to format a human-readable answer, while chart queries go through the **egru-chart-builder Lambda** (pure deterministic logic, no LLM) to produce a Chart.js config.
- The frontend renders charts client-side with `new Chart(canvas, config)` from Chart.js v4.

---

## Key Design Points

### Classification (routing)
- **Model:** Amazon Nova Lite (cheap, fast — classification only)
- **Output:** `{"classification": "CHART_REQUEST" | "DATA_LOOKUP" | ...}`
- The JSON Parser Lambda cleans LLM output (strips code fences) so the Condition node
  can evaluate `classification == "CHART_REQUEST"` via JSONPath

### Data path (type: "sql_query")
- **Prompt_Data** (Claude Sonnet 4.6) receives the full system prompt + user message
  and generates a raw SQL SELECT query
- **InlineCode_Transform_Data** strips code fences, wraps in `{response: sql, type: "sql_query"}`
- Back in Flask: SQL is validated (SELECT-only), executed against `expenses.db`,
  then a **second Bedrock call** (Claude Sonnet 4.5, temp=0) formats a human-readable answer

### Chart path (type: "chart")
- **Prompt_Chart** (Claude Sonnet 4.6) generates a JSON instruction:
  `{chartType, title, labelField, valueField, sql}`
- **InlineCode_Transform_Chart** strips code fences, parses JSON, adds `type: "chart"`
- Back in Flask: SQL is validated and executed, then the **egru-chart-builder Lambda**
  (deterministic, no LLM) converts the instruction + data into a Chart.js v4 config
- Supported chart types: `bar`, `line`, `pie`, `doughnut`

### Frontend rendering
- `chat.js` calls `addAssistantBubble(answer, sql, chart)`
- Text answer is always rendered
- If `chart` is present: a `<canvas>` is created and `new Chart(canvas, config)` renders it
- If `sql` is present: a collapsible "Show SQL" toggle reveals the query

### Flow fan-out pattern
- FlowInputNode sends the original input to **three** downstream nodes simultaneously:
  Classification, Prompt_Data, and Prompt_Chart
- The Condition node gates which prompt path actually produces output
- This means both prompt nodes receive input, but only the active path's output
  reaches a FlowOutput node

### Models used
| Node            | Model                  | Purpose                    |
|-----------------|------------------------|----------------------------|
| Classification  | Amazon Nova Lite       | Fast routing decision      |
| Prompt_Data     | Claude Sonnet 4.6      | SQL generation             |
| Prompt_Chart    | Claude Sonnet 4.6      | Chart instruction JSON     |
| Format answer   | Claude Sonnet 4.5      | Human-readable answer (2nd call, backend only) |

### AWS Resources
- **Flow ID:** FNO4NHO5DT, **Alias:** TSTALIASID
- **Lambdas:** `bedrock-flow-json-parser`, `egru-chart-builder`
- **Region:** us-east-1, **Account:** 905418197933
