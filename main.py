"""
FastAPI Backend for Quiz App
Run: uvicorn main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from models import QuizSubmission, QuizResult

load_dotenv()

# ── MongoDB Atlas ──────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME",   "QuizApp")
Q_COL     = os.getenv("QUESTIONS_COLLECTION", "questions")
R_COL     = os.getenv("RESULTS_COLLECTION",   "quiz_results")

import certifi
client       = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30_000, tls=True, tlsCAFile=certifi.where())
db           = client[DB_NAME]
questions_col = db[Q_COL]
results_col   = db[R_COL]

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="CertIQ Quiz API",
    description="PDF-powered GCP Professional Data Engineer quiz",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper ─────────────────────────────────────────────────────
def to_json(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


# ════════════════════════════════════════════════════════════════
# ROUTES
# ════════════════════════════════════════════════════════════════

@app.get("/api/health", tags=["Meta"])
def health():
    """Check API + DB connectivity."""
    return {
        "status": "ok",
        "db": DB_NAME,
        "collection": Q_COL,
        "total_questions": questions_col.count_documents({}),
    }


@app.get("/api/questions", tags=["Questions"])
def list_questions(
    page:  int = Query(1,  ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Paginated list of all questions (includes correct_ans — for admin/review).
    """
    skip  = (page - 1) * limit
    total = questions_col.count_documents({})
    docs  = [to_json(d) for d in questions_col.find().skip(skip).limit(limit)]
    return {
        "page":        page,
        "limit":       limit,
        "total":       total,
        "total_pages": (total + limit - 1) // limit,
        "questions":   docs,
    }


@app.get("/api/metadata", tags=["Meta"])
def get_metadata():
    """
    Returns available certifications, their topics, and problem counts.
    Used to populate frontend dropdowns.
    """
    pipeline = [
        {
            "$group": {
                "_id": {
                    "cert": "$certification_name",
                    "topic": "$topic"
                },
                "count": {"$sum": 1}
            }
        },
        {
            "$group": {
                "_id": "$_id.cert",
                "topics": {
                    "$push": {
                        "topic": "$_id.topic",
                        "count": "$count"
                    }
                },
                "total_count": {"$sum": "$count"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "certification_name": "$_id",
                "topics": 1,
                "total_count": 1
            }
        },
        {"$sort": {"certification_name": 1}}
    ]
    
    metadata = list(questions_col.aggregate(pipeline))
    return {"metadata": metadata}


@app.get("/api/quiz", tags=["Quiz"])
def get_quiz(
    count: int = Query(10, ge=1, le=100),
    cert: str = Query(None, description="Filter by certification_name"),
    topic: str = Query(None, description="Filter by topic")
):
    """
    Return `count` random questions for a quiz session.
    correct_ans is NOT included in the response (anti-cheat).
    Accepts optional cert and topic filters.
    """
    match_stage = {}
    if cert:
        match_stage["certification_name"] = cert
    if topic:
        match_stage["topic"] = topic

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
        
    pipeline.append({"$sample": {"size": count}})

    docs = list(questions_col.aggregate(pipeline))
    if not docs:
        raise HTTPException(
            status_code=404,
            detail="No matching questions found for the given criteria."
        )

    quiz_questions = [
        {
            "_id":      str(d["_id"]),
            "number":   d.get("number"),
            "question": d.get("question"),
            "options":  d.get("options", {}),
            "topic":    d.get("topic", "General")
        }
        for d in docs
    ]

    return {
        "session_id": str(uuid.uuid4()),
        "total":      len(quiz_questions),
        "questions":  quiz_questions,
    }


@app.post("/api/submit", response_model=QuizResult, tags=["Quiz"])
def submit_quiz(submission: QuizSubmission):
    """
    Submit answers for a quiz session.
    Returns score, percentage, and per-question feedback with explanations.
    Body: { "session_id": "...", "answers": [{ "question_id": "...", "selected_answer": "A" }] }
    """
    if not submission.answers:
        raise HTTPException(status_code=400, detail="No answers provided.")

    details = []
    score   = 0

    for ans in submission.answers:
        # Lookup question by _id
        try:
            doc = questions_col.find_one({"_id": ObjectId(ans.question_id)})
        except Exception:
            continue
        if not doc:
            continue

        correct    = doc.get("correct_ans", "")
        selected   = (ans.selected_answer or "").upper()
        is_correct = selected == correct.upper()
        if is_correct:
            score += 1

        details.append({
            "question_id":     ans.question_id,
            "number":          doc.get("number"),
            "question":        doc.get("question"),
            "options":         doc.get("options", {}),
            "selected_answer": selected,
            "correct_answer":  correct,
            "is_correct":      is_correct,
            "explanation":     doc.get("explanation", ""),
        })

    total      = len(details)
    percentage = round((score / total) * 100, 1) if total > 0 else 0.0

    # Persist result
    results_col.insert_one({
        "session_id": submission.session_id,
        "score":      score,
        "total":      total,
        "percentage": percentage,
        "details":    details,
        "timestamp":  datetime.utcnow(),
    })

    return QuizResult(
        session_id=submission.session_id,
        score=score,
        total=total,
        percentage=percentage,
        details=details,
    )


@app.get("/api/results/{session_id}", tags=["Quiz"])
def get_result(session_id: str):
    """Fetch a past quiz result by session_id."""
    doc = results_col.find_one({"session_id": session_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Result not found.")
    if "timestamp" in doc:
        doc["timestamp"] = doc["timestamp"].isoformat()
    return doc


@app.get("/", tags=["Meta"])
def read_root():
    return {"status": "CertIQ API is running. Access endpoints via /api"}
