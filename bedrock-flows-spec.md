# Bedrock Flows — Specification & Decisions

This document captures the architecture, design decisions, lessons learned, and
implementation details for the Bedrock Flow that classifies user input, generates
Python code, and executes it securely.

---

## 1. Overview

A Bedrock Flow that:
1. Classifies user input (e.g. chart request vs. data query)
2. Routes to the appropriate branch via a condition node
3. Generates Python code via a prompt node
4. Executes that code securely in a Lambda node
5. Returns the results (text output, images, or errors)

---

## 2. Flow Architecture

```
                         ┌──────────────────┐
                         │  Flow Input       │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │  Classification   │  Prompt Node
                         │  (LLM generates   │  → returns raw JSON string
                         │   JSON)            │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │  Lambda:          │  bedrock-flow-json-parser
                         │  Parse JSON       │  Strips fences, parses to object
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │  Condition Node   │  Routes on classification
                         │                   │  field value
                         └──┬──────────┬────┘
                            │          │
               ┌────────────▼──┐  ┌────▼────────────┐
               │ CHART_REQUEST │  │ Other branches   │
               │ Prompt Node   │  │ ...              │
               │ (generate     │  └─────────────────┘
               │  Python code) │
               └──────┬───────┘
                      │
               ┌──────▼───────┐
               │ Lambda:       │  bedrock-flow-code-executor
               │ Exec Python   │  Container image Lambda
               └──────┬───────┘
                      │
               ┌──────▼───────┐
               │ Flow Output   │
               └──────────────┘
```

---

## 3. File Structure

```
lambda/
  code-executor/
    Dockerfile              # Container image: Python 3.12 + matplotlib/numpy/pandas
    lambda_function.py      # Code execution Lambda handler
    build.sh                # Build, tag, push to ECR
  json-parser/
    lambda_function.py      # JSON parsing Lambda handler
    deploy.sh               # Zip and deploy to Lambda
  prompts/
    classification.txt      # Classification prompt template
    code-generation.txt     # Code generation prompt template
  flow-export.json          # Exported Bedrock Flow definition (nodes, connections, config)
  update_flow.py            # Script to push flow-export.json to Bedrock and prepare
  test_lambdas.py           # Smoke tests for deployed Lambdas (boto3)
```

---

## 4. Lessons Learned & Decisions

### 4.1 Prompt nodes always output STRING type

Bedrock Flow prompt nodes call a foundation model and return the raw text response as a
`STRING`. There is no built-in option to output a parsed JSON object. This means:

- Condition nodes cannot use JSONPath expressions (e.g. `$.data.classification`) directly
  on prompt node output
- A Lambda node is needed between the prompt node and the condition node to parse the
  string into a structured object

**Decision:** Use a Lambda node to parse JSON output from classification prompt nodes.

### 4.2 Model output often includes markdown code fences

Even when explicitly instructed not to, Claude may wrap JSON or code output in markdown
code blocks (`` ```json ... ``` `` or `` ```python ... ``` ``). This breaks downstream
parsing.

**Mitigations tried (in order):**

| Approach | Result |
|---|---|
| Prompt: "Return only raw JSON, no markdown" | Unreliable — model still adds fences sometimes |
| Prompt: "Response must start with `{` and end with `}`" | Better but not 100% reliable |
| Assistant prefill starting with `{` | Most reliable prompt-only approach, but not supported in all flow node UIs |
| Lambda node to strip fences and parse | Reliable — chosen approach |

**Decision:** Always use a Lambda cleanup node after prompt nodes that need structured
output. Both Lambda functions (json-parser and code-executor) strip markdown fences as
their first step. Cost is negligible (~$0.0000001 per invocation at 128MB/50ms).

### 4.3 Lambda response nesting

Lambda nodes in Bedrock Flows wrap the function return value. If the Lambda returns:
```json
{"output": {"classification": "CHART_REQUEST"}}
```

The condition node sees it at `$.data.document.output.classification`, not
`$.data.classification`.

**Decision:** Lambda functions return flat objects at the top level:
```python
return {"classification": "CHART_REQUEST", "prompt": "..."}
```
This places fields at `$.data.classification` where condition nodes expect them.

### 4.4 Condition node JSONPath expressions

Condition nodes evaluate JSONPath against the incoming data. The path is relative to the
node input binding.

**Key rule:** The Lambda return shape must match the JSONPath the condition expects. Keep
both flat and simple.

