import os
import csv
import json
import argparse
import google.generativeai as genai
from pymongo import MongoClient
from dotenv import load_dotenv

# Load local environment variables from .env file
load_dotenv()

MONGO_URI = os.environ.get("QUIZAPP_MONGO_URI", "")
DB_NAME = os.environ.get("DB_NAME", "QuizApp")
COLLECTION = os.environ.get("QUESTIONS_COLLECTION", "questions")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

mongo_client = None
if MONGO_URI:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30_000, tls=True)

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

def run_extraction(file_path):
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    file_name = os.path.basename(file_path)
    is_pdf = file_name.lower().endswith(".pdf")
    is_csv = file_name.lower().endswith(".csv")

    if not is_pdf and not is_csv:
        print(f"❌ Unsupported file format: {file_name}. Only .pdf and .csv are supported.")
        return

    print(f"📄 Processing local file: {file_path}")

    # Extract and Parse
    if is_pdf:
        questions = _process_pdf_gemini(file_path)
    else:
        questions = _process_csv(file_path)

    print(f"📋 Parsed {len(questions)} questions from '{file_name}'")

    if not questions:
        print("❌ No questions found or a parsing error occurred.")
        return

    # Store in MongoDB
    stored = _store(questions)
    print(f"✅ Done — {stored} documents inserted/updated in MongoDB '{DB_NAME}.{COLLECTION}'")


def _process_csv(file_path):
    print("Parsing CSV...")
    questions = []
    with open(file_path, mode='r', encoding='utf-8') as f:
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

                correct_raw = row.get("Correct Answer", "A")
                correct_list = [ans.strip().upper() for ans in correct_raw.split(",")]
                final_correct = correct_list if len(correct_list) > 1 else correct_list[0]

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
                    "certification_name": row.get("Certification", "UNKNOWN").strip()
                })
            except Exception as e:
                print(f"⚠️ Error parsing row {idx}: {e}")
                
    return questions


def _process_pdf_gemini(file_path):
    if not GEMINI_KEY:
        print("❌ GEMINI_API_KEY environment variable is not set! Check your .env file.")
        return []

    print("Uploading PDF to Gemini AI...")
    try:
        sample_file = genai.upload_file(path=file_path, mime_type="application/pdf")
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
    
    print("Generating question data with Gemini-flash-latest...")
    
    generation_config = {
        "max_output_tokens": 8192,
        "response_mime_type": "application/json",
    }
    
    model = genai.GenerativeModel(
        model_name='gemini-flash-latest',
        generation_config=generation_config
    )
    
    try:
        response = model.generate_content([sample_file, prompt])
        raw_json = response.text.strip()
        
        if raw_json.startswith("```json"):
            raw_json = raw_json[7:]
        if raw_json.endswith("```"):
            raw_json = raw_json[:-3]
        raw_json = raw_json.strip()
        
        questions = json.loads(raw_json)
        return questions
    except json.JSONDecodeError as de:
        print(f"❌ Failed to parse JSON from Gemini response: {de}")
        print(raw_json[:500] + "...") 
        return []
    except Exception as e:
        print(f"❌ Error communicating with Gemini: {e}")
        return []
        
        
def _store(questions: list) -> int:
    global mongo_client
    if not MONGO_URI or not mongo_client:
        print("❌ QUIZAPP_MONGO_URI environment variable is not set or client failed to initialize! Check your .env file.")
        return 0
        
    col = mongo_client[DB_NAME][COLLECTION]
    
    if questions:
        col.insert_many(questions)
        col.create_index("number", background=True)
        col.create_index("topic", background=True)
        col.create_index("certification_name", background=True)
        
    return len(questions)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract questions from a PDF or CSV and push to MongoDB.")
    parser.add_argument("file_path", help="Path to the .pdf or .csv file")
    args = parser.parse_args()
    
    run_extraction(args.file_path)
