@app.post("/stream")
def stream(req: StreamRequest):
    # 1. Get metadata to find the extension and title
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(req.url, download=False)
    
    filename = f"{info.get('title', 'media')}.mp4"

    # 2. Updated Command
    # We select the user's chosen format + the best available audio
    # We use --remux-video mp4 to ensure the output is a standard format
    cmd = [
        "yt-dlp",
        "-f", f"{req.format_id}+bestaudio/best", 
        "--merge-output-format", "mp4",
        "-o", "-",  # Output to stdout
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
                chunk = process.stdout.read(128 * 1024) # Increased chunk size for efficiency
                if not chunk:
                    break
                yield chunk
        finally:
            process.terminate()
            process.wait()

    # Note: Content-Length is removed because merging changes the final size dynamically
    return StreamingResponse(
        iterfile(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
    
    
    
    
    
@app.post("/stream")
def stream(req: StreamRequest):
    # First extract metadata for filesize + ext
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(req.url, download=False)
        fmt = next(
            (f for f in info["formats"] if f["format_id"] == req.format_id),
            None
        )

    if not fmt or not fmt.get("filesize"):
        raise HTTPException(status_code=400, detail="Invalid format")

    filesize = fmt["filesize"]
    ext = fmt.get("ext", "mp4")
    filename = f"media.{ext}"

    cmd = [
        "yt-dlp",
        "-f", req.format_id,
        "-o", "-",
        req.url,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 1024,
    )

    def iterfile():
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            process.terminate()
            process.wait(timeout=2)

    return StreamingResponse(
        iterfile(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(filesize),
        },
    )



# Analyze URL endpoint (TESTING)
for f in info.get("formats", []):
        if f.get("vcodec") != "none" and f.get("filesize"):
            formats.append({
                "format_id": f["format_id"],
                "ext": f["ext"],
                "resolution": f.get("resolution"),
                "filesize": f["filesize"],
            })
            
            
            
            
            
            
@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    formats = []

    for f in info.get("formats", []):
        # Skip audio-only
        if f.get("vcodec") == "none":
            continue

        format_id = f.get("format_id")
        ext = f.get("ext")

        # Facebook "sd" / "hd" are complete muxed formats
        if format_id in ("sd", "hd"):
            formats.append({
                "format_id": format_id,
                "ext": "mp4",
                "resolution": format_id.upper(),
                "note": "Complete",
                "filesize": None,
            })
            continue

        # Video-only streams (DASH/HLS)
        resolution = f.get("resolution") or f"{f.get('height', '?')}p"
        formats.append({
            "format_id": format_id,
            "ext": ext,
            "resolution": resolution,
            "note": "Video Only (Audio will be merged)",
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })

    return {
        "title": info.get("title"),
        "formats": formats[:8],  # keep UI clean
    }




@app.post("/stream")
def stream(req: StreamRequest):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    # title = clean_title(info.get("title", "media"))
    raw_title = info.get("title", "media")
    filename = f"{safe_filename(raw_title)}.mp4"
    # filename = f"{title}.mp4"

    format_selection = build_format_selection(req.format_id)

    cmd = [
        "yt-dlp",
        "-f", format_selection,
        "--merge-output-format", "mp4",
        "-o", "-",            # stream to stdout
        req.url,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 1024,
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
