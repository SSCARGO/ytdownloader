import json
import time
import os
import shutil
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, Response, send_from_directory, send_file
from flask_cors import CORS

from downloader import (
    get_info,
    start_download,
    get_download_state,
    cancel_download,
    cleanup_download,
)
from utils import validate_youtube_url, format_duration, format_views, get_downloads_folder

app = Flask(__name__, static_folder="assets", static_url_path="/assets")
CORS(app)

ASSETS_DIR = Path(__file__).parent / "assets"


# ─── Serve Frontend ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(ASSETS_DIR, "index.html")


# ─── Check ffmpeg ─────────────────────────────────────────────────────────────

def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@app.route("/api/system")
def system_info():
    return jsonify({"ffmpeg": _ffmpeg_available()})


# ─── Video Info ───────────────────────────────────────────────────────────────

@app.route("/api/info", methods=["POST"])
def video_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if not validate_youtube_url(url):
        return jsonify({"error": "Please enter a valid YouTube URL (youtube.com or youtu.be)"}), 400

    try:
        info = get_info(url)
        info["duration_str"] = format_duration(info.get("duration"))
        info["views_str"] = format_views(info.get("view_count"))
        return jsonify(info)
    except Exception as exc:
        msg = str(exc)
        if "private" in msg.lower() or "unavailable" in msg.lower():
            return jsonify({"error": "This video is private or unavailable"}), 400
        if "age" in msg.lower() or "sign in" in msg.lower():
            return jsonify({"error": "This video requires authentication (age-restricted)"}), 400
        if "copyright" in msg.lower():
            return jsonify({"error": "This video is unavailable due to copyright restrictions"}), 400
        return jsonify({"error": f"Could not fetch video info: {msg}"}), 500


# ─── Start Download ───────────────────────────────────────────────────────────

@app.route("/api/download", methods=["POST"])
def start():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = data.get("quality", "best")
    mode = data.get("mode", "video")          # "video" | "audio"
    bitrate = data.get("bitrate", "192k")

    # If user provided a specific folder (from Stage 1 logic), use it.
    # Otherwise, download to a backend temp folder so we can serve it to the browser later.
    custom_dir = data.get("output_dir", "").strip()
    if custom_dir:
        output_dir = custom_dir
    else:
        temp_dir = Path(__file__).parent / "temp_downloads"
        temp_dir.mkdir(exist_ok=True)
        output_dir = str(temp_dir)

    if not url or not validate_youtube_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    if mode == "audio" and not _ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed. MP3 conversion requires ffmpeg."}), 400

    download_id = start_download(url, quality=quality, mode=mode,
                                 bitrate=bitrate, output_dir=output_dir)
    return jsonify({"download_id": download_id})


# ─── SSE Progress Stream ──────────────────────────────────────────────────────

@app.route("/api/progress/<download_id>")
def progress(download_id: str):
    def generate():
        # Send a padding string to force browsers/proxies to flush the buffer
        yield f": {' ' * 2048}\n\n"

        while True:
            state = get_download_state(download_id)
            if state is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break

            yield f"data: {json.dumps(state)}\n\n"

            status = state.get("status")
            if status in ("done", "error", "cancelled"):
                # Clean up after a short delay to let client read final state
                # Don't cleanup immediately if done; we need to serve the file!
                if status != "done":
                    time.sleep(1)
                    cleanup_download(download_id)
                break

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    })


# ─── Serve File for Browser Download ──────────────────────────────────────────

@app.route("/api/serve_file/<download_id>")
def serve_file(download_id: str):
    state = get_download_state(download_id)
    if not state or not state.get("filepath"):
        return "File not found or expired", 404
        
    filepath = state.get("filepath")
    if not os.path.exists(filepath):
        return "File does not exist on server", 404
        
    try:
        # Serve the file as an attachment to trigger browser download
        # Extract filename and ensure it's safe for headers
        import urllib.parse
        filename = os.path.basename(filepath)
        safe_filename = urllib.parse.quote(filename)
        
        response = send_file(filepath, as_attachment=True, download_name=filename)
        # Add a custom header to help frontend debug
        response.headers["X-File-Name"] = safe_filename
        # Do NOT cleanup immediately; let the state persist so the browser can retry if needed.
        # We'll rely on the short-lived nature of the session or a separate cleanup.
        return response
    except Exception as exc:
        return str(exc), 500


# ─── Cancel Download ──────────────────────────────────────────────────────────

@app.route("/api/cancel/<download_id>", methods=["POST"])
def cancel(download_id: str):
    cancel_download(download_id)
    return jsonify({"status": "cancelling"})


# ─── Open Folder (Windows / macOS / Linux) ────────────────────────────────────

@app.route("/api/open_folder", methods=["POST"])
def open_folder():
    data = request.get_json(silent=True) or {}
    filepath = data.get("filepath", "")
    folder = str(Path(filepath).parent) if filepath else get_downloads_folder()
    try:
        if os.name == "nt":
            os.startfile(folder)
        elif os.uname().sysname == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  📥 YouTube Downloader")
    print("  Open: http://localhost:5001")
    print("="*50 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5001, threaded=True)
