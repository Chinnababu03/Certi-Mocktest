from pydantic import BaseModel
from typing import Optional, List


class SubmitAnswerItem(BaseModel):
    question_id: str      # MongoDB _id as string
    selected_answer: str  # e.g. "A"


class QuizSubmission(BaseModel):
    session_id: str
    answers: List[SubmitAnswerItem]


class QuizResult(BaseModel):
    session_id: str
    score: int
    total: int
    percentage: float
    details: List[dict]
