from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import subprocess
import re
from slowapi import Limiter
from slowapi.util import get_remote_address

# -------------------------
# App & Limiter
# -------------------------

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Private Media Service")
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Security
# -------------------------

ALLOWED_DOMAINS = (
    "youtube.com", "youtu.be",
    "facebook.com", "fb.watch",
    "instagram.com", "tiktok.com"
)

def is_allowed(url: str) -> bool:
    return any(domain in url for domain in ALLOWED_DOMAINS)

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

def safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.-]", "", name)
    return name.encode("ascii", "ignore").decode() or "media"

def format_filesize(size: int | None) -> str | None:
    if not size:
        return None
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return None

def build_format_selection(format_id: str) -> str:
    if format_id in ("best", "hd", "sd"):
        return "bestvideo+bestaudio/best"
    if format_id.endswith("v"):
        return f"{format_id}+bestaudio/best"
    return format_id

# -------------------------
# Analyze Endpoint
# -------------------------

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not is_allowed(req.url):
        raise HTTPException(status_code=403, detail="Domain not allowed")

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    formats_map = {}

    for f in info.get("formats", []):
        if f.get("vcodec") == "none":
            continue

        height = f.get("height")
        if not height or height < 360:
            continue

        key = (height, f.get("ext"))
        size = f.get("filesize") or f.get("filesize_approx")

        formats_map[key] = {
            "format_id": f.get("format_id"),
            "resolution": f"{height}p",
            "ext": f.get("ext"),
            "note": "Complete" if f.get("acodec") != "none" else "Video only",
            "filesize": format_filesize(size),
        }

    formats = [formats_map[k] for k in sorted(formats_map, key=lambda x: x[0])]

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
@limiter.limit("3/minute")
#def stream(req: StreamRequest):
def stream(request: Request, req: StreamRequest):
    if not is_allowed(req.url):
        raise HTTPException(status_code=403, detail="Domain not allowed")

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    filename = f"{safe_filename(info.get('title', 'media'))}.mp4"
    url = req.url.lower()

    if "youtube" in url or "youtu.be" in url:
        fmt = build_format_selection(req.format_id)
        cmd = [
            "yt-dlp",
            "-f", fmt,
            "--merge-output-format", "mp4",
            "-o", "-",
            req.url,
        ]
    else:
        cmd = [
            "yt-dlp",
            "-f", "best",
            "--recode-video", "mp4",
            "--postprocessor-args",
            "ffmpeg:-c:v libx264 -pix_fmt yuv420p -movflags +faststart",
            "-o", "-",
            req.url,
        ]

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
        except GeneratorExit:
            process.terminate()
        finally:
            process.terminate()
            process.wait()

    return StreamingResponse(
        iterfile(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

# -------------------------
# Misc
# -------------------------

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("favicon.ico")

@app.get("/")
def root():
    return Response("Private Media Service is running.", media_type="text/plain")
