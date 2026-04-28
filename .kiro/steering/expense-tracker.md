# Expense Tracker — Application Steering Document

This document is the authoritative source of truth for the Expense Tracker application.
It captures all design decisions, data models, API contracts, UI behavior, and implementation
details needed to recreate the app from scratch.

---

## 1. Overview

A four-page web application for tracking expenses. Users create **expense reports** (a named,
dated container) and attach **sub-expenses** (categorized line items with an amount and optional
note) to each report. A second page provides flexible querying across all data. A third page
manages **sub-expense categories** — users can add new categories and edit the display label
and icon of existing ones. A fourth page provides a **natural-language chat** interface
powered by Amazon Bedrock (Claude) that answers questions about expense data by generating
and executing SQL queries.

---

## 2. Technology Stack

| Layer     | Technology                        |
|-----------|-----------------------------------|
| Backend   | Python 3, Flask 3.1.0             |
| CORS      | flask-cors 5.0.1                  |
| Database  | SQLite (file: `backend/expenses.db`) |
| LLM       | Amazon Bedrock (Claude Sonnet 4.5) via boto3 |
| Frontend  | Vanilla JavaScript (no frameworks) |
| Styling   | Plain CSS (no preprocessors)      |
| Serving   | Python `http.server` on port 8080 |

### Running the app

```bash
# Backend (from backend/)
python3 -m venv .venv
source venv/bin/activate
pip install -r requirements.txt
python app.py          # listens on http://localhost:5000

# Frontend (from frontend/)
python3 -m http.server 8080   # open http://localhost:8080
```

---

## 3. File Structure

```
backend/
  app.py               # Flask application — all routes and DB logic
  requirements.txt     # flask==3.1.0, flask-cors==5.0.1, boto3
  expenses.db          # SQLite database (auto-created on first run)

frontend/
  index.html           # Reports page (main page)
  app.js               # Reports page JavaScript
  query.html           # Query page
  query.js             # Query page JavaScript
  categories.html      # Categories management page
  categories.js        # Categories page JavaScript
  chat.html            # Chat page (Bedrock-powered)
  chat.js              # Chat page JavaScript
  styles.css           # Shared styles (all pages)
  query.css            # Query-page-specific styles
  categories.css       # Categories-page-specific styles
  chat.css             # Chat-page-specific styles
```

---

## 4. Database Schema

### 4.1 `expense_reports`

| Column         | Type    | Constraints              | Notes                              |
|----------------|---------|--------------------------|------------------------------------|
| `id`           | INTEGER | PRIMARY KEY AUTOINCREMENT |                                    |
| `description`  | TEXT    | NOT NULL                 | Free-text name for the report      |
| `date`         | TEXT    | NOT NULL                 | `YYYY-MM-DD` — the report date     |
| `created_date` | TEXT    | NOT NULL                 | UTC ISO-8601 timestamp             |
| `modified_date`| TEXT    | nullable                 | UTC ISO-8601; set on any update    |

> **Legacy note:** Older databases also have a `created_at TEXT NOT NULL` column from an earlier
> schema version. New INSERTs must write the same timestamp to both `created_at` and
> `created_date` to satisfy the NOT NULL constraint on the old column.

### 4.2 `sub_expenses`

| Column         | Type    | Constraints                                          | Notes                                    |
|----------------|---------|------------------------------------------------------|------------------------------------------|
| `id`           | INTEGER | PRIMARY KEY AUTOINCREMENT                            |                                          |
| `report_id`    | INTEGER | NOT NULL, FK → `expense_reports(id)` ON DELETE CASCADE |                                        |
| `category`     | TEXT    | NOT NULL                                             | One of the 9 fixed categories (see §5)   |
| `note`         | TEXT    | NOT NULL DEFAULT ''                                  | Optional free-text note                  |
| `amount`       | REAL    | NOT NULL                                             | Must be > 0                              |
| `created_date` | TEXT    | NOT NULL                                             | UTC ISO-8601 timestamp                   |
| `modified_date`| TEXT    | nullable                                             | UTC ISO-8601; set on update              |

> **Legacy note:** Same `created_at TEXT NOT NULL` legacy column exists. Same dual-write rule
> applies on INSERT.

### 4.3 `categories`

