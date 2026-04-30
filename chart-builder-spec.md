# Chart Builder — Specification & Implementation Plan

## 1. Purpose

Enable the chat interface to render interactive charts in the browser when a user asks
for a visualization (e.g. "Show me a bar chart of spending by category"). The LLM
generates a simple chart instruction object, a Lambda translates it into a valid
Chart.js configuration, and the frontend renders it in a `<canvas>` element inside
the chat bubble.

---

## 2. Architecture

```
User: "Show me a bar chart of spending by category"
        │
        ▼
Bedrock Flow
        │
        ├─ Classification Node → CHART_REQUEST
        │
        ├─ Prompt_Chart Node (LLM)
        │   ├─ Step 1: Generate SQL to fetch the data
        │   └─ Step 2: Generate a chart instruction object
        │       {
        │         "chartType": "bar",
        │         "title": "Spending by Category",
        │         "labelField": "category",
        │         "valueField": "total",
        │         "sql": "SELECT category, SUM(amount) AS total FROM sub_expenses GROUP BY category"
        │       }
        │
        ├─ Inline Code Node: strip markdown fences, parse JSON
        │
        └─ Flow Output → returns instruction object
        │
        ▼
Backend (chat_via_flow)
        │
        ├─ Detect type == "chart"
        ├─ Execute the SQL locally against expenses.db
        ├─ Call chart-builder Lambda with instruction + query results
        │       {
        │         "chartType": "bar",
        │         "title": "Spending by Category",
        │         "labelField": "category",
        │         "valueField": "total",
        │         "data": [
        │           {"category": "airline", "total": 1200},
        │           {"category": "hotel", "total": 980}
        │         ]
        │       }
        │
        └─ Return to frontend:
           {
             "answer": "Here's your spending by category:",
             "chart": { <valid Chart.js config> },
             "sql": "SELECT ...",
             "data": [...]
           }
        │
        ▼
Frontend (chat.js)
        │
        ├─ Render answer text as bubble
        ├─ Detect "chart" field in response
        ├─ Create <canvas> inside the bubble
        └─ new Chart(canvas, response.chart)
```

---

## 3. Technology Choice: Chart.js

| Attribute | Value |
|---|---|
| Library | Chart.js v4.x |
| Size | ~70KB (CDN) |
| Load method | `<script>` tag from CDN, no build step |
| Config style | Declarative JSON object |
| Chart types needed | bar, line, pie, doughnut |

CDN URL: `https://cdn.jsdelivr.net/npm/chart.js`

---

## 4. Chart Instruction Object (LLM Output)

The LLM generates this simple JSON. It does NOT generate Chart.js syntax.

```json
{
  "chartType": "bar",
  "title": "Spending by Category",
  "labelField": "category",
  "valueField": "total",
  "sql": "SELECT category, SUM(amount) AS total FROM sub_expenses GROUP BY category"
}
```

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `chartType` | string | yes | One of: `bar`, `line`, `pie`, `doughnut` |
| `title` | string | yes | Chart title |
| `labelField` | string | yes | Key in the data rows to use as labels (x-axis or slice names) |
| `valueField` | string | yes | Key in the data rows to use as values (y-axis or slice sizes) |
| `sql` | string | yes | SQL SELECT query to fetch the data |

### What the LLM does NOT need to know
- Chart.js property names or structure
- Color palettes
- Axis formatting
- Responsive settings
- Plugin configuration

---

## 5. Chart Builder Lambda (`lambda/chart-builder/`)

### 5.1 Purpose

Takes a chart instruction object (with data already populated) and returns a valid
Chart.js configuration object. Deterministic — no LLM calls, no randomness.

### 5.2 Input

```json
{
  "chartType": "bar",
  "title": "Spending by Category",
  "labelField": "category",
  "valueField": "total",
  "data": [
    {"category": "Airline", "total": 1200},
    {"category": "Hotel", "total": 980},
    {"category": "Car", "total": 450}
  ]
}
```

### 5.3 Output

```json
{
  "type": "bar",
  "data": {
    "labels": ["Airline", "Hotel", "Car"],
    "datasets": [{
      "label": "Spending by Category",
      "data": [1200, 980, 450],
      "backgroundColor": ["#4f46e5", "#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe",
                           "#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"]
    }]
  },
  "options": {
    "responsive": true,
    "maintainAspectRatio": true,
    "plugins": {
      "title": {
        "display": true,
        "text": "Spending by Category",
        "font": {"size": 16, "weight": "bold"}
      },
      "legend": {"display": false}
    },
    "scales": {
      "y": {
        "beginAtZero": true,
        "ticks": {"prefix": "$"}
      }
    }
  }
}
```

