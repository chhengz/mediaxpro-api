# 🖥️ Backend – MediaXPro API (FastAPI + yt-dlp)

## MediaXPro Backend

A private FastAPI backend that analyzes and streams online videos using yt-dlp.  
Designed to work with a Flutter client via HTTP streaming.

Supports Facebook, YouTube, Instagram, TikTok, and more.

---

## ✨ Features

- 🔍 Analyze video metadata & formats
- 🎞️ Normalize platform-specific formats
- 🔊 Auto-merge video + audio
- 📡 Stream output directly (no disk save)
- ⚡ Low memory usage
- 🌍 CORS enabled
- 📦 Stateless & container-friendly

---

## 🧱 Tech Stack

- Python 3.10+
- FastAPI
- yt-dlp
- FFmpeg
- Uvicorn

---

## 📦 API Endpoints

### 🔎 Analyze Video

```code
POST /analyze
```

**Request**

```json
{
  "url": "https://video-link"
}
````

**Response**

```json
{
  "title": "Video title",
  "formats": [
    {
      "format_id": "best",
      "ext": "mp4",
      "resolution": "720p",
      "note": "Complete"
    }
  ]
}
```

---

### ⬇️ Stream Download

- **Request**

```code
POST /stream
```

- **Response**

```json
{
  "url": "https://video-link",
  "format_id": "best"
}
```


- `video/mp4` stream
- Merged audio + video
- No Content-Length (progress may be indeterminate)

---

## 🧠 Format Logic

- Facebook / Instagram / TikTok:

```cmd
-f best
```

- YouTube:

```cmd
-f bestvideo+bestaudio/best
```

This prevents:

- black screen videos
- audio-only playback
- DASH format issues

## 🛠️ Requirements

- Python 3.10+
- yt-dlp installed
- FFmpeg available in PATH

## 🚀 Run Locally

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

- you can change the ip base on your LAN/IPv4
- Example: --host 127.0.0.1

---

## 🌍 Deployment

Works on:

- VPS (Hetzner, DigitalOcean, Oracle Free Tier*)
- Railway / Fly.io (with limits)
- Docker environments

⚠️ Avoid serverless platforms that block subprocess or FFmpeg.

---

## ⚠️ Disclaimer

This project is for **educational and personal use only**.
Respect content owners and platform terms of service.

---

## 👨‍💻 Developer

Develop by **@chheng_hilo**
