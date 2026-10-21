import os
import time
import requests

def upload_video_resumable(video_path, metadata, access_token, config):
    # Safety Gate Check
    meta_path = metadata.get("path")
    if meta_path != "video_ai_gemini":
        err_msg = f"[block] Safety block: Publishing blocked because metadata path is '{meta_path}'. Only 'video_ai_gemini' is allowed to publish live."
        print(err_msg, flush=True)
        raise RuntimeError(err_msg)

    title = metadata.get("title", "")
    desc = metadata.get("description", "")
    hashtags = metadata.get("hashtags", [])

    if config.get("append_hashtags_to_description", True) and hashtags:
        desc = f"{desc}\n\n" + " ".join(hashtags)

    category_id = str(metadata.get("category_id", config.get("category_id", "22")))
    default_lang = metadata.get("language", config.get("default_language", "en"))
    privacy_status = config.get("privacy_status", "public")
    made_for_kids = bool(config.get("made_for_kids", False))

    snippet = {
        "title": title,
        "description": desc,
        "tags": metadata.get("tags", []),
        "categoryId": category_id,
        "defaultLanguage": default_lang
    }

    status = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": made_for_kids
    }

    body = {"snippet": snippet, "status": status}
    file_size = os.path.getsize(video_path)

    init_url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(file_size)
    }

    init_res = requests.post(init_url, headers=headers, json=body, timeout=40)
    init_res.raise_for_status()

    upload_url = init_res.headers.get("Location")
    if not upload_url:
        raise RuntimeError("No upload Location returned by YouTube API.")

    with open(video_path, "rb") as f:
        up_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/mp4"
        }
        up_res = requests.put(upload_url, headers=up_headers, data=f, timeout=600)
        up_res.raise_for_status()
        yt_data = up_res.json()

    video_id = yt_data.get("id")
    if not video_id:
        raise RuntimeError("No video ID in YouTube upload response.")

    # Verification of published status
    v_url = f"https://www.googleapis.com/youtube/v3/videos?part=status,snippet&id={video_id}"
    v_res = requests.get(v_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    actual_privacy = "unknown"
    actual_upload_status = "unknown"
    if v_res.status_code == 200:
        items = v_res.json().get("items", [])
        if items:
            s_obj = items[0].get("status", {})
            actual_privacy = s_obj.get("privacyStatus", "unknown")
            actual_upload_status = s_obj.get("uploadStatus", "unknown")

    video_url = f"https://youtu.be/{video_id}"
    print(f"[yt] Video published: {video_url}", flush=True)
    print(f"[yt] Actual privacyStatus: {actual_privacy}, uploadStatus: {actual_upload_status}", flush=True)

    return {
        "video_id": video_id,
        "video_url": video_url,
        "privacy_status": actual_privacy,
        "upload_status": actual_upload_status,
        "title": title,
        "tags": metadata.get("tags", []),
        "hashtags": hashtags
    }