| Column         | Type    | Constraints       | Notes                                    |
|----------------|---------|-------------------|------------------------------------------|
| `slug`         | TEXT    | PRIMARY KEY       | Immutable identifier (e.g. `airline`)    |
| `display_label`| TEXT    | NOT NULL          | Human-readable name (e.g. "Airline")     |
| `icon`         | TEXT    | NOT NULL DEFAULT ''| Emoji icon for display                   |
| `sort_order`   | INTEGER | NOT NULL DEFAULT 0| Controls display ordering                |

### 4.4 Migration strategy

`init_db()` runs on every server start. It:
1. Creates all three tables with `CREATE TABLE IF NOT EXISTS`.
2. Seeds the `categories` table with 9 defaults if it is empty.
3. Attempts `ALTER TABLE … ADD COLUMN` for each new column, silently ignoring errors if the
   column already exists (SQLite does not support `IF NOT EXISTS` on `ALTER TABLE`).
4. Back-fills `created_date` from `created_at` for any rows where `created_date IS NULL`.

### 4.5 Derived values

- **Report total** is never stored. It is always computed at query time as
  `SUM(sub_expenses.amount)` for the report's rows.
- Deleting a report cascades to all its sub-expenses via the FK constraint.

---

## 5. Sub-Expense Categories

Categories are **database-managed** in the `categories` table (see §4.3). They are no longer
hardcoded in Python or JavaScript. All pages fetch categories from `GET /api/categories` at
startup and populate dropdowns dynamically.

### Default seed categories

On first run (empty `categories` table), `init_db()` seeds these 9 defaults:

| Slug            | Display Label   | Icon | Sort Order |
|-----------------|-----------------|------|------------|
| `airline`       | Airline         | ✈️   | 1          |
| `hotel`         | Hotel           | 🏨   | 2          |
| `car`           | Car             | 🚗   | 3          |
| `organization`  | Organization    | 🏢   | 4          |
| `coach_lessons` | Coach Lessons   | 🎓   | 5          |
| `slush`         | Slush           | 💧   | 6          |
| `admission`     | Admission       | 🎟️  | 7          |
| `equipment`     | Equipment       | 🔧   | 8          |
| `other`         | Other           | 📦   | 9          |

### Slug rules
- Must start with a lowercase letter
- May contain only lowercase letters, digits, and underscores (`^[a-z][a-z0-9_]*$`)
- Immutable after creation (the slug is the primary key and is referenced by `sub_expenses.category`)

### Adding new categories
Users add categories via the Categories page (`categories.html`). The slug, display label,
and icon are provided. `sort_order` is auto-assigned as `MAX(sort_order) + 1`.

### Editing categories
Users can change the **display label** and **icon** of any existing category. The slug
cannot be changed. Changes are saved per-row via `PUT /api/categories/:slug`.

"Organization" is intentionally generic — it represents a specific group without naming it.

---

## 6. REST API

Base URL: `http://localhost:5000/api`

All request and response bodies are JSON. All timestamps are UTC ISO-8601 strings.

### 6.1 Categories

#### `GET /categories`
Returns all categories ordered by `sort_order, slug`.

**Response 200:**
```json
[
  { "slug": "airline", "display_label": "Airline", "icon": "✈️", "sort_order": 1 }
]
```

#### `POST /categories`
Add a new category.

**Request body:**
```json
{ "slug": "parking", "display_label": "Parking", "icon": "🅿️" }
```

**Validation:**
- `slug` required, must match `^[a-z][a-z0-9_]*$`, must be unique
- `display_label` required, non-empty
- `icon` optional

**Response 201:** The new category object.
**Response 409:** If slug already exists.

#### `PUT /categories/:slug`
Update a category's display label and/or icon. The slug cannot be changed.

**Request body:**
```json
{ "display_label": "Parking Fees", "icon": "🅿️" }
```

**Response 200:** The updated category object.

### 6.2 Expense Reports

#### `GET /expenses`
Returns all reports ordered by `date DESC, created_date DESC`.
Each report includes its `sub_expenses` array and a computed `total`.

**Response 200:**
```json
[
  {
    "id": 1,
    "description": "Q2 Conference",
    "date": "2026-04-15",
    "created_date": "2026-04-15T10:00:00+00:00",
    "modified_date": null,
    "total": 1250.00,
    "sub_expenses": [ ... ]
  }
]
```

#### `POST /expenses`
Create a new expense report. No amount is provided — the total is derived from sub-expenses.

**Request body:**
```json
{ "description": "Q2 Conference", "date": "2026-04-15" }
```

**Response 201:** Full report object (with empty `sub_expenses` array and `total: 0`).

