from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import subprocess
import re
from slowapi import Limiter
from slowapi.util import get_remote_address

# limiter = Limiter(key_func=get_remote_address)
# app.state.limiter = limiter

app = FastAPI(title="Private Media Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_DOMAINS = (
    "youtube.com", "youtu.be",
    "facebook.com", "fb.watch",
    "instagram.com", "tiktok.com"
)

def is_allowed(url: str) -> bool:
    return any(d in url for d in ALLOWED_DOMAINS)

class AnalyzeRequest(BaseModel):
    url: str


class StreamRequest(BaseModel):
    url: str
    format_id: str


# -------------------------
# Helpers
# -------------------------

def clean_title(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', title)

def safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.-]", "", name)
    return name.encode("ascii", "ignore").decode() or "media"


def build_format_selection(format_id: str) -> str:
    """
    Decide how yt-dlp should download + merge
    """
    if format_id in ("best", "sd", "hd"):
        return "bestvideo+bestaudio/best"

    if format_id.endswith("v"):
        return f"{format_id}+bestaudio/best"

    # YouTube combined formats (18, 22, etc.)
    return format_id


# -------------------------
# Analyze Endpoint
# -------------------------

def format_filesize(size: int | None) -> str | None:
    if not size or size <= 0:
        return None

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} PB"


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    min_height = 360  # anything smaller is skipped
    formats_map = {}

    for f in info.get("formats", []):
        # skip audio-only
        if f.get("vcodec") == "none":
            continue

        height = f.get("height")
        if not height or height < min_height:
            continue
        
        raw_size = f.get("filesize") or f.get("filesize_approx")

        # Normalize key by height to avoid duplicates
        key = height
        formats_map[key] = {
            "format_id": f.get("format_id"),
            "ext": f.get("ext", "mp4"),
            "resolution": f"{height}p",
            "note": "Complete" if f.get("acodec") != "none" else "Video only (audio merged)",
            "filesize": format_filesize(raw_size),
        }

    # Sort ascending, optional: you could sort descending to show high-res first
    formats = [formats_map[h] for h in sorted(formats_map)]

    # Fallback if nothing left
    if not formats:
        formats = [{
            "format_id": "best",
            "resolution": "Best available",
            "note": "Auto selected",
            "filesize": None,
        }]

    return {
        "title": info.get("title"),
        "formats": formats,
    }


# -------------------------
# Stream Endpoint
# -------------------------

@app.post("/stream")
# @limiter.limit("3/minute")
def stream(req: StreamRequest):
    """
    Stream video dynamically based on platform.
    """
    import subprocess
    
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    raw_title = info.get("title", "media")
    filename = f"{safe_filename(raw_title)}.mp4"
    # filename = "media.mp4"

    # Detect platform
    url = req.url.lower()
    if "facebook.com" in url or "fb.watch" in url:
        platform = "facebook"
    elif "youtube.com" in url or "youtu.be" in url:
        platform = "youtube"
    elif "instagram.com" in url:
        platform = "instagram"
    elif "tiktok.com" in url:
        platform = "tiktok"
    else:
        platform = "other"

    # Build command per platform
    if platform == "facebook":
        cmd = [
            "yt-dlp",
            "-f", "best",
            "--recode-video", "mp4",
            "--postprocessor-args",
            "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-",
            req.url,
        ]
    elif platform == "youtube":
        format_selection = (
            f"{req.format_id}+bestaudio/best"
            if req.format_id != "best"
            else "bestvideo+bestaudio/best"
        )
        cmd = [
            "yt-dlp",
            "-f", format_selection,
            "--merge-output-format", "mp4",
            "-o", "-",
            req.url,
        ]
    elif platform in ["instagram", "tiktok"]:
        format_selection = "bestvideo+bestaudio/best"
        cmd = [
            "yt-dlp",
            "-f", format_selection,
            "--recode-video", "mp4",
            "--postprocessor-args",
            "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-",
            req.url,
        ]
    else:  # fallback for unknown sites
        cmd = [
            "yt-dlp",
            "-f", "best",
            "--recode-video", "mp4",
            "--postprocessor-args",
            "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-",
            req.url,
        ]

    # Run the process
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def iterfile():
        try:
            while True:
                chunk = process.stdout.read(128 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            process.terminate()
            process.wait()

    return StreamingResponse(
        iterfile(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
