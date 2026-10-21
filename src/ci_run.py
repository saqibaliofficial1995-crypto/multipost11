import os
import sys
import json
import time
import argparse
import requests

from src.auth import get_access_token, get_gemini_api_key
from src.drive_client import list_pending_videos, download_video, get_or_create_uploaded_folder, move_to_uploaded
from src.normalize import get_video_duration, normalize_video
from src.llm_meta import generate_video_metadata
from src.yt_client import upload_video_resumable

def load_config(config_path="config.json"):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base_dir, config_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {
        "made_for_kids": False,
        "privacy_status": "public",
        "default_language": "en",
        "max_uploads_per_run": 1,
        "drive_folder_id": "1d3WNdfdbYn0Jdxq9XICOrlC61FNpShME",
        "ai_provider": "gemini",
        "model": "gemini-flash-lite-latest"
    }

def load_state(state_file):
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": {}, "history": []}

def save_state(state, state_file):
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w", encoding="utf-8-sig") as f:
        json.dump(state, f, indent=2)

def get_uploaded_ids(state):
    uploaded = set()
    items = state.get("items", {})
    if isinstance(items, dict):
        for fid, entry in items.items():
            if isinstance(entry, dict):
                if entry.get("youtube_video_id") or entry.get("uploaded_at_utc"):
                    uploaded.add(fid)
            elif isinstance(entry, str) and entry.strip():
                uploaded.add(fid)
    for entry in state.get("history", []):
        if isinstance(entry, dict):
            fid = entry.get("drive_file_id") or entry.get("id")
            if fid and (entry.get("youtube_video_id") or entry.get("uploaded_at_utc")):
                uploaded.add(fid)
    return uploaded

def run_pipeline(dry_run=False, max_uploads=1, config_path="config.json"):
    print(f"[ci_run] Starting pipeline run (dry_run={dry_run}, max_uploads={max_uploads})...", flush=True)
    config = load_config(config_path)

    folder_id = os.environ.get("DRIVE_FOLDER_ID") or config.get("drive_folder_id")
    if not folder_id:
        raise ValueError("DRIVE_FOLDER_ID not provided.")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state_file = os.path.join(base_dir, "state", "uploaded.json")
    state = load_state(state_file)
    uploaded_ids = get_uploaded_ids(state)

    access_token = get_access_token()
    gemini_key = get_gemini_api_key()

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {access_token}"})

    pending_videos = list_pending_videos(session, folder_id, uploaded_ids)
    if not pending_videos:
        print("[ci_run] No unuploaded videos found in Drive inbox.", flush=True)
        return

    to_process = pending_videos[:max_uploads]
    temp_dir = os.path.join(base_dir, "temp_downloads")
    os.makedirs(temp_dir, exist_ok=True)

    uploaded_folder_id = None
    if not dry_run:
        uploaded_folder_id = get_or_create_uploaded_folder(session, folder_id)

    for item in to_process:
        file_id = item["id"]
        file_name = item.get("name", f"{file_id}.mp4")
        print(f"\n--- Processing: {file_name} ({file_id}) ---", flush=True)

        local_path = os.path.join(temp_dir, file_name)
        try:
            print(f"[download] Downloading {file_name} from Drive...", flush=True)
            download_video(session, file_id, local_path)
            duration = get_video_duration(local_path)
            print(f"[video] Detected duration: {duration:.1f}s", flush=True)

            print("[gemini] Analyzing video with Gemini for metadata...", flush=True)
            meta = generate_video_metadata(local_path, gemini_key, duration_seconds=duration)

            if dry_run:
                print(f"[dry_run] === DRY RUN SIMULATION SUCCESSFUL ===", flush=True)
                print(f"[dry_run] Video ID: (simulation)", flush=True)
                print(f"[dry_run] Title: {meta.get('title')}", flush=True)
                print(f"[dry_run] Char count: {len(meta.get('title', ''))}", flush=True)
                print(f"[dry_run] Tag count: {len(meta.get('tags', []))}", flush=True)
                print(f"[dry_run] Hashtags: {' '.join(meta.get('hashtags', []))}", flush=True)
                print(f"[dry_run] Path: {meta.get('path')}", flush=True)
                print(f"[dry_run] Model: {meta.get('model_used')}", flush=True)
                print(f"[dry_run] Gemini file id: {meta.get('gemini_file_id')}", flush=True)
                print(f"[dry_run] Skipping YouTube upload and Drive move.", flush=True)
            else:
                print("[live] Uploading video to YouTube...", flush=True)
                yt_result = upload_video_resumable(local_path, meta, access_token, config)
                video_id = yt_result["video_id"]
                video_url = yt_result["video_url"]

                print(f"[drive] Moving video {file_id} to 'Uploaded'...", flush=True)
                move_to_uploaded(session, file_id, uploaded_folder_id, file_name)

                # Record state
                utc_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                entry = {
                    "drive_file_id": file_id,
                    "drive_file_name": file_name,
                    "youtube_video_id": video_id,
                    "youtube_url": video_url,
                    "title": meta.get("title"),
                    "uploaded_at_utc": utc_now,
                    "tags": meta.get("tags"),
                    "hashtags": meta.get("hashtags"),
                    "model_used": meta.get("model_used")
                }
                state["items"][file_id] = entry
                state["history"].append(entry)
                save_state(state, state_file)
                print(f"[state] Saved upload state for {file_id} -> {video_id}", flush=True)

        finally:
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    if os.path.exists(temp_dir):
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass
    print("\n[ci_run] Pipeline execution completed successfully.", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Channel 11 Upload Pipeline")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Perform dry run without live changes")
    parser.add_argument("--max-uploads", dest="max_uploads", type=int, default=1, help="Max videos to process")
    parser.add_argument("--config", dest="config", default="config.json", help="Path to config file")

    args = parser.parse_args()

    # Environment variables override CLI defaults if present
    env_dry = os.environ.get("DRY_RUN", "").lower() in ["true", "1", "yes"]
    dry_run = args.dry_run or env_dry

    env_max = os.environ.get("MAX_UPLOADS")
    max_uploads = int(env_max) if env_max and env_max.isdigit() else args.max_uploads

    run_pipeline(dry_run=dry_run, max_uploads=max_uploads, config_path=args.config)
