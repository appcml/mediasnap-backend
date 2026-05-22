from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import uuid
import threading
import time
import shutil

app = Flask(__name__)
CORS(app)

TEMP_DIR = tempfile.gettempdir()

# Copia cookies a ruta temporal (Render /etc/secrets es read-only)
COOKIES_FILE = None
_secret = "/etc/secrets/cookies.txt"
_local = os.path.join(os.path.dirname(__file__), "cookies.txt")

for src in [_secret, _local]:
    if os.path.exists(src):
        _tmp = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        shutil.copy2(src, _tmp)
        COOKIES_FILE = _tmp
        break

def get_ydl_opts(extra={}):
    opts = {
        "quiet": True,
        "no_warnings": True,
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
    return jsonify({"status": "MediaSnap API activa", "version": "1.4"})


@app.route("/debug")
def debug():
    return jsonify({
        "cookies_file": COOKIES_FILE,
        "cookies_exists": os.path.exists(COOKIES_FILE) if COOKIES_FILE else False,
        "secrets_dir": os.listdir("/etc/secrets") if os.path.exists("/etc/secrets") else "no existe",
    })


@app.route("/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL requerida"}), 400

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
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                    })

        formats.append({
            "format_id": "bestaudio",
            "label": "Audio MP3 (mejor calidad)",
            "type": "audio",
            "ext": "mp3",
            "filesize": None,
        })

        seen = set()
        unique_formats = []
        for f in formats:
            if f["label"] not in seen:
                seen.add(f["label"])
                unique_formats.append(f)

        return jsonify({
            "title": info.get("title", "Sin título"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", ""),
            "formats": unique_formats,
        })

    except Exception as e:
        return jsonify({"error": f"No se pudo obtener información: {str(e)}"}), 500


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "bestaudio")
    file_type = data.get("type", "audio")

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    file_id = str(uuid.uuid4())

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
            return jsonify({"error": "No se encontró el archivo descargado"}), 500

        safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()
        download_name = f"{safe_title}.{output_path.split('.')[-1]}"

        return send_file(output_path, as_attachment=True, download_name=download_name)

    except Exception as e:
        return jsonify({"error": f"Error al descargar: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