### 4.5 Library packaging — container image over Lambda layers

matplotlib + numpy + pandas together exceed the 250MB Lambda **total unzipped** limit.
This limit applies to the deployment package plus all layers combined — not per-layer.
You can attach up to 5 layers, but they share the same 250MB ceiling, so splitting across
multiple layers does not help.

Approximate unzipped sizes:

| Library    | Size (approx.) |
|------------|----------------|
| numpy      | ~75 MB         |
| pandas     | ~65 MB         |
| matplotlib | ~120 MB        |
| **Total**  | **~260 MB**    |

This exceeds 250MB before even adding the function code.

**Decision:** Use a container image Lambda for the code-executor. Container images support
up to 10GB, keep the architecture serverless, and give full control over the Python
environment.

### 4.7 Container image size and cold starts

The built container image is approximately **800MB–1GB**:

| Component                        | Size (approx.) |
|----------------------------------|----------------|
| Python 3.12 Lambda base image    | ~550 MB        |
| numpy                            | ~75 MB         |
| pandas                           | ~65 MB         |
| matplotlib + dependencies        | ~120 MB        |
| Function code                    | <1 MB          |
| **Total**                        | **~810 MB**    |

ECR storage cost: ~$0.08/month for this image.

**Cold start tradeoff:** A container image Lambda this size takes roughly 3–8 seconds on
first cold start vs. ~1 second for a zip-deployed Lambda. Warm invocations are unaffected.
If cold starts are a concern, use
[provisioned concurrency](https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html)
to keep instances warm (~$0.015/hour per instance).

### 4.6 Matplotlib backend

Lambda has no display server. `plt.show()` will fail.

**Decision:** Force `MPLBACKEND=Agg` via environment variable in both the Dockerfile and
the subprocess env. The code-generation prompt explicitly instructs the model to use
`plt.savefig()` and never `plt.show()`.

---

## 5. Lambda: JSON Parser (`lambda/json-parser/`)

### 5.1 Purpose

Sits between a prompt node and a condition node. Strips markdown code fences from the LLM
output and parses the JSON into a proper object so condition nodes can evaluate JSONPath
expressions against it.

### 5.2 Deployment

- **Runtime:** Python 3.12 (zip deployment, no dependencies beyond stdlib)
- **Memory:** 128 MB
- **Timeout:** 10 seconds
- **Function name:** `bedrock-flow-json-parser`

### 5.3 Deploy command

```bash
cd lambda/json-parser
./deploy.sh <aws-account-id> <region>
```

### 5.4 Input/Output

**Input:** `event["node"]["inputs"][0]["value"]` — raw string from prompt node

**Output:** Parsed JSON object (flat). Example:
```json
{"classification": "CHART_REQUEST", "prompt": "Show me a bar chart of Q1 sales"}
```

On parse failure, returns:
```json
{"error": "Failed to parse JSON: ...", "raw": "<first 500 chars>"}
```

### 5.5 Fence stripping logic

1. Strip leading `` ```json `` or `` ``` `` with optional newline
2. Strip trailing `` ``` `` with optional newline
3. Parse the cleaned string as JSON
4. If the result is a dict, return it directly (flat)
5. If the result is not a dict, wrap it: `{"value": <parsed>}`

---

## 6. Lambda: Code Executor (`lambda/code-executor/`)

### 6.1 Purpose

Executes LLM-generated Python code in a sandboxed subprocess and returns stdout output,
any generated chart images (base64-encoded), and errors.

### 6.2 Deployment

- **Package type:** Container image (ECR)
- **Base image:** `public.ecr.aws/lambda/python:3.12`
- **Installed libraries:** matplotlib 3.9.2, numpy 2.1.3, pandas 2.2.3
- **Memory:** 512 MB
- **Timeout:** 60 seconds (subprocess limited to 30s)
- **Function name:** `bedrock-flow-code-executor`

### 6.3 Build & deploy command

```bash
cd lambda/code-executor
./build.sh <aws-account-id> <region>
```

This builds the Docker image, creates the ECR repo (if needed), pushes the image, and
prints the `aws lambda create-function` command to run.

### 6.4 Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

RUN pip install --no-cache-dir \
    matplotlib==3.9.2 \
    numpy==2.1.3 \
    pandas==2.2.3 \
    --target "${LAMBDA_TASK_ROOT}"

ENV MPLBACKEND=Agg

COPY lambda_function.py ${LAMBDA_TASK_ROOT}

CMD ["lambda_function.handler"]
```

