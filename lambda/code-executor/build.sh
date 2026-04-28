#!/bin/bash
# Build and push the code-executor Lambda container image to ECR.
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - Docker running
#
# Usage:
#   ./build.sh <aws-account-id> <region>
#
# Example:
#   ./build.sh 123456789012 us-east-1

set -euo pipefail

ACCOUNT_ID="${1:?Usage: ./build.sh <aws-account-id> <region>}"
REGION="${2:-us-east-1}"
REPO_NAME="egru-bedrock-flow-code-executor"
IMAGE_TAG="latest"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"

echo "── Building Docker image ──"
docker build --platform linux/amd64 -t "${REPO_NAME}:${IMAGE_TAG}" .

echo "── Creating ECR repository (if needed) ──"
aws ecr describe-repositories --repository-names "${REPO_NAME}" --region "${REGION}" 2>/dev/null \
  || aws ecr create-repository --repository-name "${REPO_NAME}" --region "${REGION}"

echo "── Logging in to ECR ──"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "── Tagging and pushing ──"
docker tag "${REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

echo ""
echo "✅ Image pushed to: ${ECR_URI}:${IMAGE_TAG}"
echo ""
echo "Create the Lambda function with:"
echo "  aws lambda create-function \\"
echo "    --function-name ${REPO_NAME} \\"
echo "    --package-type Image \\"
echo "    --code ImageUri=${ECR_URI}:${IMAGE_TAG} \\"
echo "    --role arn:aws:iam::${ACCOUNT_ID}:role/<your-lambda-role> \\"
echo "    --timeout 60 \\"
echo "    --memory-size 512 \\"
echo "    --region ${REGION}"
