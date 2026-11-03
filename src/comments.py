import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import time
import requests

CHANNEL_ID = "UC1TPHuTceK0ul-s697EWF2Q"
CREATOR_NAME = "Zoe Whitley"
STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
REPLIED_FILE = os.path.join(STATE_DIR, "replied.json")

def load_replied_ids():
    if os.path.exists(REPLIED_FILE):
        try:
            with open(REPLIED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("replied_ids", []))
        except Exception:
            return set()
    return set()

def save_replied_ids(replied_ids):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump({"replied_ids": sorted(list(replied_ids))}, f, indent=2)

def generate_friendly_reply(comment_text, gemini_api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_api_key}"
    headers = {"x-goog-api-key": gemini_api_key, "Content-Type": "application/json"}
    prompt = f"Write a very short, polite, warm 1-sentence reply as the YouTube creator {CREATOR_NAME} to this viewer comment: '{comment_text}'. Keep it natural, under 15 words."
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text
    except Exception:
        pass
    return "Thank you so much for watching and supporting the channel!"

def run_comment_responder(access_token, gemini_api_key, max_replies=10):
    print("[comments] Checking for new viewer comments on Channel 11...", flush=True)
    replied_ids = load_replied_ids()
    threads_url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "allThreadsRelatedToChannelId": CHANNEL_ID,
        "maxResults": 30,
        "order": "time"
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    res = requests.get(threads_url, headers=headers, params=params, timeout=20)
    if res.status_code != 200:
        print(f"[comments] Failed to fetch comment threads: {res.status_code}", flush=True)
        return

    items = res.json().get("items", [])
    replied_count = 0

    for item in items:
        if replied_count >= max_replies:
            break
        top = item.get("snippet", {}).get("topLevelComment", {})
        comment_id = top.get("id")
        snippet = top.get("snippet", {})
        author_channel = snippet.get("authorChannelId", {}).get("value")
        text = snippet.get("textDisplay", "")

        # Do not reply to self or already replied comments
        if author_channel == CHANNEL_ID or comment_id in replied_ids:
            continue

        # Filter spam or low quality comments
        t_clean = text.strip().lower()
        if len(t_clean) < 3 or any(w in t_clean for w in ["sub4sub", "whatsapp", "telegram", "crypto", "free money"]):
            continue

        reply_text = generate_friendly_reply(text, gemini_api_key)
        reply_url = "https://www.googleapis.com/youtube/v3/comments?part=snippet"
        reply_body = {
            "snippet": {
                "parentId": comment_id,
                "textOriginal": reply_text
            }
        }

        r_res = requests.post(reply_url, headers=headers, json=reply_body, timeout=15)
        if r_res.status_code in [200, 201]:
            replied_ids.add(comment_id)
            replied_count += 1
            print(f"[comments] Replied to comment {comment_id}: '{reply_text}'", flush=True)
            time.sleep(1.5)
        else:
            print(f"[comments] Reply failed for {comment_id}: {r_res.status_code}", flush=True)

    save_replied_ids(replied_ids)
    print(f"[comments] Completed comment run. Replied to {replied_count} new comment(s).", flush=True)

if __name__ == "__main__":
    from src.auth import get_access_token, get_gemini_api_key
    token = get_access_token()
    gemini_key = get_gemini_api_key()
    run_comment_responder(token, gemini_key)