**Validation:**
- `description` required, non-empty string
- `date` required, must parse as `YYYY-MM-DD`

#### `PUT /expenses/:id`
Update a report's header fields and optionally all its sub-expenses in a single transaction.
Sets `modified_date` on the report and on every sub-expense that is updated.

**Request body:**
```json
{
  "description": "Updated name",
  "date": "2026-04-20",
  "sub_expenses": [
    { "id": 3, "category": "airline", "note": "Flight to NYC", "amount": 450.00 },
    { "id": 4, "category": "hotel",   "note": "",              "amount": 320.00 }
  ]
}
```
`sub_expenses` is optional. Omit it to update only the header.

**Response 200:** Full updated report object.

#### `DELETE /expenses/:id`
Delete a report and all its sub-expenses (cascade).

**Response 200:** `{ "message": "Expense report deleted" }`

---

### 6.3 Sub-Expenses

#### `POST /expenses/:reportId/sub_expenses`
Add a sub-expense to an existing report. Also sets `modified_date` on the parent report.

**Request body:**
```json
{ "category": "airline", "note": "Flight to NYC", "amount": 450.00 }
```

**Validation:**
- `category` must be one of the 9 valid slugs
- `amount` must be a number > 0
- `note` is optional (defaults to empty string)

**Response 201:** Full parent report object (with updated `sub_expenses` and `total`).

#### `DELETE /expenses/:reportId/sub_expenses/:subId`
Delete a single sub-expense. Also sets `modified_date` on the parent report.

**Response 200:** Full updated parent report object.

---

### 6.4 Summary

#### `GET /summary`
Aggregate totals across all data.

**Response 200:**
```json
{
  "total": 5430.00,
  "count": 12,
  "breakdown": {
    "airline": 1200.00,
    "hotel": 980.00
  }
}
```

---

### 6.5 Query

#### `GET /query`
Flexible filtered query. All parameters are optional and combinable.

| Param       | Values                          | Notes                                      |
|-------------|---------------------------------|--------------------------------------------|
| `type`      | `sub_expenses` (default), `reports` | Switches result shape                  |
| `category`  | any valid category slug         | Sub-expenses mode only; omit for all       |
| `date_from` | `YYYY-MM-DD`                    | Filters on `expense_reports.date`, inclusive |
| `date_to`   | `YYYY-MM-DD`                    | Inclusive                                  |

**Response 200 — sub_expenses mode:**
```json
{
  "type": "sub_expenses",
  "results": [
    {
      "id": 3,
      "report_id": 1,
      "category": "airline",
      "note": "Flight to NYC",
      "amount": 450.00,
      "report_description": "Q2 Conference",
      "report_date": "2026-04-15"
    }
  ],
  "grand_total": 450.00,
  "breakdown": { "airline": 450.00 }
}
```

**Response 200 — reports mode:**
```json
{
  "type": "reports",
  "results": [ /* full report objects with sub_expenses and total */ ],
  "grand_total": 1250.00
}
```

---

### 6.6 Chat

#### `POST /chat`
Natural-language query interface powered by Amazon Bedrock.

**Request body:**
```json
{ "message": "How much did I spend on hotels?" }
```

**Validation:**
- `message` required, non-empty, max 1000 characters

**Response 200:**
```json
{
  "answer": "You spent $1,200 on hotels across 3 expense reports.",
  "sql": "SELECT SUM(amount) AS total FROM sub_expenses WHERE category = 'hotel'",
  "data": [{ "total": 1200.0 }]
}
```

If the model determines the question cannot be answered from the DB, `sql` and `data` are
`null` and `answer` contains the model's explanation.

**Response 400:** Invalid input or rejected SQL.
**Response 500:** Bedrock or execution failure.
**Response 503:** Bedrock client not configured.

**Two-call flow:**
1. First Bedrock call: system prompt with DB schema + live categories + safety rules →
   model generates a SQL SELECT query
2. SQL is validated (must start with SELECT, no DDL/DML) and executed read-only against
   `expenses.db`
3. Second Bedrock call: user question + SQL + raw results → model formats a human-readable
   answer

**Bedrock configuration:**
- Model: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (configurable via `BEDROCK_MODEL` env var)
- Region: `us-east-1` (configurable via `BEDROCK_REGION` env var)
- API: `converse` via boto3 bedrock-runtime client
- Temperature: 0 (deterministic SQL generation)
- Max tokens: 1024

---

## 7. Frontend Architecture

