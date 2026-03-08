# CertIQ Quiz App

A professional-grade quiz application designed for Google Cloud Professional Data Engineer certification preparation. This application uses a multi-tier serverless architecture on Google Cloud Platform (GCP) and features a premium dark glassmorphism UI.

## 🌟 What This Project Does

This project automatically extracts certification questions from official PDF study materials, stores them in a cloud database, and serves them through a high-performance REST API to a modern, responsive frontend application.

- **Content Ingestion**: Automatically parses CertyIQ PDF files uploaded to a Cloud Storage bucket, extracting questions, options, correct answers, and explanations.
- **Backend API**: Provides endpoints for paginated question retrieval, randomized quiz generation (with anti-cheat measures), answer submission scoring, and detailed performance breakdown.
- **Frontend UI**: A beautiful, interactive quiz interface built with Vanilla JS and CSS featuring animated glassmorphism cards, live scoring, progress tracking, and result rings.

## 🏗️ Architecture & Branching Strategy

To maintain clean separation of concerns and independent deployment lifecycles, this repository is organized into three distinct orphan branches. **The `master` branch only contains this README and a `.gitignore`.**

1. **`extraction` Branch (Data Pipeline)**
   - **Service:** Google Cloud Function (Gen 2, Python 3.11)
   - **Trigger:** Cloud Storage (`google.cloud.storage.object.v1.finalized`)
   - **Workflow:** When a PDF is uploaded to the designated bucket, the function awakens, parses the PDF using `pdfplumber`, and bulk inserts the parsed questions into MongoDB Atlas.

2. **`api` Branch (Backend Services)**
   - **Service:** Google Cloud Run (FastAPI, Python 3.11)
   - **Database:** MongoDB Atlas (Document DB)
   - **Workflow:** Serves a REST API over HTTPS for the frontend to consume. Connects securely to MongoDB. Built automatically from a Dockerfile.

3. **`frontend` Branch (User Interface)**
   - **Service:** Firebase Hosting (Static HTML/CSS/JS)
   - **Workflow:** Serves the highly optimized static assets globally via CDN. Configured to proxy all `/api/**` traffic directly to the Cloud Run service, avoiding CORS issues.

## 🚀 Getting Started

To deploy this project to your own GCP environment, follow these steps.

### Prerequisites
1. A Google Cloud Platform project with billing enabled.
2. A MongoDB Atlas cluster (free tier is fine).
3. Google Cloud CLI (`gcloud`) installed and configured.
4. Firebase CLI (`firebase`) installed.

### 1. Database Setup
1. Create a database named `QuizApp` in MongoDB Atlas.
2. Get your connection string (URI). Make sure your IP is whitelisted or allow access from anywhere (`0.0.0.0/0`) for cloud access.

### 2. Deploy the Data Pipeline
```bash
# Switch to the extraction branch
git checkout extraction

# Set your environment variables
export MONGO_URI="mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority"
export DB_NAME="QuizApp"

# Run the deployment script
bash deploy-extraction.sh
```

### 3. Deploy the Backend API
```bash
# Switch to the api branch
git checkout api

# Make sure MONGO_URI is still exported
# Run the deployment script
bash deploy-api.sh
```

### 4. Deploy the Frontend
```bash
# Switch to the frontend branch
git checkout frontend

# Run the deployment script (ensure you have run `firebase login` first)
bash deploy-frontend.sh
```

## 🎮 How to Use

Once deployed, the workflow is entirely automated:

1. **Add Questions**: Upload a CertyIQ format PDF to the Cloud Storage bucket created during step 2. The Cloud Function will automatically extract the questions and populate your MongoDB instance.
2. **Take a Quiz**: Visit your Firebase Hosting URL (e.g., `https://your-project.web.app`). Select the number of questions, choose a topic category, and start the quiz.
3. **Review Results**: At the end of the quiz, review your comprehensive score report including explanations for incorrect answers.
