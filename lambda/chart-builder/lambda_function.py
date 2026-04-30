"""
Chart Builder Lambda for Bedrock Flows.

Takes a chart instruction object (with data) and returns a valid Chart.js
configuration. Deterministic — no LLM calls, no randomness.

Input:
{
    "chartType": "bar",
    "title": "Spending by Category",
    "labelField": "category",
    "valueField": "total",
    "data": [
        {"category": "Airline", "total": 1200},
        {"category": "Hotel", "total": 980}
    ]
}

Output: A valid Chart.js v4 configuration object.
"""

import json

# ── Color palette (matches app design system) ─────────────────────────────────
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

VALID_CHART_TYPES = {"bar", "line", "pie", "doughnut"}


def get_colors(count):
    """Return a list of colors, cycling the palette if needed."""
    return [PALETTE[i % len(PALETTE)] for i in range(count)]


def validate_instruction(instruction):
    """Validate the chart instruction. Returns error string or None."""
    if not isinstance(instruction, dict):
        return "Instruction must be a JSON object"

    chart_type = instruction.get("chartType", "")
    if chart_type not in VALID_CHART_TYPES:
        return f"Invalid chartType '{chart_type}'. Must be one of: {', '.join(sorted(VALID_CHART_TYPES))}"

    data = instruction.get("data")
    if not data or not isinstance(data, list) or len(data) == 0:
        return "Data is required and must be a non-empty list"

    label_field = instruction.get("labelField", "")
    value_field = instruction.get("valueField", "")

    if not label_field:
        return "labelField is required"
    if not value_field:
        return "valueField is required"

    first_row = data[0]
    if not isinstance(first_row, dict):
        return "Each data row must be a JSON object"
    if label_field not in first_row:
        return f"labelField '{label_field}' not found in data. Available keys: {', '.join(first_row.keys())}"
    if value_field not in first_row:
        return f"valueField '{value_field}' not found in data. Available keys: {', '.join(first_row.keys())}"

    # Check values are numeric
    for i, row in enumerate(data):
        val = row.get(value_field)
        if val is not None and not isinstance(val, (int, float)):
            try:
                float(val)
            except (ValueError, TypeError):
                return f"Row {i}: valueField '{value_field}' is not numeric: {val}"

    return None


def extract_data(instruction):
    """Extract labels and values from the instruction data."""
    data = instruction["data"]
    label_field = instruction["labelField"]
    value_field = instruction["valueField"]

    labels = [str(row.get(label_field, "")) for row in data]
    values = [float(row.get(value_field, 0)) for row in data]

    return labels, values


def build_bar(instruction, labels, values):
    """Build a Chart.js bar chart config."""
    title = instruction.get("title", "Chart")
    colors = get_colors(len(values))

    return {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": title,
                "data": values,
                "backgroundColor": colors,
                "borderRadius": 4,
            }]
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": title,
                    "font": {"size": 16, "weight": "bold"},
                    "color": "#111827",
                },
                "legend": {"display": False},
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "grid": {"color": "rgba(0,0,0,0.06)"},
                    "ticks": {"color": "#6b7280"},
                },
                "x": {
                    "grid": {"display": False},
                    "ticks": {"color": "#6b7280"},
                },
            },
        },
    }


def build_line(instruction, labels, values):
    """Build a Chart.js line chart config."""
    title = instruction.get("title", "Chart")
    color = PALETTE[0]

    return {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": title,
                "data": values,
                "borderColor": color,
                "backgroundColor": color + "20",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 5,
                "pointBackgroundColor": color,
            }]
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": title,
                    "font": {"size": 16, "weight": "bold"},
                    "color": "#111827",
                },
                "legend": {"display": False},
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "grid": {"color": "rgba(0,0,0,0.06)"},
                    "ticks": {"color": "#6b7280"},
                },
                "x": {
                    "grid": {"display": False},
                    "ticks": {"color": "#6b7280"},
                },
            },
        },
    }


def build_pie(instruction, labels, values):
    """Build a Chart.js pie chart config."""
    title = instruction.get("title", "Chart")
    colors = get_colors(len(values))

    return {
        "type": "pie",
        "data": {
            "labels": labels,
            "datasets": [{
                "data": values,
                "backgroundColor": colors,
                "borderWidth": 2,
                "borderColor": "#ffffff",
            }]
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": title,
                    "font": {"size": 16, "weight": "bold"},
                    "color": "#111827",
                },
                "legend": {
                    "display": True,
                    "position": "right",
                    "labels": {"color": "#374151"},
                },
            },
        },
    }


def build_doughnut(instruction, labels, values):
    """Build a Chart.js doughnut chart config."""
    config = build_pie(instruction, labels, values)
    config["type"] = "doughnut"
    return config


# Chart type → builder function
BUILDERS = {
    "bar": build_bar,
    "line": build_line,
    "pie": build_pie,
    "doughnut": build_doughnut,
}


def handler(event, context):
    """
    Lambda handler. Accepts chart instruction, returns Chart.js config.

    Can be called directly via boto3 Lambda invoke (from the backend)
    or from a Bedrock Flow Lambda node.
    """
    # Support both direct invoke and Bedrock Flow invoke formats
    if "node" in event:
        # Bedrock Flow format
        try:
            raw = event["node"]["inputs"][0]["value"]
            instruction = json.loads(raw) if isinstance(raw, str) else raw
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return {"error": f"Could not parse Bedrock Flow input: {e}"}
    else:
        # Direct invoke format
        instruction = event

    # Validate
    err = validate_instruction(instruction)
    if err:
        return {"error": err}

    # Extract data
    labels, values = extract_data(instruction)

    # Build chart config
    chart_type = instruction["chartType"]
    builder = BUILDERS[chart_type]
    config = builder(instruction, labels, values)

    return {"chart": config, "error": None}