### 5.4 Validation

The Lambda validates the input before building:

| Check | Action on failure |
|---|---|
| `chartType` not in `[bar, line, pie, doughnut]` | Return error |
| `title` missing or empty | Use "Chart" as default |
| `labelField` not a key in `data[0]` | Return error |
| `valueField` not a key in `data[0]` | Return error |
| `data` empty or not a list | Return error |
| Values are not numeric | Return error |

### 5.5 Color palette

A fixed palette matching the app's design system:

```python
PALETTE = [
    "#4f46e5",  # indigo-600
    "#6366f1",  # indigo-500
    "#818cf8",  # indigo-400
    "#a5b4fc",  # indigo-300
    "#7c3aed",  # violet-600
    "#8b5cf6",  # violet-500
    "#a78bfa",  # violet-400
    "#c4b5fd",  # violet-300
    "#2563eb",  # blue-600
    "#3b82f6",  # blue-500
]
```

Colors cycle if there are more data points than palette entries.

### 5.6 Chart type templates

Each chart type has a builder function that produces the correct Chart.js structure:

- **bar** — vertical bars, y-axis with $ prefix, gridlines
- **line** — line with markers, fill under line, y-axis with $ prefix
- **pie** — pie slices, legend on the right, percentage tooltips
- **doughnut** — same as pie but with cutout

### 5.7 Deployment

- **Runtime:** Python 3.12 (zip deployment, no dependencies)
- **Memory:** 128 MB
- **Timeout:** 10 seconds
- **Function name:** `bedrock-flow-chart-builder`

---

## 6. Backend Changes (`backend/app.py`)

### 6.1 New response type in `chat_via_flow`

Add handling for `type == "chart"` in the flow response routing:

```python
if response_type == "chart":
    # Extract SQL from the instruction
    sql = result.get("sql", "").strip()
    # Validate and execute SQL
    # Merge query results into the instruction as "data"
    # Call chart-builder Lambda
    # Return {answer, chart, sql, data}
```

### 6.2 Chart builder Lambda invocation

New helper function `build_chart(instruction, data)`:
1. Merge `data` into the instruction object
2. Invoke `bedrock-flow-chart-builder` Lambda
3. Return the Chart.js config from the Lambda response

### 6.3 Response shape

When a chart is generated, the chat endpoint returns:

```json
{
  "answer": "Here's your spending by category:",
  "chart": { <Chart.js config object> },
  "sql": "SELECT ...",
  "data": [{"category": "airline", "total": 1200}, ...]
}
```

The `chart` field is `null` for non-chart responses (same as today).

---

## 7. Frontend Changes

### 7.1 Add Chart.js library

Add to `chat.html` `<head>`:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### 7.2 Update `chat.js` — render charts in bubbles

When the response contains a `chart` field:
1. Create the answer text bubble as usual
2. Create a `<canvas>` element inside the bubble
3. Call `new Chart(canvas.getContext('2d'), response.chart)`

### 7.3 Chart canvas styling

- Max width: 100% of bubble
- Fixed aspect ratio (Chart.js handles this with `maintainAspectRatio: true`)
- White background
- Rounded corners matching bubble style

### 7.4 Update `chat.css`

Add styles for the chart canvas container inside bubbles.

---

## 8. Bedrock Flow Changes

### 8.1 Update Prompt_Chart node

The current `Prompt_Chart` generates Python code for matplotlib. Change it to generate
a chart instruction JSON object instead.

New prompt template:
```
You are analyzing expense data. The user wants a chart.

Generate a JSON object with these exact fields:
- "chartType": one of "bar", "line", "pie", "doughnut"
- "title": a descriptive chart title
- "labelField": the column name to use for labels
- "valueField": the column name to use for values
- "sql": a SQLite SELECT query to fetch the data

Database schema:
<include DB schema and category list>

Rules:
- Return ONLY the JSON object
- No markdown, no code blocks, no explanation
- Response must start with { and end with }
- The SQL must be a SELECT statement only
- Use SUM, COUNT, GROUP BY as needed for aggregation

User request: {{code_prompt}}
```

### 8.2 Update InlineCode node for chart branch

Add a new inline code node (or update the existing one) on the chart branch to:
1. Strip markdown fences from the LLM output
2. Parse the JSON
3. Return it with `"type": "chart"` so the backend knows how to route it

