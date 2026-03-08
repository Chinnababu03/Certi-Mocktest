# CertIQ Quiz App

A professional-grade quiz app for Google Professional Data Engineer certification prep, powered by AI-extracted questions.

## Repository Structure

This repository is split into three branches, each responsible for a different part of the architecture:

- **[`extraction`](https://github.com/TODO/tree/extraction)**: Cloud Function (Python) triggered by GCS PDF uploads to parse and store questions in MongoDB.
- **[`api`](https://github.com/TODO/tree/api)**: Cloud Run FastAPI backend that serves the questions and handles quiz logic.
- **[`frontend`](https://github.com/TODO/tree/frontend)**: Firebase Hosting static frontend (HTML/CSS/JS) with a premium dark glassmorphism theme.

## Deployment

Please check out the respective branches for deployment scripts and specific code for each service.
