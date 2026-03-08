"""
Cloud Function entry point — triggered when a PDF is uploaded to GCS bucket.
Branch: extraction
Deploy: gcloud functions deploy certiq-extraction (see deploy-extraction.sh)
"""

import os
import re
import tempfile
import pdfplumber
from pymongo import MongoClient
from google.cloud import storage

# ── Config from env vars set in Cloud Function ─────────────────
MONGO_URI   = os.environ["MONGO_URI"]
DB_NAME     = os.environ.get("DB_NAME", "QuizApp")
COLLECTION  = os.environ.get("QUESTIONS_COLLECTION", "questions")


def run_extraction(cloud_event, *args):
    """
    GCS trigger entry point.
    Fires on 'google.cloud.storage.object.v1.finalized' event.
    """
    data        = cloud_event.data
    bucket_name = data["bucket"]
    file_name   = data["name"]

    # Only process PDF files
    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF file: {file_name}")
        return

    print(f"📄 New PDF uploaded: gs://{bucket_name}/{file_name}")

    # 1. Download PDF to /tmp
    storage_client = storage.Client()
    bucket         = storage_client.bucket(bucket_name)
    blob           = bucket.blob(file_name)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        blob.download_to_filename(tmp_path)
        print(f"⬇️  Downloaded to {tmp_path}")

    # 2. Extract text
    text = _extract_text(tmp_path)

    # 3. Parse questions
    questions = _parse(text)
    print(f"📋 Parsed {len(questions)} questions from '{file_name}'")

    if not questions:
        print("❌ No questions found. Check PDF format.")
        return

    # 4. Store in MongoDB (namespaced by filename so different PDFs don't clash)
    stored = _store(questions)
    print(f"✅ Done — {stored} documents in MongoDB '{DB_NAME}.{COLLECTION}'")


# ── Helpers (same logic as local extract_pdf.py) ───────────────

def _extract_text(path: str) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n".join(pages)


def _parse(text: str) -> list:
    text       = text.replace('\r\n', '\n')
    header_re  = re.compile(r'(?im)^Question:\s*(\d+)\s+CertyIQ.*?$')
    headers    = list(header_re.finditer(text))

    if not headers:
        return []

    option_re      = re.compile(r'^([A-F])[.)]\s+(.+)$')
    answer_re      = re.compile(r'^Answer:\s*([A-F]+)', re.IGNORECASE)
    explanation_re = re.compile(r'^Explanation:\s*(.*)', re.IGNORECASE)

    questions = []

    for idx, header in enumerate(headers):
        q_num = int(header.group(1))
        start = header.end()
        end   = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        block = text[start:end]

        q_lines, options, correct, exp_lines = [], {}, "", []
        section, last_opt = "question", None

        for raw in block.split("\n"):
            line = raw.strip()
            if not line:
                continue
            opt_m = option_re.match(line)
            ans_m = answer_re.match(line)
            exp_m = explanation_re.match(line)

            if exp_m:
                section = "explanation"
                if exp_m.group(1).strip():
                    exp_lines.append(exp_m.group(1).strip())
            elif ans_m:
                section = "answer"
                correct = ans_m.group(1).upper()[0]
            elif opt_m and section != "explanation":
                section  = "options"
                last_opt = opt_m.group(1).upper()
                options[last_opt] = opt_m.group(2).strip()
            else:
                if section == "question":
                    q_lines.append(line)
                elif section == "options" and last_opt:
                    options[last_opt] += " " + line
                elif section == "explanation":
                    exp_lines.append(line)

        question_text = " ".join(q_lines).strip()
        if question_text and len(options) >= 2:
            questions.append({
                "number":      q_num,
                "question":    question_text,
                "options":     options,
                "correct_ans": correct or (list(options)[0] if options else "A"),
                "explanation": " ".join(exp_lines).strip(),
            })

    return questions


def _store(questions: list) -> int:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30_000, tls=True)
    col    = client[DB_NAME][COLLECTION]
    col.delete_many({})
    if questions:
        col.insert_many(questions)
        col.create_index("number",      background=True)
        col.create_index("correct_ans", background=True)
    return len(questions)
