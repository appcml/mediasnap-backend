from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import uuid
import threading
import time
import shutil
import requests as req

app = Flask(__name__)
CORS(app)

TEMP_DIR = tempfile.gettempdir()

RAPIDAPI_KEY = "54ef22c024msh7547de4061da054p1d5725jsndfe97ccda874"
RAPIDAPI_HOST = "youtube-mp3-audio-video-downloader.p.rapidapi.com"

COOKIES_FILE = None
for src in ["/etc/secrets/cookies.txt", os.path.join(os.path.dirname(__file__), "cookies.txt")]:
    if os.path.exists(src):
        _tmp = os.path.join(TEMP_DIR, "yt_cookies.txt")
        shutil.copy2(src, _tmp)
        COOKIES_FILE = _tmp
        break

def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url

def get_ydl_opts(extra={}):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        },
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    opts.update(extra)
    return opts

def cleanup_old_files():
    while True:
        time.sleep(600)
        now = time.time()
        for fname in os.listdir(TEMP_DIR):
            fpath = os.path.join(TEMP_DIR, fname)
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > 600:
                try:
                    os.remove(fpath)
                except:
                    pass

threading.Thread(target=cleanup_old_files, daemon=True).start()


@app.route("/")
def index():
    return jsonify({"status": "MediaSnap API activa", "version": "1.6"})


@app.route("/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL requerida"}), 400

    if is_youtube(url):
        try:
            video_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1].split("?")[0]
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": RAPIDAPI_HOST,
            }
            r = req.get(
                f"https://{RAPIDAPI_HOST}/get-video-info/{video_id}",
                headers=headers,
                timeout=15
            )
            info = r.json()
            formats = [
                {"format_id": "mp3", "label": "Audio MP3", "type": "audio", "ext": "mp3"},
                {"format_id": "mp4_720", "label": "720p MP4", "type": "video", "ext": "mp4"},
                {"format_id": "mp4_360", "label": "360p MP4", "type": "video", "ext": "mp4"},
            ]
            return jsonify({
                "title": info.get("title", "Sin título"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("channelTitle", ""),
                "formats": formats,
            })
        except Exception as e:
            return jsonify({"error": f"Error YouTube: {str(e)}"}), 500

    else:
        try:
            with yt_dlp.YoutubeDL(get_ydl_opts({"skip_download": True})) as ydl:
                info = ydl.extract_info(url, download=False)

            formats = []
            for f in info.get("formats", []):
                if f.get("vcodec") != "none" and f.get("acodec") != "none":
                    height = f.get("height")
                    if height and height in [360, 480, 720, 1080]:
                        formats.append({
                            "format_id": f["format_id"],
                            "label": f"{height}p MP4",
                            "type": "video",
                            "ext": "mp4",
                        })
            formats.append({"format_id": "bestaudio", "label": "Audio MP3", "type": "audio", "ext": "mp3"})

            seen = set()
            unique = []
            for f in formats:
                if f["label"] not in seen:
                    seen.add(f["label"])
                    unique.append(f)

            return jsonify({
                "title": info.get("title", "Sin título"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
                "formats": unique,
            })
        except Exception as e:
            return jsonify({"error": f"No se pudo obtener información: {str(e)}"}), 500


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "mp3")
    file_type = data.get("type", "audio")

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    file_id = str(uuid.uuid4())

    if is_youtube(url):
        try:
            video_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1].split("?")[0]
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": RAPIDAPI_HOST,
            }
            if file_type == "audio":
                r = req.get(
                    f"https://{RAPIDAPI_HOST}/get-direct-download-url-for-mp3/{video_id}",
                    headers=headers,
                    timeout=30
                )
            else:
                quality = "720" if "720" in format_id else "360"
                r = req.get(
                    f"https://{RAPIDAPI_HOST}/get-direct-download-url-for-mp4/{video_id}",
                    headers=headers,
                    params={"quality": quality},
                    timeout=30
                )
            result = r.json()
            download_url = result.get("url") or result.get("downloadUrl") or result.get("link")
            if not download_url:
                return jsonify({"error": "No se obtuvo URL de descarga"}), 500

            file_r = req.get(download_url, stream=True, timeout=60)
            ext = "mp3" if file_type == "audio" else "mp4"
            output_path = os.path.join(TEMP_DIR, f"{file_id}.{ext}")
            with open(output_path, "wb") as f:
                for chunk in file_r.iter_content(chunk_size=8192):
                    f.write(chunk)

            return send_file(output_path, as_attachment=True, download_name=f"descarga.{ext}")

        except Exception as e:
            return jsonify({"error": f"Error descarga YouTube: {str(e)}"}), 500

    else:
        if file_type == "audio":
            ydl_opts = get_ydl_opts({
                "format": "bestaudio/best",
                "outtmpl": os.path.join(TEMP_DIR, f"{file_id}.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            ydl_opts = get_ydl_opts({
                "format": f"{format_id}+bestaudio/best",
                "outtmpl": os.path.join(TEMP_DIR, f"{file_id}.%(ext)s"),
                "merge_output_format": "mp4",
            })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "descarga")

            output_path = None
            for ext in ["mp3", "mp4", "webm", "m4a"]:
                candidate = os.path.join(TEMP_DIR, f"{file_id}.{ext}")
                if os.path.exists(candidate):
                    output_path = candidate
                    break

            if not output_path:
                return jsonify({"error": "No se encontró el archivo"}), 500

            safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()
            download_name = f"{safe_title}.{output_path.split('.')[-1]}"
            return send_file(output_path, as_attachment=True, download_name=download_name)

        except Exception as e:
            return jsonify({"error": f"Error al descargar: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
