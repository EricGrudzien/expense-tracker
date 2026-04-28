#!/bin/bash
# Package and deploy the json-parser Lambda as a zip.
#
# Usage:
#   ./deploy.sh <aws-account-id> <region>
#
# Example:
#   ./deploy.sh 123456789012 us-east-1

set -euo pipefail

ACCOUNT_ID="${1:?Usage: ./deploy.sh <aws-account-id> <region>}"
REGION="${2:-us-east-1}"
FUNCTION_NAME="bedrock-flow-json-parser"

echo "── Packaging ──"
zip -j function.zip lambda_function.py

echo "── Creating or updating Lambda ──"
if aws lambda get-function --function-name "${FUNCTION_NAME}" --region "${REGION}" 2>/dev/null; then
  echo "Updating existing function..."
  aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file fileb://function.zip \
    --region "${REGION}"
else
  echo "Creating new function..."
  aws lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.12 \
    --handler lambda_function.handler \
    --zip-file fileb://function.zip \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/<your-lambda-role>" \
    --timeout 10 \
    --memory-size 128 \
    --region "${REGION}"
fi

rm -f function.zip

echo ""
echo "✅ Lambda deployed: ${FUNCTION_NAME}"
