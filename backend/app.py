from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
import re
import json
import logging
from datetime import datetime, timezone

import boto3

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")

# ── Chat logger (writes to chat.log) ──────────────────────────────────────────
CHAT_LOG_PATH = os.path.join(os.path.dirname(__file__), "chat.log")
chat_logger = logging.getLogger("chat")
chat_logger.setLevel(logging.INFO)
_chat_handler = logging.FileHandler(CHAT_LOG_PATH, encoding="utf-8")
_chat_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
chat_logger.addHandler(_chat_handler)

# ── Bedrock configuration ─────────────────────────────────────────────────────
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL  = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Feature flag: set to "true" to route chat through Bedrock Flows instead of direct model calls
USE_BEDROCK_FLOW = os.environ.get("USE_BEDROCK_FLOW", "false").lower() == "true"
BEDROCK_FLOW_ID    = os.environ.get("BEDROCK_FLOW_ID", "FNO4NHO5DT")
BEDROCK_FLOW_ALIAS = os.environ.get("BEDROCK_FLOW_ALIAS", "TSTALIASID")

try:
    bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
except Exception as e:
    logging.warning(f"Could not create Bedrock runtime client: {e}")
    bedrock_client = None

try:
    bedrock_agent_client = boto3.client("bedrock-agent-runtime", region_name=BEDROCK_REGION)
except Exception as e:
    logging.warning(f"Could not create Bedrock agent runtime client: {e}")
    bedrock_agent_client = None

DEFAULT_CATEGORIES = [
    ("airline",       "Airline",       "✈️",  1),
    ("hotel",         "Hotel",         "🏨",  2),
    ("car",           "Car",           "🚗",  3),
    ("organization",  "Organization",  "🏢",  4),
    ("coach_lessons", "Coach Lessons", "🎓",  5),
    ("slush",         "Slush",         "💧",  6),
    ("admission",     "Admission",     "🎟️", 7),
    ("equipment",     "Equipment",     "🔧",  8),
    ("other",         "Other",         "📦",  9),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with get_db() as conn:
        # ── Categories table ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                slug          TEXT PRIMARY KEY,
                display_label TEXT NOT NULL,
                icon          TEXT NOT NULL DEFAULT '',
                sort_order    INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Seed defaults if table is empty
        count = conn.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO categories (slug, display_label, icon, sort_order) VALUES (?, ?, ?, ?)",
                DEFAULT_CATEGORIES,
            )

        # ── Expense reports table ─────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expense_reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                description   TEXT    NOT NULL,
                date          TEXT    NOT NULL,
                created_date  TEXT    NOT NULL,
                modified_date TEXT
            )
        """)

        # ── Sub-expenses table ────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sub_expenses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id     INTEGER NOT NULL REFERENCES expense_reports(id) ON DELETE CASCADE,
                category      TEXT    NOT NULL,
                note          TEXT    NOT NULL DEFAULT '',
                amount        REAL    NOT NULL,
                created_date  TEXT    NOT NULL,
                modified_date TEXT
            )
        """)

        # ── Migrate existing databases ────────────────────────────────────────
        migrations = [
            ("expense_reports", "created_date",  "TEXT"),
            ("expense_reports", "modified_date", "TEXT"),
            ("sub_expenses",    "created_date",  "TEXT"),
            ("sub_expenses",    "modified_date", "TEXT"),
        ]
        for table, column, col_type in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except Exception:
                pass

        # Back-fill created_date from legacy created_at
        for table in ("expense_reports", "sub_expenses"):
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "created_at" in cols:
                conn.execute(f"""
                    UPDATE {table}
                    SET created_date = created_at
                    WHERE created_date IS NULL AND created_at IS NOT NULL
                """)

        conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_valid_slugs(conn):
    """Return the set of valid category slugs from the DB."""
    rows = conn.execute("SELECT slug FROM categories").fetchall()
    return {r["slug"] for r in rows}


