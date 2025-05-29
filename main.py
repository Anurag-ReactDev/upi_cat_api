# backend_app.py
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import re
from dotenv import load_dotenv
import base64,json
import pandas as pd
import tempfile
import requests
import fitz  # PyMuPDF
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PDF_PASSWORD = "9550521991"  # Update if needed
MODEL_API_URL = "https://model-cloud-api.onrender.com/predict"  # Replace with actual URL


load_dotenv()
app = FastAPI()

# === CORS (to allow frontend access) ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_credentials_dict():
    b64_creds = os.getenv("GOOGLE_CREDENTIALS_BASE64")
    if not b64_creds:
        raise Exception("GOOGLE_CREDENTIALS_BASE64 is not set")
    return json.loads(base64.b64decode(b64_creds))


def get_token_dict():
    b64_token = os.getenv("GOOGLE_TOKEN_BASE64")
    if not b64_token:
        raise Exception("GOOGLE_TOKEN_BASE64 is not set")
    return json.loads(base64.b64decode(b64_token))


def authenticate_gmail():
    creds = None
    try:
        token_info = get_token_dict()
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    except Exception as e:
        raise Exception("🔒 Failed to load credentials from env: " + str(e))

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("❌ Token expired or invalid — re-auth required")

    return build("gmail", "v1", credentials=creds)




# === Extract Text from PDF using PyMuPDF ===
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = "\n".join([page.get_text() for page in doc])
    doc.close()
    return text




def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    
    if doc.needs_pass:
        if not doc.authenticate(PDF_PASSWORD):
            raise ValueError("❌ PDF is encrypted and password authentication failed.")
    
    text = "\n".join([page.get_text() for page in doc])
    doc.close()
    return text

# === Endpoint 1: Fetch and extract data from Gmail ===
@app.get("/extract-transactions")
def extract_transactions():
    try:
        service = authenticate_gmail()
        query = 'label:transaction-statements has:attachment filename:pdf'
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])[::-1]

        os.makedirs("downloads", exist_ok=True)
        os.makedirs("processed", exist_ok=True)

        all_data = pd.DataFrame()

        for msg in messages:
            msg_id = msg['id']
            message = service.users().messages().get(userId='me', id=msg_id).execute()
            for part in message['payload'].get('parts', []):
                if part.get('filename', '').endswith('.pdf'):
                    att_id = part['body'].get('attachmentId')
                    attachment = service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
                    data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                    pdf_path = os.path.join("downloads", part['filename'])
                    with open(pdf_path, 'wb') as f:
                        f.write(data)
                    text = extract_text_from_pdf(pdf_path)
                    df = parse_transaction_text(text)
                    all_data = pd.concat([all_data, df], ignore_index=True)

        if all_data.empty:
            return {"message": "No transactions extracted."}

        all_data.to_csv("processed/unlabeled_transactions.csv", index=False)
        return {
            "columns": all_data.columns.tolist(),
            "data": all_data.to_dict(orient="records")
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# === Parse Text to Transactions ===
def parse_transaction_text(text):
    lines = text.split("\n")
    records = []

    i = 0
    while i < len(lines):
        if re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{2}, \d{4}$", lines[i]):
            try:
                date = lines[i].strip()
                time = lines[i + 1].strip()
                txn_line = lines[i + 2].strip()
                txn_type = lines[i + 6].strip()
                amount_line = lines[i + 7].strip()

                # Extract amount
                amount = float(amount_line.replace("INR", "").replace(",", "").strip())

                # Clean transaction text
                txn = re.sub(r"^(Paid to|Received from)\s*", "", txn_line, flags=re.I)

                records.append({
                    "Date & Time": f"{date} {time}",
                    "Transaction": txn,
                    "Type": txn_type,
                    "Amount": amount
                })

                i += 8  # Skip to next block
            except Exception as e:
                print(f"⚠️ Skipping block at line {i}: {e}")
                i += 1
        else:
            i += 1

    if not records:
        print("⚠️ No transactions found.")
        return pd.DataFrame(columns=["Date & Time", "Transaction", "Type", "Amount"])

    return pd.DataFrame(records)

## Endpoint 2: Send unlabeled CSV to Model API ===
@app.get("/predict-labels")
def send_csv_to_model():
    folder = "processed"
    csv_files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".csv")]

    if not csv_files:
        return JSONResponse(status_code=404, content={"error": "No extracted CSVs found"})

    latest_csv = sorted(csv_files, key=os.path.getmtime, reverse=True)[0]
    print(f"🕐 Using latest CSV: {latest_csv}")

    with open(latest_csv, "rb") as f:
        response = requests.post(MODEL_API_URL, files={"file": ("unlabeled_transactions.csv", f, "text/csv")})

    if response.status_code != 200:
        return JSONResponse(status_code=500, content={"error": "Model API failed", "details": response.text})

    return response.json()
