import os
import time
import requests

VALID_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")

def robust_drive_request(session, method, url, **kwargs):
    for attempt in range(5):
        try:
            res = session.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
            if res.status_code in [200, 204]:
                return res
            elif res.status_code in [400, 403, 404]:
                return res
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    return res

def list_pending_videos(session, inbox_id, uploaded_ids_set):
    videos = []
    page_token = None
    url = "https://www.googleapis.com/drive/v3/files"

    while True:
        params = {
            "q": f"'{inbox_id}' in parents and trashed = false and mimeType contains 'video/'",
            "pageSize": 100,
            "orderBy": "createdTime asc",
            "fields": "nextPageToken, files(id, name, mimeType, createdTime, size)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true"
        }
        if page_token:
            params["pageToken"] = page_token

        res = robust_drive_request(session, "GET", url, params=params)
        res.raise_for_status()
        data = res.json()

        for f in data.get("files", []):
            name = f.get("name", "").lower()
            if any(name.endswith(ext) for ext in VALID_EXTENSIONS):
                if f["id"] not in uploaded_ids_set:
                    videos.append(f)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    videos.sort(key=lambda x: (x.get("createdTime", ""), x.get("id", "")))
    print(f"[drive] Found {len(videos)} pending unuploaded video(s) in Drive inbox.", flush=True)
    return videos

def download_video(session, file_id, dest_path):
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    with session.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dest_path

def get_or_create_uploaded_folder(session, inbox_id):
    url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": f"'{inbox_id}' in parents and name = 'Uploaded' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        "fields": "files(id, name)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true"
    }
    res = robust_drive_request(session, "GET", url, params=params)
    res.raise_for_status()
    files = res.json().get("files", [])
    if files:
        return files[0]["id"]

    create_body = {
        "name": "Uploaded",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [inbox_id]
    }
    c_res = robust_drive_request(session, "POST", "https://www.googleapis.com/drive/v3/files?supportsAllDrives=true", json=create_body)
    c_res.raise_for_status()
    folder_id = c_res.json()["id"]
    print(f"[drive] Created 'Uploaded' folder: {folder_id}", flush=True)
    return folder_id

def move_to_uploaded(session, file_id, uploaded_folder_id, file_name):
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=parents&supportsAllDrives=true"
    r = robust_drive_request(session, "GET", meta_url)
    current_parents = ""
    if r.status_code == 200:
        parents = r.json().get("parents", [])
        current_parents = ",".join(parents)

    patch_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?addParents={uploaded_folder_id}&removeParents={current_parents}&supportsAllDrives=true"
    robust_drive_request(session, "PATCH", patch_url, json={})
    print(f"[drive] Moved '{file_name}' to 'Uploaded' subfolder.", flush=True)
