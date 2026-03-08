#!/bin/bash
# deploy-api.sh
# Deploys the FastAPI backend to Cloud Run
# Usage: bash deploy-api.sh
# Must be run from the api branch root

set -e

PROJECT_ID="linkifinity"
REGION="asia-south1"
SERVICE_NAME="certiq-api"

echo "=== Deploying Cloud Run: $SERVICE_NAME ==="
echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo ""

gcloud config set project $PROJECT_ID

# Deploy using source-based build (no need to push image manually)
gcloud run deploy $SERVICE_NAME \
  --source=. \
  --region=$REGION \
  --allow-unauthenticated \
  --port=8080 \
  --memory=512Mi \
  --cpu=1 \
  --set-env-vars="MONGO_URI=${MONGO_URI},DB_NAME=QuizApp,QUESTIONS_COLLECTION=questions,RESULTS_COLLECTION=quiz_results" \
  --project=$PROJECT_ID

echo ""
echo "✅ Cloud Run '$SERVICE_NAME' deployed!"
echo "   Get URL: gcloud run services describe $SERVICE_NAME --region=$REGION --format='value(status.url)'"
