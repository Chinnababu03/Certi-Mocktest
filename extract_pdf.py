"""
extract_pdf.py
--------------
Reads questions from CertIQprofessional-data-engineer.pdf and
stores each one as a document in MongoDB.

Each MongoDB document:
  {
    "number":      1,
    "question":    "Your company built a TensorFlow ...",
    "options":     {"A": "Threading", "B": "Serialization", ...},
    "correct_ans": "C",
    "explanation": "Bad performance of a model is either due to ..."
  }

Usage:
  python extract_pdf.py
"""

import os
import re
import pdfplumber
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────
MONGO_URI  = os.getenv("MONGO_URI",  "mongodb://localhost:27017")
DB_NAME    = os.getenv("DB_NAME",    "quizapp")
COLLECTION = os.getenv("QUESTIONS_COLLECTION", "questions")
PDF_PATH   = os.getenv("PDF_PATH",   "CertIQprofessional-data-engineer.pdf")


# ── Step 1: Extract raw text from PDF ──────────────────────────
def extract_text(path: str) -> str:
    all_pages = []
    print(f"📄  Opening: {path}")
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                all_pages.append(text)
            if (i + 1) % 20 == 0:
                print(f"    {i+1}/{total} pages read …")
    print(f"✅  Done reading {total} pages.")
    return "\n".join(all_pages)


# ── Step 2: Parse questions ────────────────────────────────────
def parse(text: str) -> list[dict]:
    """
    The PDF format is:
      Question: 1 CertyIQ
      <question text, may span multiple lines>
      A. <choice>
      B. <choice>
      C. <choice>
      D. <choice>
      Answer: C
      Explanation:
      <explanation text, may span multiple lines>
      (next question starts with "Question: 2 CertyIQ")
    """

    # Split on "Question: <N> CertyIQ" headers
    header_re = re.compile(r'(?im)^Question:\s*(\d+)\s+CertyIQ.*?$')
    headers   = list(header_re.finditer(text))

    if not headers:
        print("❌  No question headers found. Check the PDF.")
        return []

    print(f"📊  Found {len(headers)} question headers.")

    option_re      = re.compile(r'^([A-F])[.)]\s+(.+)$')
    answer_re      = re.compile(r'^Answer:\s*([A-F]+)', re.IGNORECASE)
    explanation_re = re.compile(r'^Explanation:\s*(.*)',  re.IGNORECASE)

    questions = []

    for idx, header in enumerate(headers):
        q_num = int(header.group(1))

        # Text block for this question (up to next header or end of text)
        start = header.end()
        end   = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        block = text[start:end]

        # ── Parse lines ────────────────────────────────────────
        q_lines   = []
        options   = {}
        correct   = ""
        exp_lines = []
        section   = "question"   # question → options → answer → explanation
        last_opt  = None

        for raw_line in block.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            opt_m = option_re.match(line)
            ans_m = answer_re.match(line)
            exp_m = explanation_re.match(line)

            if exp_m:
                section = "explanation"
                tail = exp_m.group(1).strip()
                if tail:
                    exp_lines.append(tail)

            elif ans_m:
                section = "answer"
                raw_ans = ans_m.group(1).upper()
                # Some answers are multi-letter (e.g., "BDF") – keep first letter
                correct = raw_ans[0]

            elif opt_m and section in ("question", "options"):
                section  = "options"
                last_opt = opt_m.group(1).upper()
                options[last_opt] = opt_m.group(2).strip()

            else:
                if section == "question":
                    q_lines.append(line)
                elif section == "options" and last_opt:
                    # continuation of previous option text
                    options[last_opt] += " " + line
                elif section == "explanation":
                    exp_lines.append(line)

        question_text = " ".join(q_lines).strip()

        # Skip blocks that didn't produce a valid question
        if not question_text or len(options) < 2:
            continue

        questions.append({
            "number":      q_num,
            "question":    question_text,
            "options":     options,
            "correct_ans": correct or (list(options)[0] if options else "A"),
            "explanation": " ".join(exp_lines).strip(),
        })

    return questions


# ── Step 3: Store in MongoDB ───────────────────────────────────
def store(questions: list[dict]) -> int:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=30_000,
        tls=True,
    )
    db  = client[DB_NAME]
    col = db[COLLECTION]

    # Drop existing data so we get a fresh seed every run
    deleted = col.delete_many({})
    if deleted.deleted_count:
        print(f"🗑️   Removed {deleted.deleted_count} old documents.")

    if not questions:
        print("⚠️   Nothing to insert.")
        return 0

    result = col.insert_many(questions)
    count  = len(result.inserted_ids)

    # Indexes for fast API queries
    col.create_index("number",      background=True)
    col.create_index("correct_ans", background=True)

    print(f"✅  Inserted {count} questions into "
          f"'{DB_NAME}.{COLLECTION}'")
    return count


# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  PDF → MongoDB Extractor")
    print("=" * 55)

    if not os.path.exists(PDF_PATH):
        print(f"❌  PDF not found: {PDF_PATH}")
        return

    text      = extract_text(PDF_PATH)
    questions = parse(text)

    print(f"\n📋  Parsed {len(questions)} questions.")

    if not questions:
        return

    # Quick preview of first 2
    for q in questions[:2]:
        print(f"\n── Q{q['number']} ──────────────────────────")
        print(f"   Q : {q['question'][:90]}…")
        for k, v in q["options"].items():
            tick = "✓" if k == q["correct_ans"] else " "
            print(f"  [{tick}] {k}: {v}")
        print(f"   Ans: {q['correct_ans']}")
        if q["explanation"]:
            print(f"   Exp: {q['explanation'][:80]}…")

    print("\n💾  Saving to MongoDB Atlas …")
    stored = store(questions)

    print("\n" + "=" * 55)
    print(f"  Done — {stored} documents stored.")
    print("=" * 55)


if __name__ == "__main__":
    main()