### 7.1 Pages

| File              | Purpose                                      |
|-------------------|----------------------------------------------|
| `index.html`      | Reports page — create, view, edit, delete    |
| `query.html`      | Query page — filter and display results      |
| `categories.html` | Categories page — add and edit categories    |
| `chat.html`       | Chat page — natural-language expense queries  |

All pages share `styles.css`. `query.html` additionally loads `query.css`.
`categories.html` additionally loads `categories.css`. `chat.html` additionally loads
`chat.css`.

Navigation between pages uses plain `<a href>` links in a shared nav component rendered
in each page's `<header>`. The active tab gets class `nav-tab--active`. All four pages
include the same four tabs: Reports, Query, Categories, Chat.

### 7.2 No build step

The frontend uses no bundler, transpiler, or framework. All JS is vanilla ES2020+ loaded
directly via `<script src>`. No `import`/`export` — all code is in a single script per page.

### 7.3 API base URL

Both `app.js` and `query.js` define:
```js
const API_BASE = "http://localhost:5000/api";
```

### 7.4 Category metadata

Categories are loaded from `GET /api/categories` at page init on all three pages. The
response is stored in a `CATEGORIES` array. Helper functions `categoryLabel(slug)` and
`buildCategoryOptions(selectedSlug)` use this array to render display labels and populate
`<select>` dropdowns dynamically. There is no hardcoded category list in the frontend.

---

## 8. Reports Page (`index.html` / `app.js`)

### 8.1 Summary bar

Two stat tiles at the top of the page:
- **Grand Total** — sum of all sub-expense amounts across all reports (`/api/summary`)
- **Expense Reports** — count of all reports

### 8.2 New Report form

Fields: `description` (text, required, max 200 chars) and `date` (date picker, required,
defaults to today). On submit, calls `POST /api/expenses`. The new card is prepended to the
list and auto-expanded.

### 8.3 Report cards

Each report renders as a collapsible card:

**View mode (collapsed):** Shows description, date, total, and three action buttons:
`+ Add`, `Edit`, `Delete`.

**View mode (expanded):** Clicking the card header (not a button) toggles the sub-expense
panel open/closed. The toggle arrow rotates 90° when open. Expansion state is tracked in a
`Set<number>` (`expandedReports`) so it survives card re-renders.

**Sub-expense panel (view):** Table with columns: Category (badge), Note, Amount, Action
(Delete button per row). Footer row shows the report total. Below the table is a timestamp
footer showing `Created:` and `Modified:` dates.

**Edit mode:** Clicking `Edit` switches the card to edit mode (tracked in `editingReports`
Set). The header becomes a purple-tinted form with editable Description and Date inputs.
The sub-expense panel stays open and each row becomes editable inline (category dropdown,
note input, amount input). A single **Save** button in the header collects all changes
(header fields + all sub-expense rows) and sends them in one `PUT /api/expenses/:id` request.
**Cancel** reverts to view mode with no API call.

**Delete report:** Requires `window.confirm()` before calling `DELETE /api/expenses/:id`.

**Add sub-expense:** Opens a modal dialog (see §8.4).

**Delete sub-expense:** Works in both view and edit mode. Calls
`DELETE /api/expenses/:id/sub_expenses/:subId`. The card re-renders in place; edit mode is
preserved if active.

### 8.4 Add Sub-Expense modal

Triggered by the `+ Add` button on any report card. Fields:
- **Category** — required `<select>` with all 9 options
- **Note** — optional text input, `autocomplete="off"` to suppress browser history suggestions
- **Amount** — required number input, min 0.01, step 0.01

The modal form has `autocomplete="off"` at the form level as well.

Dismiss: × button, Cancel button, clicking the overlay backdrop, or pressing Escape.

On submit: calls `POST /api/expenses/:reportId/sub_expenses`. The card is patched in place
(not a full list re-render). The summary bar is refreshed.

### 8.5 Card rendering pattern

Cards are built by `buildCard(report)` which reads `expandedReports` and `editingReports`
to decide which HTML variant to render. `replaceCard(oldCard, report)` swaps a DOM node
in place without re-rendering the whole list. This preserves scroll position and other
cards' state.

---

## 9. Query Page (`query.html` / `query.js`)

### 9.1 Filter panel

**Type toggle:** Pill-style toggle group — "Sub-Expenses" (default) or "Expense Reports".
Switching to "Expense Reports" hides the Category filter (not applicable at report level).

