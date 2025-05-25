from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import base64, json
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = os.path.expanduser("~/UPI_CATEGORISER_API/token.json")

def get_credentials_dict():
    b64_creds = os.getenv("GOOGLE_CREDENTIALS_BASE64")
    if not b64_creds:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 is not set")
    return json.loads(base64.b64decode(b64_creds))

def get_token_from_env():
    b64_token = os.getenv("GOOGLE_TOKEN_BASE64")
    if b64_token:
        try:
            data = json.loads(base64.b64decode(b64_token))
            return Credentials.from_authorized_user_info(data, SCOPES)
        except Exception as e:
            print(f"⚠️ Failed to parse token from env: {e}")
    return None

def main():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_dict = get_credentials_dict()
            flow = InstalledAppFlow.from_client_config(creds_dict, SCOPES)
            creds = flow.run_local_server(port=8080)
        # Save token to file system for future sessions (optional)
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
    print("✅ Authentication complete. Token saved.")
    return build("gmail", "v1", credentials=creds)


if __name__ == "__main__":
    main()