### 6.5 Input/Output

**Input:** `event["node"]["inputs"][0]["value"]` — raw code string from prompt node

**Output:**
```json
{
  "success": true,
  "output": "Total revenue: $309.3M\n",
  "images": {
    "chart.png": "<base64-encoded PNG>"
  },
  "error": null
}
```

On failure:
```json
{
  "success": false,
  "output": null,
  "images": {},
  "error": "NameError: name 'foo' is not defined"
}
```

### 6.6 Security layers

| Layer | Implementation | Purpose |
|---|---|---|
| **Code scanning** | Regex check for `os.system`, `subprocess`, `socket`, `requests`, `urllib`, `__import__`, `eval`, `exec`, `open()` outside `/tmp` | Block dangerous patterns before execution |
| **Timeout** | `subprocess.run(timeout=30)` | Kill runaway or infinite-loop code |
| **Stripped environment** | Only `PATH`, `HOME=/tmp`, `MPLBACKEND=Agg`, `PYTHONPATH` passed | No AWS credentials leaked to generated code |
| **Output size cap** | stdout truncated to 10KB, stderr to 5KB | Prevent memory exhaustion |
| **Image cleanup** | Old images deleted before execution, generated images deleted after collection | No data persists between invocations |
| **Temp file cleanup** | `finally: os.unlink(tmp_path)` | No code persists between invocations |
| **No network (optional)** | Lambda in VPC with no internet gateway | Prevent data exfiltration |

### 6.7 Blocked code patterns

The following regex patterns are scanned before execution. If any match, the code is
rejected without running:

| Pattern | Blocks |
|---|---|
| `\bos\.system\b` | Shell command execution |
| `\bsubprocess\b` | Process spawning |
| `\bsocket\b` | Network access |
| `\brequests\b` | HTTP requests |
| `\burllib\b` | URL fetching |
| `\b__import__\b` | Dynamic imports |
| `\beval\b` | Arbitrary code evaluation |
| `\bexec\b` | Arbitrary code execution |
| `\bopen\s*\([^)]*["\']\/(?!tmp)` | File access outside `/tmp` |

### 6.8 Image collection

After code execution, the Lambda scans `/tmp` for `*.png`, `*.jpg`, `*.jpeg`, and `*.svg`
files. Each found image is:
1. Read and base64-encoded
2. Added to the `images` dict keyed by filename
3. Deleted from `/tmp`

This supports multiple chart outputs from a single code execution.

---

## 7. Prompt Templates (`lambda/prompts/`)

### 7.1 Classification (`classification.txt`)

Classifies user input into: `CHART_REQUEST`, `DATA_QUERY`, or `GENERAL_QUESTION`.

Key instructions:
- Returns JSON with `classification` and `prompt` fields
- Explicitly told to start with `{` and end with `}`
- No markdown, no code blocks, no explanation

Template variable: `{{input}}` — the user's raw input.

### 7.2 Code Generation (`code-generation.txt`)

Generates executable Python code for the Lambda execution environment.

Key instructions:
- Available libraries: matplotlib, numpy, pandas
- Must use `matplotlib.use('Agg')` before importing pyplot
- Save charts to `/tmp/<name>.png` with `plt.savefig()`, never `plt.show()`
- Call `plt.close()` after saving to free memory
- Print text output to stdout
- No interactive functions (`input()`)
- No blocked imports (`os`, `subprocess`, `socket`, `requests`, `urllib`)
- Handle errors with try/except

Chart style guidelines (matching existing charting patterns):
- Clean color palette (tab10 or Set2)
- White figure background
- Gridlines for readability
- Dollar formatting with `$` prefix and commas
- `plt.tight_layout()` before saving

Template variable: `{{prompt}}` — the user's request (cleaned by classification step).

---

## 8. Condition Node Configuration

- **Input field:** `classification` bound to JSON parser Lambda output
- **Conditions:**
  - `classification == "CHART_REQUEST"` → code generation prompt → code executor Lambda
  - `classification == "DATA_QUERY"` → data query branch
  - Default → general response branch

---

## 9. Response Handling

### 9.1 Text output

When the generated code prints to stdout, the Lambda captures it in the `output` field
(truncated to 10KB). The flow output node passes this to the caller.