**Filters:**
- Category (sub-expenses mode only) — `<select>`, defaults to "All categories"
- From Date — optional date picker
- To Date — optional date picker

**Validation:** If both dates are provided, `date_from` must be ≤ `date_to`. Error shown
inline on the To Date field.

**Run Query** — submits the form, builds a `URLSearchParams` object, calls `GET /api/query`.
**Clear** — resets all fields and hides results.

### 9.2 Sub-expense results

- **Summary bar** (top-right of results card): count of line items + grand total
- **Breakdown chips**: one pill per category present in results, sorted by amount descending,
  showing category label and subtotal
- **Results table**: columns — Report Date, Report (description), Category (badge), Note,
  Amount (right-aligned)
- **Footer row**: grand total

### 9.3 Report results

- **Summary bar**: count of reports + grand total
- **Result cards**: one card per report showing description, date, total, and a nested
  sub-expenses table (Category, Note, Amount)
- **Grand total bar**: shown below all cards

---

## 10. Categories Page (`categories.html` / `categories.js`)

### 10.1 Add Category form

Fields:
- **Slug** — required text input, validated against `^[a-z][a-z0-9_]*$`, max 50 chars.
  Shown with a hint: "Lowercase letters, numbers, underscores. Used internally."
- **Display Label** — required text input, max 100 chars
- **Icon** — optional text input for an emoji, max 10 chars

On submit: calls `POST /api/categories`. On success, resets the form and reloads the list.
A 409 error (duplicate slug) is shown inline.

### 10.2 Category list

Each category renders as an inline row with:
- **Slug** — displayed as read-only monospace text (not editable)
- **Icon** — editable text input (small, centered)
- **Display Label** — editable text input
- **Save** button — calls `PUT /api/categories/:slug` for that row only

After a successful save, the button briefly shows "Saved ✓" for 1.2 seconds before
reverting to "Save". Validation: display label is required.

---

## 11. Chat Page (`chat.html` / `chat.js`)

### 11.1 Layout

Full-height chat layout within the standard container. The chat card uses `flex: 1` to fill
available vertical space. Inside: a scrollable messages area and a fixed input bar at the
bottom.

### 11.2 Message types

| Type       | Alignment | CSS class                | Style                            |
|------------|-----------|--------------------------|----------------------------------|
| User       | Right     | `chat-bubble--user`      | Indigo background, white text    |
| Assistant  | Left      | `chat-bubble--assistant` | Light gray background, dark text |
| Error      | Left      | `chat-bubble--error`     | Red-tinted background            |
| Loading    | Left      | `chat-bubble--loading`   | Animated "Thinking..." dots      |

### 11.3 "Show SQL" toggle

Each assistant response that includes SQL shows a "▸ Show SQL" link below the answer.
Clicking toggles a dark-themed monospace code block. Toggle text changes to "▾ Hide SQL"
when expanded.

### 11.4 Behavior

- Welcome message on page load with example questions
- User types and presses Enter or clicks Send
- User bubble appears immediately; loading indicator shows while waiting
- On response: loading replaced with assistant bubble (+ SQL toggle if SQL was generated)
- Auto-scrolls to bottom after each message
- Input cleared and re-focused after send
- Conversation is DOM-only (lost on refresh)

### 11.5 Input validation

- Empty messages blocked (Send button disabled)
- Max 1000 characters (inline error if exceeded)
- Input and button disabled during in-flight requests

### 11.6 Single-turn design

Each message is independent — no conversation history is sent to Bedrock. This keeps the
implementation simple and avoids token cost growth. Multi-turn is a future enhancement.

---

## 12. Visual Design

### 10.1 Color palette

| Purpose                  | Value     |
|--------------------------|-----------|
| Primary (indigo)         | `#4f46e5` |
| Primary hover            | `#4338ca` |
| Primary light (indigo)   | `#6366f1` |
| Edit mode (violet)       | `#7c3aed` |
| Edit mode hover          | `#6d28d9` |
| Edit mode border         | `#c4b5fd` |
| Edit mode bg             | `#faf5ff` |
| Category badge bg        | `#ede9fe` |
| Category badge text      | `#5b21b6` |
| Total row bg             | `#f5f3ff` |
| Error red                | `#ef4444` |
| Error bg                 | `#fef2f2` |
| Error border             | `#fecaca` |
| Page background          | `#f0f2f5` |
| Card background          | `#fff`    |
| Border                   | `#e5e7eb` |
| Muted text               | `#6b7280` |
| Body text                | `#374151` |
| Heading text             | `#111827` |

