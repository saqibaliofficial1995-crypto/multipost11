import os
import sys
import re
import json
import time
import random
import requests

EXCLUDE_SUBSTRINGS = [
    "-tts", "-image", "-embedding", "-aqa", "-vision", "-thinking",
    "-live", "-native-audio", "-dialog", "-preview", "learnlm", "gemma"
]

PRIORITY_ORDER = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-pro-latest"
]

CURRENCY_PATTERN = re.compile(r"[\$\u20AC\u00A3\u00A5\u20B9]|\b(?:USD|AED|EUR|GBP)\b", re.IGNORECASE)
MAGNITUDE_PATTERN = re.compile(r"\b\d+([.,]\d+)?\s*(m|b|k|million|billion|sqft|sq\s*ft|feet)\b", re.IGNORECASE)

def get_live_models(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    headers = {"x-goog-api-key": api_key}
    try:
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code == 200:
            models_data = res.json().get("models", [])
            valid_models = []
            for item in models_data:
                methods = item.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue
                name = item.get("name", "").replace("models/", "").strip()
                name_lower = name.lower()
                if any(sub in name_lower for sub in EXCLUDE_SUBSTRINGS):
                    continue
                valid_models.append(name)

            ordered_models = []
            for p in PRIORITY_ORDER:
                for m in valid_models:
                    if (m == p or m.startswith(p)) and m not in ordered_models:
                        ordered_models.append(m)

            if ordered_models:
                print(f"[llm_meta] Filtered live models ({len(ordered_models)}): {ordered_models}", flush=True)
                return ordered_models
            else:
                raise RuntimeError(f"None of priority models ({PRIORITY_ORDER}) found in live Gemini model list.")
    except Exception as e:
        print(f"[llm_meta] Warning fetching live models: {e}", flush=True)

    return list(PRIORITY_ORDER)

def upload_video_to_gemini(video_path, api_key):
    file_size = os.path.getsize(video_path)
    init_url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    headers = {
        "x-goog-api-key": api_key,
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": "video/mp4",
        "Content-Type": "application/json"
    }
    body = {"file": {"display_name": os.path.basename(video_path)}}

    init_res = requests.post(init_url, headers=headers, json=body, timeout=30)
    if init_res.status_code != 200:
        raise RuntimeError(f"Gemini file upload init failed: {init_res.status_code} - {init_res.text}")

    upload_url = init_res.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("No upload URL returned from Gemini.")

    with open(video_path, "rb") as f:
        video_data = f.read()

    up_headers = {
        "Content-Length": str(file_size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize"
    }
    up_res = requests.post(upload_url, headers=up_headers, data=video_data, timeout=180)
    if up_res.status_code != 200:
        raise RuntimeError(f"Gemini file upload finalize failed: {up_res.status_code} - {up_res.text}")

    file_info = up_res.json().get("file", {})
    file_name = file_info.get("name")
    file_uri = file_info.get("uri")

    print(f"[llm_meta] Uploaded to Gemini: {file_name}. Waiting for PROCESSING state...", flush=True)
    get_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
    for _ in range(40):
        time.sleep(2)
        check_res = requests.get(get_url, headers={"x-goog-api-key": api_key}, timeout=15)
        if check_res.status_code == 200:
            state = check_res.json().get("state")
            if state == "ACTIVE":
                print(f"[llm_meta] Gemini file is ACTIVE: {file_name}", flush=True)
                return file_name, file_uri
            elif state == "FAILED":
                raise RuntimeError("Gemini video processing failed.")
    raise TimeoutError("Gemini video processing timed out.")

def delete_gemini_file(file_name, api_key):
    if not file_name:
        return
    url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
    try:
        requests.delete(url, headers={"x-goog-api-key": api_key}, timeout=15)
        print(f"[llm_meta] Deleted Gemini temporary file {file_name}.", flush=True)
    except Exception as e:
        print(f"[llm_meta] Warning deleting Gemini file: {e}", flush=True)

def sanitize_json_controls(raw_json_str):
    def fix_str(match):
        val = match.group(0)
        val = re.sub(r'(?<!\\)\n', r'\\n', val)
        val = re.sub(r'(?<!\\)\r', r'\\r', val)
        val = re.sub(r'(?<!\\)\t', r'\\t', val)
        return val
    try:
        return re.sub(r'"(?:[^"\\]|\\.)*"', fix_str, raw_json_str, flags=re.DOTALL)
    except Exception:
        return raw_json_str

def try_parse_json(s):
    if not s:
        return None
    try:
        return json.loads(s, strict=False)
    except Exception:
        pass
    try:
        sanitized = sanitize_json_controls(s)
        return json.loads(sanitized, strict=False)
    except Exception:
        pass
    return None

def clean_text(raw_text):
    text = raw_text.strip()
    match_dict = re.search(r"\{.*\}", text, re.DOTALL)
    if match_dict:
        res = try_parse_json(match_dict.group(0))
        if isinstance(res, dict):
            return res

    match_arr = re.search(r"\[.*\]", text, re.DOTALL)
    if match_arr:
        res = try_parse_json(match_arr.group(0))
        if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
            return res[0]

    cleaned = re.sub(r"^```(?:json|text)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    res = try_parse_json(cleaned)
    if isinstance(res, dict):
        return res
    elif isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
        return res[0]

    return None

def validate_metadata(meta, duration_seconds=None):
    if not isinstance(meta, dict):
        raise ValueError("Metadata is not a valid dictionary.")

    title = meta.get("title", "").strip()
    if not title:
        raise ValueError("Title is empty.")
    if len(title) >= 60:
        raise ValueError(f"Title length is {len(title)} >= 60 characters.")

    # Currency check on title and description
    desc_str = str(meta.get("description", ""))
    full_text = f"{title} {desc_str}"
    if CURRENCY_PATTERN.search(title):
        raise ValueError(f"Title contains currency symbols or currency codes: {title}")

    # Magnitude/unit hallucination check
    if MAGNITUDE_PATTERN.search(title):
        raise ValueError(f"Title contains magnitude claims or unit patterns: {title}")

    # Tags check: 10-15 tags, total joined length < 460
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or len(tags) < 10:
        raise ValueError(f"Tags count is {len(tags)}, must be between 10 and 15.")
    tags = [str(t).strip() for t in tags if str(t).strip()][:15]
    if len(tags) < 10:
        raise ValueError(f"Valid tags count is {len(tags)}, must be at least 10.")
    meta["tags"] = tags
    tags_joined = ",".join(tags)
    if len(tags_joined) >= 460:
        raise ValueError(f"Tags string length {len(tags_joined)} exceeds 460 characters.")

    # Description check and formatting: include ch9/ch10 description-separator fix
    desc = meta.get("description", "")
    if isinstance(desc, list):
        lines = [str(d).strip() for d in desc if d]
        meta["description"] = "\n\n".join(lines)
    elif isinstance(desc, str):
        lines = [line.strip() for line in desc.splitlines() if line.strip()]
        if len(lines) == 1 and ". " in lines[0]:
            parts = [s.strip() for s in re.split(r"\.\s+", lines[0]) if s.strip()]
            lines = [p if p.endswith((".", "!", "?")) else f"{p}." for p in parts]
        meta["description"] = "\n\n".join(lines)

    # Hashtags check: exactly 3
    hashtags = meta.get("hashtags", [])
    if not isinstance(hashtags, list):
        raise ValueError("Hashtags must be a list.")

    cleaned_hashtags = []
    for h in hashtags:
        h_clean = str(h).strip()
        if not h_clean.startswith("#"):
            h_clean = f"#{h_clean}"
        cleaned_hashtags.append(h_clean)

    # Check if duration <= 60s -> must include #shorts
    is_short = (duration_seconds is not None and duration_seconds <= 60.0)
    has_shorts = any(h.lower() == "#shorts" for h in cleaned_hashtags)

    if is_short and not has_shorts:
        if len(cleaned_hashtags) >= 3:
            cleaned_hashtags[2] = "#shorts"
        else:
            cleaned_hashtags.append("#shorts")

    if len(cleaned_hashtags) != 3:
        raise ValueError(f"Hashtags count is {len(cleaned_hashtags)}, must be exactly 3.")

    meta["hashtags"] = cleaned_hashtags
    return True

def generate_video_metadata(video_path, api_key, duration_seconds=60):
    models = get_live_models(api_key)
    file_name, file_uri = upload_video_to_gemini(video_path, api_key)

    is_short = (duration_seconds is not None and duration_seconds <= 60.0)
    shorts_instruction = "Must include '#shorts' in hashtags because video is under 60 seconds." if is_short else ""

    prompt = f"""Watch the video frames and listen to the audio carefully. Do NOT use the video filename to guess content.
Return ONLY a raw JSON object. No markdown, no code fences, no explanation text before or after.

Perform this exact analysis:
1. Inferred channel topic/niche from the actual video visuals.
2. The language of the video (e.g. 'en', 'es', etc.).
3. Relevant YouTube category ID (e.g. '22' for People & Blogs, '24' for Entertainment, '26' for Howto).
4. Engaging SEO Title: Under 60 characters with the primary keyword right at the beginning. NEVER include money amounts, currency signs ($, EUR, etc.), or fake statistics/magnitudes (e.g. 100M, 50k, etc.).
5. Description: First 2 lines must be an intriguing hook, followed by a brief summary.
6. 10 to 15 relevant SEO tags (comma joined length under 460 chars).
7. Exactly 3 relevant hashtags. {shorts_instruction}

Required JSON structure:
{{
  "inferred_topic": "topic summary",
  "language": "en",
  "category_id": "22",
  "title": "Keyword First: Engaging Short Title",
  "description": "Hook line 1\nHook line 2\nDetailed summary...",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
  "hashtags": ["#tag1", "#tag2", "#tag3"]
}}"""

    max_validation_attempts = 4
    validation_attempts_used = 0
    final_meta = None
    skip_list = set()
    start_meta_time = time.time()
    MAX_METADATA_TIME_SECONDS = 360

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "contents": [{
            "parts": [
                {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json"
        }
    }

    try:
        model_idx = 0
        consecutive_model_failures = 0

        while validation_attempts_used < max_validation_attempts:
            elapsed_total = time.time() - start_meta_time
            if elapsed_total > MAX_METADATA_TIME_SECONDS:
                print(f"[time_cap] Overall time cap of {MAX_METADATA_TIME_SECONDS}s exceeded ({elapsed_total:.1f}s elapsed). Aborting.", flush=True)
                break

            candidate_models = [m for m in models if m not in skip_list]
            if not candidate_models:
                print("[fail] No remaining valid models in list.", flush=True)
                break

            current_model = candidate_models[model_idx % len(candidate_models)]
            gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
            print(f"[model] Trying model '{current_model}' (validation attempts: {validation_attempts_used}/{max_validation_attempts}, elapsed: {elapsed_total:.1f}s)...", flush=True)

            res = None
            transient_retries = 3
            backoff_schedule = [4, 8, 16]

            for retry_i in range(transient_retries + 1):
                if (time.time() - start_meta_time) > MAX_METADATA_TIME_SECONDS:
                    break
                try:
                    res = requests.post(gen_url, headers=headers, json=body, timeout=60)
                except Exception as req_err:
                    print(f"[warning] Request error on {current_model}: {req_err}", flush=True)
                    res = None

                status_code = res.status_code if res is not None else 500
                if status_code in (503, 429, 500):
                    if retry_i < transient_retries:
                        backoff = backoff_schedule[retry_i] + random.uniform(0.5, 1.5)
                        print(f"[transient] HTTP {status_code} on {current_model}. Retry {retry_i+1} after {backoff:.1f}s...", flush=True)
                        time.sleep(backoff)
                        continue
                    else:
                        break
                elif status_code in (404, 400):
                    err_msg = res.text[:120] if res is not None else ""
                    print(f"[bad_model] HTTP {status_code} on {current_model}: {err_msg}. Skipping model.", flush=True)
                    skip_list.add(current_model)
                    break
                else:
                    break

            if res is None or res.status_code != 200:
                consecutive_model_failures += 1
                if consecutive_model_failures >= len(candidate_models) * 2:
                    print("[fail] All models gave errors.", flush=True)
                    break
                model_idx += 1
                continue

            consecutive_model_failures = 0
            try:
                candidates = res.json().get("candidates", [])
                if not candidates:
                    validation_attempts_used += 1
                    model_idx += 1
                    continue

                text_part = candidates[0]["content"]["parts"][0]["text"]
                meta = clean_text(text_part)
                if not meta:
                    validation_attempts_used += 1
                    model_idx += 1
                    continue

                validate_metadata(meta, duration_seconds=duration_seconds)
                meta["path"] = "video_ai_gemini"
                meta["model_used"] = current_model
                meta["gemini_file_id"] = file_name
                final_meta = meta
                break
            except Exception as val_err:
                print(f"[fail] Validation error on {current_model}: {val_err}", flush=True)
                validation_attempts_used += 1
                model_idx += 1
                time.sleep(2)

        if not final_meta:
            elapsed_final = time.time() - start_meta_time
            raise RuntimeError(f"Failed to generate validated video metadata: budget ({elapsed_final:.1f}s) exhausted.")

        topic = final_meta.get("inferred_topic", "General Entertainment")
        title = final_meta.get("title", "")
        desc = final_meta.get("description", "")
        hook = " ".join([line for line in desc.splitlines() if line.strip()][:2])
        tags = final_meta.get("tags", [])
        hashtags = final_meta.get("hashtags", [])

        print(f"[topic] Inferred channel topic: '{topic}'", flush=True)
        print(f"[llm_meta] Gemini watched the video and inferred channel topic: '{topic}'", flush=True)
        print(f"[meta] Path used: video_ai_gemini | Model used: {final_meta['model_used']}", flush=True)
        print(f"[meta] Title ({len(title)} chars): {title}", flush=True)
        print(f"[meta] Description hook: {hook}", flush=True)
        print(f"[meta] Tags ({len(tags)}): {','.join(tags)}", flush=True)
        print(f"[meta] Hashtags: {' '.join(hashtags)}", flush=True)
        print(f"[meta] Gemini file id: {file_name}", flush=True)

        return final_meta
    finally:
        delete_gemini_file(file_name, api_key)
