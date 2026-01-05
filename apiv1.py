import os
import re
import subprocess
import yt_dlp
from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.status import HTTP_403_FORBIDDEN

# -------------------------
# Configuration & Security
# -------------------------

# Define your secret token here (or load from environment variables)
API_TOKEN = os.getenv("API_TOKEN", "secure-media-token-123")
API_KEY_NAME = "X-API-Key"

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    """Validates the API Key from the header."""
    if api_key == API_TOKEN:
        return api_key
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, 
        detail="Could not validate credentials"
    )

# -------------------------
# App Setup
# -------------------------

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Private Media Service")

# Register the Rate Limit Exception Handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# -------------------------
# Models
# -------------------------

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

def format_filesize(size: int | None) -> str | None:
    if not size or size <= 0:
        return None
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

# -------------------------
# Analyze Endpoint
# -------------------------

@app.post("/analyze", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def analyze(request: Request, req: AnalyzeRequest):
    """
    Analyzes the URL and returns available formats.
    Requires 'X-API-Key' header.
    """
    try:
        # 'quiet': True prevents yt-dlp from spamming logs
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=400, detail="Invalid URL or extraction failed")

    min_height = 360
    formats_map = {}

    for f in info.get("formats", []):
        if f.get("vcodec") == "none": continue # skip audio only

        height = f.get("height")
        if not height or height < min_height: continue
        
        raw_size = f.get("filesize") or f.get("filesize_approx")
        key = height
        
        formats_map[key] = {
            "format_id": f.get("format_id"),
            "ext": f.get("ext", "mp4"),
            "resolution": f"{height}p",
            "note": "Complete" if f.get("acodec") != "none" else "Video only (audio merged)",
            "filesize": format_filesize(raw_size),
        }

    formats = [formats_map[h] for h in sorted(formats_map)]

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

@app.post("/stream", dependencies=[Depends(verify_api_key)])
@limiter.limit("3/minute")
def stream(request: Request, req: StreamRequest):
    """
    Stream video dynamically.
    Requires 'X-API-Key' header.
    """
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    raw_title = info.get("title", "media")
    filename = f"{safe_filename(raw_title)}.mp4"

    # Platform detection & Command builder
    url_lower = req.url.lower()
    
    # Common flags for stability
    # - movflags +faststart moves metadata to front so streaming works immediately
    # - re-encoding to h264 ensures compatibility with all browsers
    ffmpeg_args = "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart"

    cmd = ["yt-dlp", "-o", "-", req.url]

    if any(x in url_lower for x in ["facebook.com", "fb.watch", "instagram.com", "tiktok.com"]):
        # These platforms usually need recoding to standard mp4 for direct stream
        cmd.extend([
            "-f", "best",
            "--recode-video", "mp4",
            "--postprocessor-args", ffmpeg_args
        ])
    elif any(x in url_lower for x in ["youtube.com", "youtu.be"]):
        # Handle YouTube specific format selection
        fmt = req.format_id
        if fmt == "best" or fmt in ("sd", "hd"):
            selection = "bestvideo+bestaudio/best"
        elif fmt.endswith("v"): # custom logic if you have video-only ids
            selection = f"{fmt}+bestaudio/best"
        else:
            selection = f"{fmt}+bestaudio/best"

        cmd.extend([
            "-f", selection,
            "--merge-output-format", "mp4"
        ])
    else:
        # Fallback
        cmd.extend([
            "-f", "best",
            "--recode-video", "mp4",
            "--postprocessor-args", ffmpeg_args
        ])

    # Start the subprocess
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def iterfile():
        try:
            while True:
                chunk = process.stdout.read(64 * 1024) # 64KB chunks
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