### 9.2 Chart/image output

When the generated code saves images to `/tmp/`:
1. The Lambda scans for `*.png`, `*.jpg`, `*.jpeg`, `*.svg`
2. Each file is base64-encoded and added to the `images` dict
3. Files are cleaned up after encoding
4. The caller decodes the base64 string and renders the image

Multiple images are supported (e.g. a script that generates 3 charts).

### 9.3 Error output

If the code fails (non-zero exit code, timeout, or blocked pattern):
- `success` is `false`
- `error` contains the reason (stderr, timeout message, or blocked pattern description)
- `output` may still contain partial stdout from before the failure
- `images` will be empty

---

## 10. Cost Considerations

| Component | Config | Cost per invocation (approx.) |
|---|---|---|
| Bedrock: classification prompt | ~200 input + ~50 output tokens | ~$0.003 |
| Lambda: JSON parser | 128MB, ~50ms | ~$0.0000001 |
| Bedrock: code generation prompt | ~500 input + ~300 output tokens | ~$0.005 |
| Lambda: code executor | 512MB, ~5s avg | ~$0.000004 |
| **Total per flow invocation** | | **~$0.008** |

Bedrock model calls dominate cost. Lambda costs are negligible. ECR storage for the
container image is ~$0.10/GB/month.

---

## 11. Deployment

### 11.1 Deployed Resources

| Resource | Type | ARN / URI |
|---|---|---|
| IAM Role | IAM Role | `arn:aws:iam::123456789012:role/bedrock-flow-lambda-role` |
| JSON Parser | Lambda (zip, Python 3.12) | `arn:aws:lambda:us-east-1:123456789012:function:bedrock-flow-json-parser` |
| Code Executor | Lambda (container image) | `arn:aws:lambda:us-east-1:123456789012:function:bedrock-flow-code-executor` |
| Container Image | ECR Repository | `123456789012.dkr.ecr.us-east-1.amazonaws.com/bedrock-flow-code-executor:latest` |

**Account:** 123456789012
**Region:** us-east-1

### 11.2 Deployment Steps (as executed)

#### Step 1: Create IAM execution role

```bash
aws iam create-role \
  --role-name bedrock-flow-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name bedrock-flow-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

This role has only basic Lambda execution permissions (CloudWatch Logs). No Bedrock, S3,
or other AWS service access — intentionally minimal since the code-executor Lambda runs
untrusted generated code.

#### Step 2: Deploy JSON parser Lambda (zip)

```bash
zip -j /tmp/json-parser.zip lambda/json-parser/lambda_function.py

aws lambda create-function \
  --function-name bedrock-flow-json-parser \
  --runtime python3.12 \
  --handler lambda_function.handler \
  --zip-file fileb:///tmp/json-parser.zip \
  --role arn:aws:iam::123456789012:role/bedrock-flow-lambda-role \
  --timeout 10 \
  --memory-size 128 \
  --region us-east-1
```

#### Step 3: Build code executor container image

```bash
cd lambda/code-executor
docker build --platform linux/amd64 --provenance=false \
  -t bedrock-flow-code-executor:latest .
```

**Important:** The `--provenance=false` flag is required. Without it, Docker produces a
multi-platform manifest list (OCI image index) which Lambda rejects with:
`The image manifest, config or layer media type for the source image is not supported.`
Adding `--provenance=false` produces a single-platform image that Lambda accepts.

#### Step 4: Push to ECR

```bash
aws ecr create-repository \
  --repository-name bedrock-flow-code-executor \
  --region us-east-1

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    123456789012.dkr.ecr.us-east-1.amazonaws.com

docker tag bedrock-flow-code-executor:latest \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/bedrock-flow-code-executor:latest

docker push \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/bedrock-flow-code-executor:latest
```

#### Step 5: Create code executor Lambda from container image

```bash
aws lambda create-function \
  --function-name bedrock-flow-code-executor \
  --package-type Image \
  --code ImageUri=123456789012.dkr.ecr.us-east-1.amazonaws.com/bedrock-flow-code-executor:latest \
  --role arn:aws:iam::123456789012:role/bedrock-flow-lambda-role \
  --timeout 60 \
  --memory-size 512 \
  --region us-east-1
```

#### Step 6: Verify both functions are Active

```bash
aws lambda get-function --function-name bedrock-flow-json-parser \
  --query "Configuration.State" --output text