```python
import re
import json

def __func():
    text = variable
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    parsed = json.loads(cleaned)
    parsed["type"] = "chart"
    return parsed

__func()
```

### 8.3 Flow wiring

The chart branch currently goes:
```
ConditionNode_1 (CHART_REQUEST) → Prompt_Chart → FlowOutput_Chart
```

Change to:
```
ConditionNode_1 (CHART_REQUEST) → Prompt_Chart → InlineCode_Transform_Chart → FlowOutput_Chart
```

---

## 9. Implementation Checklist

### Lambda

- [x] **Step 1**: Create `lambda/chart-builder/lambda_function.py`
  - Input validation
  - Color palette
  - Builder functions for bar, line, pie, doughnut
  - Output: valid Chart.js config JSON

- [x] **Step 2**: Deploy chart-builder Lambda
  - Zip and deploy (no special dependencies)
  - Use existing `bedrock-flow-lambda-role`

- [x] **Step 3**: Test chart-builder Lambda
  - Add tests to `lambda/test_lambdas.py`
  - Test each chart type
  - Test validation (missing fields, invalid chartType)

### Backend

- [x] **Step 4**: Add `build_chart()` helper to `backend/app.py`
  - Invokes chart-builder Lambda with instruction + data
  - Returns Chart.js config

- [x] **Step 5**: Update `chat_via_flow()` to handle `type == "chart"`
  - Extract SQL from instruction
  - Execute SQL locally
  - Call `build_chart()` with instruction + results
  - Return `{answer, chart, sql, data}`

- [x] **Step 6**: Update `chat_via_model()` to support charts (optional)
  - If the direct model path should also support charts
  - Or leave as SQL-only for now

### Frontend

- [x] **Step 7**: Add Chart.js to `chat.html`
  - CDN `<script>` tag

- [x] **Step 8**: Update `chat.js` to render charts
  - Detect `chart` field in response
  - Create `<canvas>` in bubble
  - Instantiate Chart.js with the config

- [x] **Step 9**: Add chart styles to `chat.css`
  - Canvas container sizing
  - Background and border radius

### Bedrock Flow

- [x] **Step 10**: Update `Prompt_Chart` prompt template
  - Change from Python code generation to chart instruction JSON
  - Include DB schema and category list in the prompt

- [x] **Step 11**: Add `InlineCode_Transform_Chart` node
  - Strip fences, parse JSON, add `"type": "chart"`

- [x] **Step 12**: Rewire chart branch connections
  - Prompt_Chart → InlineCode_Transform_Chart → FlowOutput_Chart

- [x] **Step 13**: Update `flow-export.json` and push
  - `python lambda/update_flow.py`

### Testing

- [x] **Step 14**: End-to-end test
  - "Show me a bar chart of spending by category"
  - "Create a pie chart of expenses by report"
  - "Line chart of monthly spending"
  - Verify chart renders in chat bubble
  - Verify SQL toggle still works alongside chart

### Documentation

- [x] **Step 15**: Update `bedrock-flows-spec.md`
  - Add chart-builder Lambda section
  - Update flow architecture diagram
  - Document chart response type

- [x] **Step 16**: Update `expense-tracker.md` steering doc
  - Add Chart.js to technology stack
  - Document chart rendering in chat page section

---

## 10. File Changes Summary

| File | Change |
|---|---|
| `lambda/chart-builder/lambda_function.py` | New — chart config factory |
| `lambda/chart-builder/deploy.sh` | New — deployment script |
| `lambda/test_lambdas.py` | Add chart-builder tests |
| `backend/app.py` | Add `build_chart()`, update `chat_via_flow()` for chart type |
| `frontend/chat.html` | Add Chart.js CDN script tag |
| `frontend/chat.js` | Render charts in bubbles |
| `frontend/chat.css` | Chart canvas styles |
| `lambda/flow-export.json` | Updated flow with new prompt + inline code node |
| `lambda/prompts/chart-instruction.txt` | New — prompt template for chart instructions |
| `bedrock-flows-spec.md` | Updated documentation |
| `.kiro/steering/expense-tracker.md` | Updated documentation |

---

## 11. Future Enhancements

- **Multi-dataset charts**: Support multiple `valueField` entries for grouped/stacked bars
- **Date-axis charts**: Auto-detect date fields and format x-axis as timeline
- **Chart download**: Add a "Download PNG" button below each chart
- **Chart type suggestion**: LLM picks the best chart type based on the data shape
- **Fallback to table**: If chart rendering fails, show the data as an HTML table
