"""
Code Execution Lambda for Bedrock Flows.

Receives LLM-generated Python code, executes it in a sandboxed subprocess,
and returns stdout output, any generated chart images (base64), and errors.
"""

import subprocess
import tempfile
import os
import re
import base64
import glob
import json


# Max output sizes to prevent memory issues
MAX_STDOUT = 10_000   # 10 KB
MAX_STDERR = 5_000    # 5 KB
TIMEOUT_SECONDS = 30

# Patterns that indicate potentially dangerous code
BLOCKED_PATTERNS = [
    r'\bos\.system\b',
    r'\bsubprocess\b',
    r'\bsocket\b',
    r'\brequests\b',
    r'\burllib\b',
    r'\b__import__\b',
    r'\beval\b',
    r'\bexec\b',
    r'\bopen\s*\([^)]*["\']\/(?!tmp)',  # open() on paths outside /tmp
]


def strip_code_fences(text):
    """Remove markdown code fences from LLM output."""
    cleaned = re.sub(r'^```(?:python)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    return cleaned


def scan_for_blocked_patterns(code):
    """Check code for potentially dangerous patterns. Returns list of violations."""
    violations = []
    for pattern in BLOCKED_PATTERNS:
        matches = re.findall(pattern, code)
        if matches:
            violations.append(f"Blocked pattern: {matches[0]}")
    return violations


def collect_images(directory="/tmp"):
    """Find and base64-encode any generated image files."""
    images = {}
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.svg"):
        for path in glob.glob(os.path.join(directory, ext)):
            filename = os.path.basename(path)
            try:
                with open(path, "rb") as f:
                    images[filename] = base64.b64encode(f.read()).decode()
                os.unlink(path)  # Clean up
            except Exception:
                pass
    return images


def handler(event, context):
    """
    Bedrock Flow Lambda handler.

    Input: event["node"]["inputs"][0]["value"] — raw code string from prompt node
    Output: {"success": bool, "output": str, "images": dict, "error": str|None}
    """
    try:
        raw = event.get("node", {}).get("inputs", [{}])[0].get("value", "")
    except (KeyError, IndexError):
        return {
            "success": False,
            "output": None,
            "images": {},
            "error": "Could not extract code from event input",
        }

    if not raw or not raw.strip():
        return {
            "success": False,
            "output": None,
            "images": {},
            "error": "No code provided",
        }

    # Strip markdown fences
    code = strip_code_fences(raw)

    # Security scan
    violations = scan_for_blocked_patterns(code)
    if violations:
        return {
            "success": False,
            "output": None,
            "images": {},
            "error": f"Code rejected — {'; '.join(violations)}",
        }

    # Clean up any leftover images from previous invocations
    for old in glob.glob("/tmp/*.png") + glob.glob("/tmp/*.jpg") + glob.glob("/tmp/*.svg"):
        try:
            os.unlink(old)
        except Exception:
            pass

    # Write code to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir="/tmp", delete=False
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        # Execute in a sandboxed subprocess
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd="/tmp",
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": "/tmp",
                "MPLBACKEND": "Agg",  # Non-interactive matplotlib
                "PYTHONPATH": os.environ.get("LAMBDA_TASK_ROOT", ""),
            },
        )

        # Collect any generated images
        images = collect_images("/tmp")

        return {
            "success": result.returncode == 0,
            "output": result.stdout[:MAX_STDOUT] if result.stdout else None,
            "images": images,
            "error": result.stderr[:MAX_STDERR] if result.returncode != 0 else None,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": None,
            "images": {},
            "error": f"Execution timed out ({TIMEOUT_SECONDS}s limit)",
        }
    except Exception as e:
        return {
            "success": False,
            "output": None,
            "images": {},
            "error": f"Execution error: {str(e)}",
        }
    finally:
        # Always clean up the temp script
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
