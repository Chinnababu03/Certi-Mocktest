"""
Cloud Function entry point (main.py for GCP Cloud Functions)
Do NOT rename this file — Cloud Functions require main.py as entry module.
"""

import os
import re
import tempfile
import pdfplumber
from pymongo import MongoClient
from google.cloud import storage

MONGO_URI  = os.environ["MONGO_URI"]
DB_NAME    = os.environ.get("DB_NAME", "QuizApp")
COLLECTION = os.environ.get("QUESTIONS_COLLECTION", "questions")


def run_extraction(cloud_event, *args):
    """GCS object finalize trigger — called when a PDF is uploaded."""
    data        = cloud_event.data
    bucket_name = data["bucket"]
    file_name   = data["name"]

    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF: {file_name}")
        return

    print(f"📄 Processing: gs://{bucket_name}/{file_name}")

    # Download PDF to /tmp
    gcs    = storage.Client()
    bucket = gcs.bucket(bucket_name)
    blob   = bucket.blob(file_name)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        blob.download_to_filename(tmp_path)

    text      = _extract_text(tmp_path)
    questions = _parse(text)
    print(f"📋 Parsed {len(questions)} questions")

    if questions:
        stored = _store(questions)
        print(f"✅ Stored {stored} docs in MongoDB '{DB_NAME}.{COLLECTION}'")
    else:
        print("❌ No questions found — check PDF format.")


def _extract_text(path: str) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n".join(pages)


def _parse(text: str) -> list:
    text      = text.replace('\r\n', '\n')
    header_re = re.compile(r'(?im)^Question:\s*(\d+)\s+CertyIQ.*?$')
    headers   = list(header_re.finditer(text))
    if not headers:
        return []

    option_re      = re.compile(r'^([A-F])[.)]\s+(.+)$')
    answer_re      = re.compile(r'^Answer:\s*([A-F]+)', re.IGNORECASE)
    explanation_re = re.compile(r'^Explanation:\s*(.*)', re.IGNORECASE)
    questions      = []

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

        qt = " ".join(q_lines).strip()
        if qt and len(options) >= 2:
            questions.append({
                "number":      q_num,
                "question":    qt,
                "options":     options,
                "correct_ans": correct or list(options)[0],
                "explanation": " ".join(exp_lines).strip(),
            })
    return questions


def _store(questions: list) -> int:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30_000, tls=True)
    col    = client[DB_NAME][COLLECTION]
    col.delete_many({})
    col.insert_many(questions)
    col.create_index("number",      background=True)
    col.create_index("correct_ans", background=True)
    return len(questions)
