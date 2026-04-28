"""Update the inline code node in flow-export.json and push to Bedrock."""

import json
import os

EXPORT_PATH = os.path.join(os.path.dirname(__file__), "flow-export.json")
NODE_NAME = "InlineCode_Transform_Data"

# The inline code to set — proper indentation guaranteed here
INLINE_CODE = (
    "import re\n"
    "\n"
    "def __func():\n"
    "    text = variable\n"
    "    cleaned = re.sub(r'^```(?:sql)?\\s*\\n?', '', text.strip())\n"
    "    cleaned = re.sub(r'\\n?```\\s*$', '', cleaned)\n"
    "    return {\"response\": cleaned, \"type\": \"sql_query\"}\n"
    "\n"
    "__func()\n"
)

def main():
    with open(EXPORT_PATH) as f:
        export = json.load(f)

    found = False
    for node in export["definition"]["nodes"]:
        if node["name"] == NODE_NAME:
            node["configuration"]["inlineCode"]["code"] = INLINE_CODE
            found = True
            break

    if not found:
        print(f"Error: Node '{NODE_NAME}' not found in flow export")
        return

    with open(EXPORT_PATH, "w") as f:
        json.dump(export, f, indent=2, default=str)

    print(f"Updated '{NODE_NAME}' in {EXPORT_PATH}")
    print()
    print("Code set to:")
    print(INLINE_CODE)
    print()
    print("Now run: python lambda/update_flow.py")


if __name__ == "__main__":
    main()
