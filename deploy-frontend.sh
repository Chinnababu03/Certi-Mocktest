#!/bin/bash
# deploy-frontend.sh
# Deploys the frontend to Firebase Hosting
# Usage: bash deploy-frontend.sh
# Must be run from the frontend branch root
# Prerequisites: firebase-tools installed (npm install -g firebase-tools)

set -e

PROJECT_ID="linkifinity"

echo "=== Deploying Frontend to Firebase Hosting ==="
echo "Project : $PROJECT_ID"
echo ""

firebase use $PROJECT_ID
firebase deploy --only hosting

echo ""
echo "✅ Frontend deployed to Firebase Hosting!"
echo "   Visit: https://$PROJECT_ID.web.app"
