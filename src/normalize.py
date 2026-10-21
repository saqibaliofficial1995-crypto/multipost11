import os
import subprocess

def get_video_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8").strip()
        return float(out)
    except Exception:
        return 0.0

def normalize_video(input_path, output_path, encode_config=None):
    if encode_config is None:
        encode_config = {}
    width = encode_config.get("width", 1080)
    height = encode_config.get("height", 1920)
    fps = encode_config.get("fps", 30)
    max_sec = encode_config.get("max_seconds", 180)
    v_bitrate = encode_config.get("video_bitrate", "6M")
    a_bitrate = encode_config.get("audio_bitrate", "128k")

    print(f"[ffmpeg] Normalizing to {width}x{height} {fps}fps...", flush=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    filter_complex = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", filter_complex,
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "fast",
        "-b:v", v_bitrate,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", a_bitrate,
        "-t", str(max_sec),
        output_path
    ]

    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path
    except Exception as e:
        print(f"[ffmpeg] Warning: ffmpeg normalization failed or not available ({e}), using original video.", flush=True)
        return input_path
