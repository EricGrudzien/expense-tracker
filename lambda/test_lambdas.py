"""Quick smoke tests for the deployed Lambda functions."""

import boto3
import json

client = boto3.client("lambda", region_name="us-east-1")


def invoke(function_name, payload):
    resp = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(resp["Payload"].read())
    status = resp["StatusCode"]
    return status, result


def test_json_parser():
    print("=" * 60)
    print("TEST: JSON Parser — markdown-fenced JSON")
    print("=" * 60)
    status, result = invoke("bedrock-flow-json-parser", {
        "node": {
            "inputs": [{
                "value": '```json\n{"classification": "CHART_REQUEST", "prompt": "Show a bar chart"}\n```'
            }]
        }
    })
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
    assert result.get("classification") == "CHART_REQUEST", f"FAIL: {result}"
    print("PASS\n")

    print("=" * 60)
    print("TEST: JSON Parser — raw JSON (no fences)")
    print("=" * 60)
    status, result = invoke("bedrock-flow-json-parser", {
        "node": {
            "inputs": [{
                "value": '{"classification": "DATA_QUERY", "prompt": "Show totals"}'
            }]
        }
    })
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
    assert result.get("classification") == "DATA_QUERY", f"FAIL: {result}"
    print("PASS\n")


def test_code_executor():
    print("=" * 60)
    print("TEST: Code Executor — simple print")
    print("=" * 60)
    code = 'print("Hello from Lambda!")'
    status, result = invoke("bedrock-flow-code-executor", {
        "node": {"inputs": [{"value": code}]}
    })
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
    assert result.get("success") is True, f"FAIL: {result}"
    assert "Hello from Lambda!" in result.get("output", ""), f"FAIL: {result}"
    print("PASS\n")

    print("=" * 60)
    print("TEST: Code Executor — blocked pattern (os.system)")
    print("=" * 60)
    code = 'import os\nos.system("whoami")'
    status, result = invoke("bedrock-flow-code-executor", {
        "node": {"inputs": [{"value": code}]}
    })
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
    assert result.get("success") is False, f"FAIL: {result}"
    assert "Blocked" in result.get("error", ""), f"FAIL: {result}"
    print("PASS\n")

    print("=" * 60)
    print("TEST: Code Executor — matplotlib chart")
    print("=" * 60)
    code = """import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.figure(figsize=(8, 5))
plt.bar(['Q1', 'Q2', 'Q3'], [100, 150, 130])
plt.title('Test Chart')
plt.savefig('/tmp/chart.png', dpi=150, bbox_inches='tight')
plt.close()
print('Chart generated')"""

    status, result = invoke("bedrock-flow-code-executor", {
        "node": {"inputs": [{"value": code}]}
    })
    print(f"Status: {status}")
    print(f"success: {result.get('success')}")
    print(f"output: {result.get('output')}")
    print(f"error: {result.get('error')}")
    print(f"images: {list(result.get('images', {}).keys())}")
    has_image = "chart.png" in result.get("images", {})
    print(f"Has chart.png: {has_image}")
    assert result.get("success") is True, f"FAIL: {result.get('error')}"
    assert has_image, "FAIL: no chart.png in images"
    print("PASS\n")

    print("=" * 60)
    print("TEST: Code Executor — pandas + numpy")
    print("=" * 60)
    code = """import pandas as pd
import numpy as np

df = pd.DataFrame({
    'category': ['airline', 'hotel', 'car'],
    'amount': [500.0, 300.0, 150.0]
})
print(f"Total: ${df['amount'].sum():,.2f}")
print(f"Mean: ${df['amount'].mean():,.2f}")
print(f"Std: ${np.std(df['amount']):,.2f}")"""

    status, result = invoke("bedrock-flow-code-executor", {
        "node": {"inputs": [{"value": code}]}
    })
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
    assert result.get("success") is True, f"FAIL: {result.get('error')}"
    assert "$950.00" in result.get("output", ""), f"FAIL: {result}"
    print("PASS\n")


if __name__ == "__main__":
    test_json_parser()
    test_code_executor()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
