from fastapi import FastAPI, HTTPException, Depends, Request, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import subprocess
import re
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Optional

# -----------------------------
# Rate Limiter Setup (Completed)
# -----------------------------
limiter = Limiter(key_func=get_remote_address)  # Fallback to IP if no token
app = FastAPI(title="Private Media Service")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Config
# -----------------------------
ALLOWED_DOMAINS = (
    "youtube.com", "youtu.be",
    "facebook.com", "fb.watch",
    "instagram.com", "tiktok.com"
)

# Simple static tokens (replace with database/JWT in production)
VALID_TOKENS = {
    "token123": "user1",
    "secret456": "user2",
    "demo789": "demo",
    # Add more tokens here
}

def is_allowed(url: str) -> bool:
    return any(d in url for d in ALLOWED_DOMAINS)

# -----------------------------
# Models
# -----------------------------
class AnalyzeRequest(BaseModel):
    url: str

class StreamRequest(BaseModel):
    url: str
    format_id: str

# -----------------------------
# Auth Dependency (for token-based limiting)
# -----------------------------
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.split(" ")[1]
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return VALID_TOKENS[token]  # Return user identifier (can be username, id, etc.)

# Key function for per-token limiting
def token_key_func(request: Request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split(" ")[1]
        if token in VALID_TOKENS:
            return f"user:{VALID_TOKENS[token]}"
    return f"ip:{get_remote_address(request)}"  # Fallback to IP

# Create a separate limiter for token-based limits
token_limiter = Limiter(key_func=token_key_func)

# -----------------------------
# Helpers
# -----------------------------
def clean_title(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', title)

def safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.-]", "", name)
    return name.encode("ascii", "ignore").decode() or "media"

# -----------------------------
# Analyze Endpoint (public, lightweight)
# -----------------------------
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
    if not is_allowed(req.url):
        raise HTTPException(status_code=400, detail="Domain not allowed")

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL or extraction failed")

    min_height = 360
    formats_map = {}

    for f in info.get("formats", []):
        if f.get("vcodec") == "none":
            continue
        height = f.get("height")
        if not height or height < min_height:
            continue
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

# -----------------------------
# Stream Endpoint (protected + rate-limited per user/token)
# -----------------------------
@app.post("/stream")
@token_limiter.limit("5/hour")  # Adjust: e.g., "10/day", "3/minute", etc.
async def stream(req: StreamRequest, user: str = Depends(get_current_user)):
    if not is_allowed(req.url):
        raise HTTPException(status_code=400, detail="Domain not allowed")

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    raw_title = info.get("title", "media")
    filename = f"{safe_filename(raw_title)}.mp4"

    url_lower = req.url.lower()
    if "facebook.com" in url_lower or "fb.watch" in url_lower:
        platform = "facebook"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        platform = "youtube"
    elif "instagram.com" in url_lower:
        platform = "instagram"
    elif "tiktok.com" in url_lower:
        platform = "tiktok"
    else:
        platform = "other"

    if platform == "facebook":
        cmd = [
            "yt-dlp", "-f", "best", "--recode-video", "mp4",
            "--postprocessor-args", "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-", req.url
        ]
    elif platform == "youtube":
        format_selection = f"{req.format_id}+bestaudio/best" if req.format_id != "best" else "bestvideo+bestaudio/best"
        cmd = ["yt-dlp", "-f", format_selection, "--merge-output-format", "mp4", "-o", "-", req.url]
    elif platform in ["instagram", "tiktok"]:
        cmd = [
            "yt-dlp", "-f", "bestvideo+bestaudio/best", "--recode-video", "mp4",
            "--postprocessor-args", "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-", req.url
        ]
    else:
        cmd = [
            "yt-dlp", "-f", "best", "--recode-video", "mp4",
            "--postprocessor-args", "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v baseline -movflags +faststart",
            "-o", "-", req.url
        ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )