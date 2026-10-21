import os
import sys
import json
import time
import requests

def get_access_token():
    # If environment variables exist (CI or local environment)
    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN")

    # If missing in env, try reading from local tokens directory
    if not (client_id and client_secret and refresh_token):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Check both repo root and parent directory
        token_paths = [
            os.path.join(base_dir, "tokens", "token.json"),
            os.path.join(os.path.dirname(base_dir), "tokens", "token.json")
        ]
        cs_paths = [
            os.path.join(base_dir, "tokens", "client_secret.json"),
            os.path.join(os.path.dirname(base_dir), "tokens", "client_secret.json")
        ]

        token_file = next((p for p in token_paths if os.path.exists(p)), None)
        cs_file = next((p for p in cs_paths if os.path.exists(p)), None)

        if token_file and cs_file:
            with open(token_file, "r", encoding="utf-8") as f:
                tdata = json.load(f)
                refresh_token = tdata.get("refresh_token")
            with open(cs_file, "r", encoding="utf-8") as f:
                csdata = json.load(f)
                info = csdata.get("installed") or csdata.get("web") or {}
                client_id = info.get("client_id")
                client_secret = info.get("client_secret")

    if not (client_id and client_secret and refresh_token):
        raise ValueError("Missing OAuth credentials in env vars or local tokens directory.")

    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    for attempt in range(5):
        try:
            res = requests.post(token_url, data=payload, timeout=25)
            if res.status_code == 200:
                return res.json()["access_token"]
            elif res.status_code in [400, 401]:
                raise RuntimeError(f"OAuth token refresh rejected: {res.status_code} {res.text}")
        except requests.exceptions.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Failed to refresh Google access token after 5 attempts.")

def get_gemini_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        # Check if local file exists
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        key_paths = [
            os.path.join(base_dir, "tokens", "gemini_key.txt"),
            os.path.join(os.path.dirname(base_dir), "tokens", "gemini_key.txt")
        ]
        key_file = next((p for p in key_paths if os.path.exists(p)), None)
        if key_file:
            with open(key_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is not set.")
    return key
