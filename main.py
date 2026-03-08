"""
Cloud Function entry point — triggered when a file is uploaded to GCS bucket.
Branch: extraction
Deploy: gcloud functions deploy certiq-extraction (see deploy-extraction.sh)
"""

import os
import csv
import json
import tempfile
import google.generativeai as genai
from pymongo import MongoClient
from google.cloud import storage

# ── Config from env vars set in Cloud Function ─────────────────
MONGO_URI   = os.environ.get("MONGO_URI", "")
DB_NAME     = os.environ.get("DB_NAME", "QuizApp")
COLLECTION  = os.environ.get("QUESTIONS_COLLECTION", "questions")
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")

# Global client for warm-start reuse
mongo_client = None
if MONGO_URI:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30_000, tls=True)

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

def run_extraction(event_payload, context=None):
    """
    GCS trigger entry point.
    Fires on 'google.cloud.storage.object.v1.finalized' event.
    """
    # Functions Framework sometimes passes a raw dict (legacy) or a CloudEvent object
    if isinstance(event_payload, dict):
        data = event_payload
    else:
        data = event_payload.data
        if isinstance(data, bytes):
            data = json.loads(data)

    bucket_name = data.get("bucket", "")
    file_name   = data.get("name", "")

    # Check extension
    is_pdf = file_name.lower().endswith(".pdf")
    is_csv = file_name.lower().endswith(".csv")

    if not is_pdf and not is_csv:
        print(f"Skipping unsupported file format: {file_name}")
        return

    print(f"📄 New file uploaded: gs://{bucket_name}/{file_name}")

    # 1. Download file to /tmp
    storage_client = storage.Client()
    bucket         = storage_client.bucket(bucket_name)
    blob           = bucket.blob(file_name)

    ext = ".pdf" if is_pdf else ".csv"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        blob.download_to_filename(tmp_path)
        print(f"⬇️  Downloaded to {tmp_path}")

    # 2. Extract and Parse
    if is_pdf:
        questions = _process_pdf_gemini(tmp_path)
    else:
        questions = _process_csv(tmp_path)

    print(f"📋 Parsed {len(questions)} questions from '{file_name}'")

    if not questions:
        print("❌ No questions found or a parsing error occurred.")
        return

    # 3. Store in MongoDB
    stored = _store(questions)
    print(f"✅ Done — {stored} documents inserted/updated in MongoDB '{DB_NAME}.{COLLECTION}'")


def _process_csv(tmp_path):
    print("Parsing CSV...")
    questions = []
    with open(tmp_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            try:
                options = {}
                if "Option A" in row and row["Option A"].strip(): options["A"] = row["Option A"].strip()
                if "Option B" in row and row["Option B"].strip(): options["B"] = row["Option B"].strip()
                if "Option C" in row and row["Option C"].strip(): options["C"] = row["Option C"].strip()
                if "Option D" in row and row["Option D"].strip(): options["D"] = row["Option D"].strip()
                if "Option E" in row and row["Option E"].strip(): options["E"] = row["Option E"].strip()
                if "Option F" in row and row["Option F"].strip(): options["F"] = row["Option F"].strip()

                # Handle multi-select like "B, C, D" gracefully
                correct_raw = row.get("Correct Answer", "A")
                correct_list = [ans.strip().upper() for ans in correct_raw.split(",")]
                
                # If only 1 correct answer, leave as a string. If multiple, store as an Array of strings.
                final_correct = correct_list if len(correct_list) > 1 else correct_list[0]

                # Ensure minimum fields
                number = row.get("Number", idx + 1)
                try: 
                    number = int(number)
                except ValueError: 
                    number = idx + 1

                questions.append({
                    "number": number,
                    "question": row.get("Question", "").strip(),
                    "options": options,
                    "correct_ans": final_correct,
                    "explanation": row.get("Explanation", "").strip(),
                    "topic": row.get("Topic", "General").strip(),
                    "certification_name": row.get("Certification", "gcp-pde").strip()
                })
            except Exception as e:
                print(f"⚠️ Error parsing row {idx}: {e}")
                
    return questions


def _process_pdf_gemini(tmp_path):
    if not GEMINI_KEY:
        print("❌ GEMINI_API_KEY environment variable is not set! Cannot process PDF.")
        return []

    print("Uploading PDF to Gemini AI...")
    try:
        sample_file = genai.upload_file(path=tmp_path, mime_type="application/pdf")
    except Exception as e:
        print(f"❌ Failed to upload PDF to Gemini: {e}")
        return []
    
    prompt = '''
    You are an expert IT certification parsing system. 
    Analyze the attached certification exam PDF. Extract ALL questions from it into a strictly formatted JSON array.
    
    For EVERY multiple-choice question, you must extract:
    1. "number": The integer question number.
    2. "question": The question text.
    3. "options": A dictionary of options with keys "A", "B", "C", "D", etc.
    4. "correct_ans": THIS IS CRITICAL. If it is a single-select question, return a single string like "B". If the question explicitly says "Choose two" or "Choose three", and multiple answers are correct, you MUST return an array of strings like ["B", "C", "D"]. DO NOT truncate multiple answers to a single letter.
    5. "explanation": The explanation text if provided.
    6. "topic": Consolidate the question topic into a consistent single phrase (e.g., "Networking", "IAM", "BigQuery", "Machine Learning", "Databases").
    7. "certification_name": Deduce a short, slug-style certification exam name from the document (e.g., "gcp-pde" for Professional Data Engineer, "gcp-pca" for Professional Cloud Architect) and apply it to ALL questions.

    CRITICAL RULES:
    - ONLY output valid JSON array syntax.
    - Start immediately with [ and end with ]. 
    - DO NOT use markdown format blocks like ```json.
    - DO NOT include any plain text explanation.
    - Ensure EVERY single question in the document is extracted.
    '''
    
    print("Generating question data with Gemini...")
    
    # Debug: List available models
    try:
        print("Listing available models for this API key:")
        for m in genai.list_models():
            print(f" - {m.name}")
    except Exception as e:
        print(f"⚠️ Could not list models: {e}")

    model = genai.GenerativeModel(model_name='gemini-1.5-flash')
    
    try:
        response = model.generate_content([sample_file, prompt])
        raw_json = response.text.strip()
        
        # Clean markdown if generated
        if raw_json.startswith("```json"):
            raw_json = raw_json[7:]
        if raw_json.endswith("```"):
            raw_json = raw_json[:-3]
        raw_json = raw_json.strip()
        
        questions = json.loads(raw_json)
        return questions
    except json.JSONDecodeError as de:
        print(f"❌ Failed to parse JSON from Gemini response: {de}")
        print(raw_json[:500] + "...") # Print snippet for debugging
        return []
    except Exception as e:
        print(f"❌ Error communicating with Gemini: {e}")
        return []
        
        
def _store(questions: list) -> int:
    global mongo_client
    if not MONGO_URI or not mongo_client:
        print("❌ MONGO_URI environment variable is not set or client failed to initialize!")
        return 0
        
    col = mongo_client[DB_NAME][COLLECTION]
    
    # We will simply append these questions to the database for this project iteration
    # rather than wiping the DB completely like the original script did, 
    # so we can support uploading multiple overlapping cert PDFs/CSVs over time.
    if questions:
        col.insert_many(questions)
        col.create_index("number", background=True)
        col.create_index("topic", background=True)
        col.create_index("certification_name", background=True)
        
    return len(questions)