# → Active

aws lambda get-function --function-name bedrock-flow-code-executor \
  --query "Configuration.State" --output text
# → Active
```

### 11.3 Smoke Tests

Tests are in `lambda/test_lambdas.py`. Run with:

```bash
python3 lambda/test_lambdas.py
```

Uses boto3 directly (not the AWS CLI) to avoid shell escaping issues with JSON payloads
that contain backticks and newlines.

#### Test results (all passed):

| Test | Function | Input | Result |
|---|---|---|---|
| Markdown-fenced JSON | json-parser | `` ```json\n{"classification":"CHART_REQUEST"}\n``` `` | Parsed correctly → `{"classification": "CHART_REQUEST"}` |
| Raw JSON (no fences) | json-parser | `{"classification":"DATA_QUERY"}` | Parsed correctly → `{"classification": "DATA_QUERY"}` |
| Simple print | code-executor | `print("Hello from Lambda!")` | `success: true`, output: `"Hello from Lambda!\n"` |
| Blocked pattern | code-executor | `import os; os.system("whoami")` | `success: false`, error: `"Code rejected — Blocked pattern: os.system"` |
| Matplotlib chart | code-executor | Bar chart with `plt.savefig('/tmp/chart.png')` | `success: true`, `images: {"chart.png": "<base64>"}` |
| Pandas + numpy | code-executor | DataFrame sum/mean/std | `success: true`, output: `"Total: $950.00\nMean: $316.67\nStd: $143.37\n"` |

### 11.4 Deployment Gotcha: Docker `--provenance=false`

When building container images for Lambda on Docker Desktop (or any BuildKit-enabled
Docker), the default build produces an OCI image index (manifest list) with provenance
attestations. Lambda does not support this format and rejects it with:

```
The image manifest, config or layer media type for the source image ... is not supported.
```

**Fix:** Always build with `--provenance=false`:
```bash
docker build --platform linux/amd64 --provenance=false -t <name> .
```

This produces a single-platform image with a standard Docker manifest that Lambda accepts.

### 11.5 Deployment Gotcha: Shell escaping for Lambda test payloads

Testing Lambda functions via `aws lambda invoke` with JSON payloads that contain backticks,
newlines, or nested quotes is error-prone due to shell escaping. The `\n` in a payload
like `` ```json\n{...}\n``` `` gets interpreted differently by `echo`, single quotes, and
double quotes in bash.

**Fix:** Use a Python script with boto3 for testing instead of the AWS CLI. The
`test_lambdas.py` script uses `json.dumps()` which handles all escaping correctly.

### 11.6 Remaining: Bedrock Flow wiring

The Lambdas are deployed and tested. The remaining step is to wire them into a Bedrock
Flow in the AWS console:

- [ ] Create Bedrock Flow with nodes:
  1. Flow Input node
  2. Classification prompt node (use `lambda/prompts/classification.txt`)
  3. JSON parser Lambda node → `bedrock-flow-json-parser`
  4. Condition node (routes on `classification` field)
  5. Code generation prompt node (use `lambda/prompts/code-generation.txt`)
  6. Code executor Lambda node → `bedrock-flow-code-executor`
  7. Flow Output node
- [ ] Grant Bedrock Flows permission to invoke both Lambda functions
- [ ] Test end-to-end with a chart request

---

## 12. Chat Backend Integration & Feature Flag

The expense tracker's chat backend (`POST /api/chat`) supports two routing modes,
controlled by a feature flag. This allows switching between direct Bedrock model calls
and the Bedrock Flow without code changes.

### 12.1 Feature flag

| Env Variable | Default | Description |
|---|---|---|
| `USE_BEDROCK_FLOW` | `false` | Set to `true` to route chat through Bedrock Flows |
| `BEDROCK_FLOW_ID` | `FNO4NHO5DT` | The Bedrock Flow identifier |
| `BEDROCK_FLOW_ALIAS` | `TSTALIASID` | The Flow alias identifier |
| `BEDROCK_MODEL` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Model ID for direct mode |
| `BEDROCK_REGION` | `us-east-1` | AWS region for all Bedrock calls |

**Usage:**
```bash
# Direct model mode (default)
python app.py