### 10.2 Typography

System font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`

### 10.3 Layout

- Max container width: `900px`, centered
- Vertical gap between sections: `24px`
- Cards: `border-radius: 12px`, `padding: 28px`, subtle box-shadow
- Report cards: `border-radius: 10px`, `border: 1.5px solid #e5e7eb`

### 10.4 Edit mode visual distinction

Edit mode uses a violet/purple color scheme (`#7c3aed`) to clearly distinguish it from
view mode (indigo `#4f46e5`). The header background shifts to `#faf5ff` with a
`#ddd6fe` border.

### 10.5 Responsive breakpoints

At `max-width: 560px`:
- Summary bar stacks vertically
- Report header wraps; total moves to top-right

---

## 13. Key Implementation Decisions

### Timestamps
- All timestamps stored as UTC ISO-8601 strings (Python `datetime.now(timezone.utc).isoformat()`).
- `created_date` is set once on INSERT and never changed.
- `modified_date` is NULL until the first update; set on every subsequent write.
- Adding or deleting a sub-expense also updates the parent report's `modified_date`.

### Report total is always derived
The `total` field on a report is never persisted. It is computed as `SUM(amount)` from
`sub_expenses` every time a report is fetched. This prevents stale totals.

### Bulk save on edit
The `PUT /api/expenses/:id` endpoint accepts an optional `sub_expenses` array. The frontend
collects all sub-expense row values at save time and sends them in a single request, updating
the report header and all sub-expenses in one DB transaction. There is no per-row save.

### Card patching vs full re-render
After any mutation (add sub, delete sub, save edit), only the affected card is replaced in
the DOM using `replaceCard()`. The full list is only re-rendered on page load or report
deletion. This preserves scroll position and other cards' expand/edit state.

### Autocomplete suppression
The "Note" field in the Add Sub-Expense modal has `autocomplete="off"` on both the input
and the parent `<form>` to prevent the browser from showing previously entered values as
suggestions.

### DB migration compatibility
The app was initially built with a `created_at` column. When `created_date` and
`modified_date` were added, the migration used `ALTER TABLE … ADD COLUMN` (silently
ignoring duplicate-column errors). Because `created_at` is `NOT NULL` in existing databases,
all INSERTs must write the same timestamp value to both `created_at` and `created_date`.

### Dynamic categories
Categories are stored in the `categories` table and loaded from `GET /api/categories` at
page init on all frontend pages. The backend validates category slugs against the DB (via
`get_valid_slugs(conn)`) rather than a hardcoded Python list. New categories can be added
at runtime without code changes. The slug is immutable after creation since it is referenced
as a foreign key in `sub_expenses.category`.

### Foreign key enforcement
`PRAGMA foreign_keys = ON` is set on every connection. This enables the `ON DELETE CASCADE`
behavior so deleting a report automatically removes all its sub-expenses.

### No authentication
The app has no user accounts, sessions, or access control. It is intended for single-user
local use.

### Bedrock chat — two-call pattern
The chat endpoint makes two separate Bedrock calls per user message: one to generate SQL,
one to format the answer. This separation keeps each prompt focused and allows the backend
to validate and execute the SQL between calls. The SQL is validated (must be SELECT-only)
and executed on a read-only connection with a 5-second timeout. The system prompt includes
the full DB schema and live category list so the model generates accurate queries.

### No pagination
All reports and sub-expenses are returned in full on every `GET /api/expenses` call.
Pagination has not been implemented.

---

## 14. Validation Rules

### Report
- `description`: required, non-empty after trim
- `date`: required, must parse as `YYYY-MM-DD`

### Sub-expense
- `category`: required, must be one of the 9 valid slugs (case-insensitive, lowercased before storage)
- `amount`: required, must be a valid float > 0
- `note`: optional, defaults to empty string

### Query page
- `date_from` and `date_to`: if both provided, `date_from` must be ≤ `date_to` (client-side check)
- `category`: if provided, must be a valid slug (server-side check)

---

## 15. Error Handling

- All API errors return JSON `{ "error": "message" }` with an appropriate 4xx status.
- The frontend displays inline field errors for validation failures.
- Network/server errors show a message in a red error banner within the relevant form or
  results section.
- Buttons are disabled during in-flight requests and re-enabled on failure.
- Delete operations use `window.confirm()` for confirmation before the API call.