def report_with_subs(conn, report_id):
    report = conn.execute(
        "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    ).fetchone()
    if not report:
        return None
    subs = conn.execute(
        "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
        (report_id,),
    ).fetchall()
    total = sum(s["amount"] for s in subs)
    return {**dict(report), "total": total, "sub_expenses": [dict(s) for s in subs]}


def validate_date(date_str):
    if not date_str:
        return "Date is required"
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "Date must be in YYYY-MM-DD format"
    return None


# ── Categories ────────────────────────────────────────────────────────────────

@app.route("/api/categories", methods=["GET"])
def get_categories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, slug"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def add_category():
    data = request.get_json()
    slug          = (data.get("slug") or "").strip().lower()
    display_label = (data.get("display_label") or "").strip()
    icon          = (data.get("icon") or "").strip()

    if not slug:
        return jsonify({"error": "Slug is required"}), 400
    if not re.match(r'^[a-z][a-z0-9_]*$', slug):
        return jsonify({"error": "Slug must start with a letter and contain only lowercase letters, numbers, and underscores"}), 400
    if not display_label:
        return jsonify({"error": "Display label is required"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT slug FROM categories WHERE slug = ?", (slug,)).fetchone()
        if existing:
            return jsonify({"error": f"Category '{slug}' already exists"}), 409

        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) as m FROM categories").fetchone()["m"]
        conn.execute(
            "INSERT INTO categories (slug, display_label, icon, sort_order) VALUES (?, ?, ?, ?)",
            (slug, display_label, icon, max_order + 1),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()

    return jsonify(dict(row)), 201


@app.route("/api/categories/<slug>", methods=["PUT"])
def update_category(slug):
    data = request.get_json()
    display_label = (data.get("display_label") or "").strip()
    icon          = (data.get("icon") or "").strip()

    if not display_label:
        return jsonify({"error": "Display label is required"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT slug FROM categories WHERE slug = ?", (slug,)).fetchone()
        if not existing:
            return jsonify({"error": "Category not found"}), 404

        conn.execute(
            "UPDATE categories SET display_label = ?, icon = ? WHERE slug = ?",
            (display_label, icon, slug),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()

    return jsonify(dict(row)), 200


# ── Expense Reports ───────────────────────────────────────────────────────────

@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    with get_db() as conn:
        reports = conn.execute(
            "SELECT * FROM expense_reports ORDER BY date DESC, created_date DESC"
        ).fetchall()
        result = []
        for r in reports:
            subs = conn.execute(
                "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
                (r["id"],),
            ).fetchall()
            total = sum(s["amount"] for s in subs)
            result.append({**dict(r), "total": total, "sub_expenses": [dict(s) for s in subs]})
    return jsonify(result)


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.get_json()
    description = (data.get("description") or "").strip()
    date = (data.get("date") or "").strip()

    if not description:
        return jsonify({"error": "Description is required"}), 400
    err = validate_date(date)
    if err:
        return jsonify({"error": err}), 400

    ts = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO expense_reports
               (description, date, created_at, created_date)
               VALUES (?, ?, ?, ?)""",
            (description, date, ts, ts),
        )
        conn.commit()
        row = report_with_subs(conn, cursor.lastrowid)
    return jsonify(row), 201


@app.route("/api/expenses/<int:report_id>", methods=["PUT"])
def update_expense(report_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Expense report not found"}), 404

        data = request.get_json()
        description = (data.get("description") or "").strip()
        date = (data.get("date") or "").strip()

        if not description:
            return jsonify({"error": "Description is required"}), 400
        err = validate_date(date)
        if err:
            return jsonify({"error": err}), 400

        ts = now_utc()
        valid_slugs = get_valid_slugs(conn)

        conn.execute(
            "UPDATE expense_reports SET description = ?, date = ?, modified_date = ? WHERE id = ?",
            (description, date, ts, report_id),
        )

        sub_updates = data.get("sub_expenses")
        if sub_updates is not None:
            for sub in sub_updates:
                sub_id   = sub.get("id")
                category = (sub.get("category") or "").strip().lower()
                note     = (sub.get("note") or "").strip()
                amount   = sub.get("amount")

                if not sub_id:
                    continue
                if category not in valid_slugs:
                    return jsonify({"error": f"Invalid category '{category}' for sub-expense {sub_id}"}), 400
                try:
                    amount = float(amount)
                    if amount <= 0:
                        return jsonify({"error": f"Amount must be > 0 for sub-expense {sub_id}"}), 400
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid amount for sub-expense {sub_id}"}), 400

                conn.execute(
                    """UPDATE sub_expenses
                       SET category = ?, note = ?, amount = ?, modified_date = ?
                       WHERE id = ? AND report_id = ?""",
                    (category, note, amount, ts, sub_id, report_id),
                )

        conn.commit()
        updated = report_with_subs(conn, report_id)
    return jsonify(updated), 200


@app.route("/api/expenses/<int:report_id>", methods=["DELETE"])
def delete_expense(report_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Expense report not found"}), 404
        conn.execute("DELETE FROM expense_reports WHERE id = ?", (report_id,))
        conn.commit()
    return jsonify({"message": "Expense report deleted"}), 200


# ── Sub-Expenses ──────────────────────────────────────────────────────────────

@app.route("/api/expenses/<int:report_id>/sub_expenses", methods=["POST"])
def add_sub_expense(report_id):
    with get_db() as conn:
        report = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not report:
            return jsonify({"error": "Expense report not found"}), 404

        data = request.get_json()
        category = (data.get("category") or "").strip().lower()
        note     = (data.get("note") or "").strip()
        amount   = data.get("amount")

        valid_slugs = get_valid_slugs(conn)
        if category not in valid_slugs:
            return jsonify({"error": f"Invalid category. Must be one of: {', '.join(sorted(valid_slugs))}"}), 400
        try:
            amount = float(amount)
            if amount <= 0:
                return jsonify({"error": "Amount must be greater than zero"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Amount must be a valid number"}), 400

        ts = now_utc()
        conn.execute(
            """INSERT INTO sub_expenses
               (report_id, category, note, amount, created_at, created_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, category, note, amount, ts, ts),
        )
        conn.execute(
            "UPDATE expense_reports SET modified_date = ? WHERE id = ?",
            (ts, report_id),
        )
        conn.commit()
        row = report_with_subs(conn, report_id)
    return jsonify(row), 201


@app.route("/api/expenses/<int:report_id>/sub_expenses/<int:sub_id>", methods=["DELETE"])
def delete_sub_expense(report_id, sub_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM sub_expenses WHERE id = ? AND report_id = ?",
            (sub_id, report_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Sub-expense not found"}), 404

        ts = now_utc()
        conn.execute("DELETE FROM sub_expenses WHERE id = ?", (sub_id,))
        conn.execute(
            "UPDATE expense_reports SET modified_date = ? WHERE id = ?",
            (ts, report_id),
        )
        conn.commit()
        updated = report_with_subs(conn, report_id)
    return jsonify(updated), 200


# ── Query ─────────────────────────────────────────────────────────────────────

@app.route("/api/query", methods=["GET"])
def query_expenses():
    qtype     = request.args.get("type", "sub_expenses").strip().lower()
    category  = (request.args.get("category") or "").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()

    for label, val in (("date_from", date_from), ("date_to", date_to)):
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": f"{label} must be YYYY-MM-DD"}), 400

    with get_db() as conn:
        valid_slugs = get_valid_slugs(conn)

        if qtype == "reports":
            where, params = [], []
            if date_from:
                where.append("er.date >= ?")
                params.append(date_from)
            if date_to:
                where.append("er.date <= ?")
                params.append(date_to)

            sql = "SELECT * FROM expense_reports er"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY er.date DESC, er.created_date DESC"

            reports = conn.execute(sql, params).fetchall()
            result = []
            for r in reports:
                subs = conn.execute(
                    "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
                    (r["id"],),
                ).fetchall()
                total = sum(s["amount"] for s in subs)
                result.append({**dict(r), "total": total, "sub_expenses": [dict(s) for s in subs]})

            grand_total = sum(r["total"] for r in result)
            return jsonify({"type": "reports", "results": result, "grand_total": grand_total})

        else:
            where, params = [], []
            if category:
                if category not in valid_slugs:
                    return jsonify({"error": f"Invalid category. Must be one of: {', '.join(sorted(valid_slugs))}"}), 400
                where.append("se.category = ?")
                params.append(category)
            if date_from:
                where.append("er.date >= ?")
                params.append(date_from)
            if date_to:
                where.append("er.date <= ?")
                params.append(date_to)

            sql = """
                SELECT se.id, se.report_id, se.category, se.note, se.amount,
                       se.created_date, se.modified_date,
                       er.description AS report_description, er.date AS report_date
                FROM sub_expenses se
                JOIN expense_reports er ON er.id = se.report_id
            """
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY er.date DESC, se.category, se.id"

            rows = conn.execute(sql, params).fetchall()
            results = [dict(r) for r in rows]
            grand_total = sum(r["amount"] for r in results)
            breakdown = {}
            for r in results:
                breakdown[r["category"]] = breakdown.get(r["category"], 0) + r["amount"]

            return jsonify({
                "type": "sub_expenses",
                "results": results,
                "grand_total": grand_total,
                "breakdown": breakdown,
            })


# ── Chat (Bedrock) ────────────────────────────────────────────────────────────

DB_SCHEMA_TEXT = """
Tables in the SQLite database:

1. categories
   - slug          TEXT PRIMARY KEY   -- e.g. 'airline', 'hotel'
   - display_label TEXT NOT NULL      -- human-readable name
   - icon          TEXT               -- emoji icon
   - sort_order    INTEGER            -- display ordering

2. expense_reports
   - id            INTEGER PRIMARY KEY AUTOINCREMENT
   - description   TEXT NOT NULL      -- name of the expense report
   - date          TEXT NOT NULL      -- report date in 'YYYY-MM-DD' format
   - created_date  TEXT               -- UTC ISO-8601 timestamp
   - modified_date TEXT               -- UTC ISO-8601 timestamp, NULL until first edit

3. sub_expenses
   - id            INTEGER PRIMARY KEY AUTOINCREMENT
   - report_id     INTEGER NOT NULL   -- FK → expense_reports(id)
   - category      TEXT NOT NULL      -- FK-like reference to categories.slug
   - note          TEXT               -- optional note
   - amount        REAL NOT NULL      -- dollar amount, always > 0
   - created_date  TEXT               -- UTC ISO-8601 timestamp
   - modified_date TEXT               -- UTC ISO-8601 timestamp

Relationships:
- sub_expenses.report_id → expense_reports.id (ON DELETE CASCADE)
- sub_expenses.category matches categories.slug
- A report's total is NOT stored; it is SUM(sub_expenses.amount) for that report.
""".strip()


def build_chat_system_prompt(conn):
    """Build the system prompt with live category data."""
    cats = conn.execute(
        "SELECT slug, display_label FROM categories ORDER BY sort_order"
    ).fetchall()
    cat_list = ", ".join(f"'{c['slug']}' ({c['display_label']})" for c in cats)

    return f"""You are a helpful assistant that answers questions about expense data stored in a SQLite database.

{DB_SCHEMA_TEXT}

Valid category slugs: {cat_list}

Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Rules:
- Generate ONLY a single SQL SELECT statement. Nothing else.
- Do NOT generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or any DDL/DML.
- Use SQLite syntax.
- Return the SQL inside a markdown code block: ```sql ... ```
- If the question cannot be answered from the database, respond with a plain text explanation instead of SQL.
- When filtering by category, use the slug values (e.g. 'airline', not 'Airline').
- When computing report totals, use SUM(sub_expenses.amount) grouped by report_id.
- Dates are stored as text in 'YYYY-MM-DD' format. Use string comparison for date filtering."""


def extract_sql(text):
    """Extract a SQL query from the model response text."""
    # Try ```sql ... ``` first
    match = re.search(r'```sql\s*\n?(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Try ``` ... ```
    match = re.search(r'```\s*\n?(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: use the whole text if it looks like SQL
    stripped = text.strip()
    if stripped.upper().startswith("SELECT"):
        return stripped
    return None


def validate_sql(sql):
    """Return None if valid SELECT, error string otherwise."""
    if not sql:
        return "No SQL query was generated"
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return "Only SELECT queries are allowed"
    forbidden = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "ATTACH ", "DETACH "]
    for kw in forbidden:
        if kw in normalized:
            return f"Forbidden keyword detected: {kw.strip()}"
    return None


def call_bedrock(system_prompt, user_message):
    """Call Bedrock converse API and return the assistant text."""
    response = bedrock_client.converse(
        modelId=BEDROCK_MODEL,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0},
    )
    return response["output"]["message"]["content"][0]["text"]


def invoke_bedrock_flow(message):
    """
    Invoke the Bedrock Flow and collect the streamed response.
    Returns the final output document text.
    """
    response = bedrock_agent_client.invoke_flow(
        flowIdentifier=BEDROCK_FLOW_ID,
        flowAliasIdentifier=BEDROCK_FLOW_ALIAS,
        inputs=[{
            "content": {"document": message},
            "nodeName": "FlowInputNode",
            "nodeOutputName": "document",
        }],
        enableTrace=False,
    )

    # The response is a stream — collect all events
    result_text = None
    for event in response["responseStream"]:
        if "flowOutputEvent" in event:
            content = event["flowOutputEvent"].get("content", {})
            doc = content.get("document")
            if doc is not None:
                result_text = doc if isinstance(doc, str) else json.dumps(doc, default=str)
        elif "flowCompletionEvent" in event:
            pass  # flow finished

    return result_text


def chat_via_model(message):
    """Original two-call Bedrock model path: generate SQL → execute → format answer."""
    with get_db() as conn:
        # Step 1: Ask Bedrock to generate SQL
        system_prompt = build_chat_system_prompt(conn)
        raw_response = call_bedrock(system_prompt, message)

        # Step 2: Extract and validate SQL
        sql = extract_sql(raw_response)
        if sql is None:
            return {"answer": raw_response, "sql": None, "data": None}

        err = validate_sql(sql)
        if err:
            return {"error": f"Generated query was rejected: {err}"}, 400

        # Step 3: Execute SQL (read-only)
        try:
            read_conn = sqlite3.connect(DB_PATH, timeout=5)
            read_conn.row_factory = sqlite3.Row
            rows = read_conn.execute(sql).fetchall()
            results = [dict(r) for r in rows]
            read_conn.close()
        except Exception as sql_err:
            return {"error": f"Query execution failed: {sql_err}", "sql": sql, "data": None}, 400

        # Step 4: Ask Bedrock to format the answer
        format_prompt = (
            "You are a helpful assistant. The user asked a question about their expenses. "
            "A SQL query was run and produced the results below. "
            "Format the results as a clear, concise answer to the user's question. "
            "Use dollar formatting for monetary amounts (e.g. $1,234.56). "
            "Do not include the SQL in your answer. "
            "If the result set is empty, say so clearly."
        )
        format_message = (
            f"User question: {message}\n\n"
            f"SQL executed: {sql}\n\n"
            f"Results ({len(results)} rows):\n{json.dumps(results, default=str, indent=2)}"
        )
        answer = call_bedrock(format_prompt, format_message)

        return {"answer": answer, "sql": sql, "data": results}


def chat_via_flow(message):
    """Bedrock Flow path: send message to the flow and return the result."""
    result_text = invoke_bedrock_flow(message)

    if result_text is None:
        return {"error": "No response received from Bedrock Flow"}, 500

    # Try to parse as JSON (the flow may return structured output)
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict):
            return {
                "answer": parsed.get("answer") or parsed.get("output") or result_text,
                "sql": parsed.get("sql"),
                "data": parsed.get("data"),
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain text response from the flow
    return {"answer": result_text, "sql": None, "data": None}


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is required"}), 400
    if len(message) > 1000:
        return jsonify({"error": "Message must be 1000 characters or fewer"}), 400

    mode = "flow" if USE_BEDROCK_FLOW else "model"
    chat_logger.info(f"REQUEST | mode={mode} | message={message}")

    try:
        if USE_BEDROCK_FLOW:
            if not bedrock_agent_client:
                return jsonify({"error": "Chat is unavailable — Bedrock agent client not configured"}), 503
            result = chat_via_flow(message)
        else:
            if not bedrock_client:
                return jsonify({"error": "Chat is unavailable — Bedrock client not configured"}), 503
            result = chat_via_model(message)

        # Handle tuple returns (response, status_code) for errors
        if isinstance(result, tuple):
            chat_logger.info(f"RESPONSE | mode={mode} | status={result[1]} | error={result[0].get('error')}")
            return jsonify(result[0]), result[1]

        chat_logger.info(
            f"RESPONSE | mode={mode} | status=200"
            f" | sql={result.get('sql', 'N/A')}"
            f" | answer={result.get('answer', '')[:200]}"
            f" | rows={len(result.get('data') or [])}"
        )
        return jsonify(result)

    except Exception as e:
        logging.exception("Chat endpoint error")
        chat_logger.info(f"RESPONSE | mode={mode} | status=500 | error={str(e)}")
        return jsonify({"error": f"Something went wrong: {str(e)}"}), 500


# ── Chat config endpoint ──────────────────────────────────────────────────────

@app.route("/api/chat/config", methods=["GET"])
def chat_config():
    """Return the current chat routing configuration."""
    return jsonify({
        "use_bedrock_flow": USE_BEDROCK_FLOW,
        "model": BEDROCK_MODEL if not USE_BEDROCK_FLOW else None,
        "flow_id": BEDROCK_FLOW_ID if USE_BEDROCK_FLOW else None,
    })


# ── Summary ───────────────────────────────────────────────────────────────────

@app.route("/api/summary", methods=["GET"])
def get_summary():
    with get_db() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM sub_expenses"
        ).fetchone()["total"]
        count = conn.execute(
            "SELECT COUNT(*) as count FROM expense_reports"
        ).fetchone()["count"]
        rows = conn.execute(
            "SELECT category, COALESCE(SUM(amount), 0) as subtotal FROM sub_expenses GROUP BY category"
        ).fetchall()
        breakdown = {r["category"]: r["subtotal"] for r in rows}
    return jsonify({"total": total, "count": count, "breakdown": breakdown})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