# Bedrock Flow mode
USE_BEDROCK_FLOW=true python app.py
```

### 12.2 Routing logic

The `POST /api/chat` endpoint checks `USE_BEDROCK_FLOW` and delegates to one of:

- **`chat_via_model(message)`** — the original two-call path: generate SQL → execute
  against SQLite → format answer. Uses `bedrock-runtime` client (`converse` API).
- **`chat_via_flow(message)`** — sends the message to the Bedrock Flow via
  `bedrock-agent-runtime` client (`invoke_flow` API). Collects the streamed response
  and normalizes it to the same `{answer, sql, data}` shape.

Both paths return the same JSON response structure to the frontend, so the UI works
identically regardless of mode.

### 12.3 Config endpoint

`GET /api/chat/config` returns the current routing mode:
```json
{"use_bedrock_flow": false, "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "flow_id": null}
```
or:
```json
{"use_bedrock_flow": true, "model": null, "flow_id": "FNO4NHO5DT"}
```

The chat page frontend fetches this on load and displays a badge: "Direct Model" (purple)
or "Bedrock Flow" (green).

### 12.4 Bedrock Flow invocation

The `invoke_flow` API returns a streaming response. The backend iterates over the
`responseStream` events and collects the `flowOutputEvent` document. If the flow returns
structured JSON (with `answer`, `sql`, `data` fields), those are used directly. If it
returns plain text, it's wrapped as `{answer: <text>, sql: null, data: null}`.

### 12.5 Chat logging

All chat requests and responses are logged to `backend/chat.log` (plain text, appended).

**Log format:**
```
<timestamp> | REQUEST  | mode=<model|flow> | message=<user message>
<timestamp> | RESPONSE | mode=<model|flow> | status=<http status> | sql=<generated SQL> | answer=<first 200 chars> | rows=<count>
```

**Examples:**
```
2026-04-28 18:30:15,123 | REQUEST | mode=model | message=What is my total spending?
2026-04-28 18:30:18,456 | RESPONSE | mode=model | status=200 | sql=SELECT SUM(amount) AS total FROM sub_expenses | answer=Your total spending is $4,500.00. | rows=1
2026-04-28 18:31:02,789 | REQUEST | mode=flow | message=Show me a bar chart of expenses
2026-04-28 18:31:08,012 | RESPONSE | mode=flow | status=200 | sql=N/A | answer=Here is your expense chart... | rows=0
```

Error responses include the error message:
```
2026-04-28 18:32:00,000 | RESPONSE | mode=model | status=400 | error=Generated query was rejected: Only SELECT queries are allowed
```

The logger uses a dedicated `chat` logger instance with a `FileHandler`, separate from
Flask's application logger. The log file is created automatically on first write.

---

## 14. Local Testing

The Lambda base image includes a built-in Runtime Interface Emulator (RIE) that simulates
the Lambda invoke API locally. No AWS credentials or deployment needed.

### 12.1 Build the image

```bash
cd lambda/code-executor
docker build --platform linux/amd64 -t code-executor:test .
```

### 12.2 Run the container

```bash
docker run --platform linux/amd64 -p 9000:8080 code-executor:test
```

The RIE listens on `http://localhost:9000`. Leave this running.

### 12.3 Test a chart generation

In another terminal:

```bash
curl -s -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "node": {
      "inputs": [{
        "value": "import matplotlib\nmatplotlib.use(\"Agg\")\nimport matplotlib.pyplot as plt\n\nplt.figure(figsize=(8,5))\nplt.bar([\"A\",\"B\",\"C\"], [10,20,15])\nplt.title(\"Test Chart\")\nplt.savefig(\"/tmp/chart.png\", dpi=150)\nplt.close()\nprint(\"Chart saved\")"
      }]
    }
  }' | python3 -m json.tool
```

Expected response:
```json
{
    "success": true,
    "output": "Chart saved\n",
    "images": {
        "chart.png": "<base64 string>"
    },
    "error": null
}
```

### 12.4 Test the security scan

```bash
curl -s -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "node": {
      "inputs": [{
        "value": "import os\nos.system(\"whoami\")"
      }]
    }
  }' | python3 -m json.tool
```

Expected response:
```json
{
    "success": false,
    "output": null,
    "images": {},
    "error": "Code rejected — Blocked pattern: os.system"
}
```

### 12.5 Save and view a generated chart

```bash
curl -s -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "node": {
      "inputs": [{
        "value": "import matplotlib\nmatplotlib.use(\"Agg\")\nimport matplotlib.pyplot as plt\nplt.figure()\nplt.plot([1,2,3],[4,5,6])\nplt.savefig(\"/tmp/chart.png\")\nplt.close()\nprint(\"done\")"
      }]
    }
  }' | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
if data.get('images', {}).get('chart.png'):
    with open('/tmp/test_chart.png', 'wb') as f:
        f.write(base64.b64decode(data['images']['chart.png']))
    print('Saved to /tmp/test_chart.png')
else:
    print('No image in response')
    print(json.dumps(data, indent=2))
"
```

Open `/tmp/test_chart.png` to verify the chart rendered correctly.

### 12.6 Stop the container

Press `Ctrl+C` in the terminal running the container, or:

```bash
docker stop $(docker ps -q --filter ancestor=code-executor:test)
```

---

## 15. Flow Definition Management

The Bedrock Flow definition can be exported as JSON, version-controlled, edited locally,
and pushed back to Bedrock via the API. This enables a code-first workflow for flow changes
without using the AWS console.

### 15.1 Exporting the flow definition

Use the `get_flow` API to capture the current flow definition:

```python
import boto3, json

client = boto3.client('bedrock-agent', region_name='us-east-1')
flow = client.get_flow(flowIdentifier='FNO4NHO5DT')

export = {
    'name': flow['name'],
    'description': flow.get('description', ''),
    'executionRoleArn': flow.get('executionRoleArn', ''),
    'definition': flow.get('definition', {}),
}

with open('lambda/flow-export.json', 'w') as f:
    json.dump(export, f, indent=2, default=str)
```

The exported JSON contains:
- **`name`** — the flow name
- **`executionRoleArn`** — the IAM role the flow uses
- **`definition`** — the full flow structure:
  - `nodes` — all nodes with their type, configuration, inputs, and outputs
  - `connections` — all edges between nodes with source/target mappings

### 15.2 Editing the flow locally

Edit `lambda/flow-export.json` directly. Common changes:
- **Change a prompt** — find the node by name, edit `configuration.prompt.sourceConfiguration.inline.templateConfiguration.text.value`
- **Add a node** — add an entry to `definition.nodes` with the appropriate type and config
- **Rewire connections** — edit `definition.connections` to change source/target node names and field mappings
- **Change a Lambda ARN** — find the Lambda node, update `configuration.lambdaFunction.lambdaArn`

### 15.3 Pushing changes with `update_flow.py`

The script at `lambda/update_flow.py` reads the export JSON, calls `update_flow`, and
then `prepare_flow` (with polling until ready).

**Preview (dry run):**
```bash
python lambda/update_flow.py --dry-run
```

**Push and prepare:**
```bash
python lambda/update_flow.py
```

**Push without preparing (useful if making multiple edits):**
```bash
python lambda/update_flow.py --no-prepare
```

**Target a different flow or file:**
```bash
python lambda/update_flow.py --flow-id ABCDEFGHIJ --file my-flow.json
```

### 15.4 The update → prepare → invoke cycle

After any change to the flow definition:

1. **`update_flow`** — pushes the new definition. Flow status becomes `NotPrepared`.
2. **`prepare_flow`** — validates and compiles the flow. Status becomes `Prepared` on
   success, or `Failed` with error details.
3. **`invoke_flow`** — can only be called when status is `Prepared`.

The `update_flow.py` script handles steps 1 and 2 automatically. If prepare fails, the
script prints the error and exits non-zero.

### 15.5 Workflow summary

```
Edit flow-export.json locally
        │
        ▼
python lambda/update_flow.py --dry-run     ← preview
        │
        ▼
python lambda/update_flow.py               ← push + prepare
        │
        ▼
Test via chat UI or curl                   ← invoke
        │
        ▼
git commit lambda/flow-export.json         ← version control
```

---

## 16. Future Enhancements

- **Code validation node**: Add a Lambda between code generation and execution that
  performs AST-level static analysis (beyond regex) to reject dangerous patterns
- **Retry with error feedback**: If code execution fails, loop back to the code generation
  prompt with the error message for a second attempt
- **Caching**: Cache classification results for identical inputs
- **Streaming**: Use Bedrock streaming for the code generation step to reduce perceived
  latency
- **ECS Fargate execution**: For stronger isolation, replace the execution Lambda with
  an ECS Fargate task running in a fully isolated container with no network access
- **Additional libraries**: Add scipy, seaborn, or plotly to the container image as needed
