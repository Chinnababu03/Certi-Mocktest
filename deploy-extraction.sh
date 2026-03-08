#!/bin/bash
# deploy-extraction.sh
# Deploys the Cloud Function (extraction branch) to GCP
# Usage: bash deploy-extraction.sh
# Must be run from the extraction branch root

set -e

PROJECT_ID="linkifinity"
REGION="asia-south1"
FUNCTION_NAME="certiq-extraction"
BUCKET="certiq-pdfs"
ENTRY_POINT="run_extraction"

echo "=== Deploying Cloud Function: $FUNCTION_NAME ==="
echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Trigger : gs://$BUCKET (object finalize)"
echo ""

# Ensure gcloud is configured for the right project
gcloud config set project $PROJECT_ID

# Create bucket if it doesn't exist
gcloud storage buckets describe gs://$BUCKET --project=$PROJECT_ID \
  > /dev/null 2>&1 || \
  gcloud storage buckets create gs://$BUCKET \
    --location=$REGION \
    --project=$PROJECT_ID

echo "✅ Bucket gs://$BUCKET is ready."

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=. \
  --entry-point=$ENTRY_POINT \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=$BUCKET" \
  --memory=512MB \
  --timeout=300s \
  --set-env-vars="DB_NAME=QuizApp,QUESTIONS_COLLECTION=questions" \
  --set-secrets="MONGO_URI=QUIZAPP_MONGO_URI:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --project=$PROJECT_ID

echo ""
echo "✅ Cloud Function '$FUNCTION_NAME' deployed!"
echo "   Upload a PDF to: gs://$BUCKET/your-file.pdf"
echo "   Then watch logs: gcloud functions logs read $FUNCTION_NAME --region=$REGION --gen2"
