"""
JSON Parser Lambda for Bedrock Flows.

Sits between a prompt node and a condition node. Strips markdown code fences
from the LLM output and parses the JSON into a proper object so condition
nodes can evaluate JSONPath expressions against it.
"""

import json
import re


def handler(event, context):
    """
    Input:  event["node"]["inputs"][0]["value"] — raw string from prompt node
    Output: parsed JSON object (flat, top-level keys land at $.data.<key>)
    """
    try:
        text = event["node"]["inputs"][0]["value"]
    except (KeyError, IndexError):
        return {"error": "Could not extract input from event"}

    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse JSON: {str(e)}", "raw": text[:500]}

    # Return flat — fields land at $.data.<field> for condition nodes
    if isinstance(parsed, dict):
        return parsed
    else:
        return {"value": parsed}
