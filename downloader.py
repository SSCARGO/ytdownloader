import threading
import uuid
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional

import yt_dlp

from utils import sanitize_filename, get_downloads_folder

# --- Shared state for active downloads ---
# { download_id: { percent, speed, eta, status, filepath, error } }
_downloads: Dict[str, Dict[str, Any]] = {}
_cancel_flags: Dict[str, bool] = {}
_lock = threading.Lock()


def _get_state(download_id: str) -> Dict[str, Any]:
    with _lock:
        return dict(_downloads.get(download_id, {}))


def _update_state(download_id: str, **kwargs):
    with _lock:
        if download_id not in _downloads:
            _downloads[download_id] = {}
        _downloads[download_id].update(kwargs)


def get_download_state(download_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_downloads.get(download_id, {})) if download_id in _downloads else None


def cancel_download(download_id: str):
    with _lock:
        _cancel_flags[download_id] = True
        if download_id in _downloads:
            _downloads[download_id]["status"] = "cancelled"


def cleanup_download(download_id: str):
    with _lock:
        _downloads.pop(download_id, None)
        _cancel_flags.pop(download_id, None)


# ---------------------------------------------------------------------------

def get_info(url: str) -> Dict[str, Any]:
    """Extract video metadata without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Build clean list of video formats
    formats = []
    seen_heights = set()
    for f in info.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        ext = f.get("ext", "")

        # Only include progressive or video-only streams (we will merge later)
        if height and vcodec != "none" and ext in ("mp4", "webm"):
            label = f"{height}p"
            if label not in seen_heights:
                seen_heights.add(label)
                formats.append({
                    "format_id": f["format_id"],
                    "label": label,
                    "height": height,
                    "ext": ext,
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                })

    # Sort descending by height
    formats.sort(key=lambda x: x["height"], reverse=True)

    return {
        "title": info.get("title", "Unknown Title"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "uploader": info.get("uploader", "Unknown"),
        "webpage_url": info.get("webpage_url", url),
        "formats": formats,
    }


# ---------------------------------------------------------------------------

def _make_progress_hook(download_id: str):
    def hook(d: dict):
        # Check cancel
        with _lock:
            if _cancel_flags.get(download_id):
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = round((downloaded / total) * 100, 1) if total else 0
            speed = d.get("speed")
            eta = d.get("eta")

            speed_str = ""
            if speed:
                if speed >= 1_048_576:
                    speed_str = f"{speed / 1_048_576:.1f} MB/s"
                elif speed >= 1024:
                    speed_str = f"{speed / 1024:.1f} KB/s"
                else:
                    speed_str = f"{speed:.0f} B/s"

            eta_str = ""
            if eta is not None:
                if eta >= 3600:
                    eta_str = f"{int(eta//3600)}h {int((eta%3600)//60)}m"
                elif eta >= 60:
                    eta_str = f"{int(eta//60)}m {int(eta%60)}s"
                else:
                    eta_str = f"{int(eta)}s"

            _update_state(
                download_id,
                percent=percent,
                speed=speed_str,
                eta=eta_str,
                status="downloading",
            )

        elif status == "finished":
            _update_state(download_id, percent=100, status="processing", speed="", eta="")

    return hook


def _run_download(download_id: str, url: str, quality: str, mode: str,
                  bitrate: str, output_dir: str):
    """Executed in a background thread."""
    _update_state(download_id, percent=0, status="extracting", speed="", eta="")

    try:
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

        if mode == "audio":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "progress_hooks": [_make_progress_hook(download_id)],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": bitrate.replace("k", ""),
                }],
                "quiet": True,
                "no_warnings": True,
            }
        else:
            has_ffmpeg = shutil.which("ffmpeg") is not None
            # Video: pick resolution
            if has_ffmpeg:
                if quality == "best":
                    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                else:
                    h = quality.replace("p", "")
                    fmt = (
                        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
                    )
                ydl_opts = {
                    "format": fmt,
                    "outtmpl": outtmpl,
                    "merge_output_format": "mp4",
                    "progress_hooks": [_make_progress_hook(download_id)],
                    "quiet": True,
                    "no_warnings": True,
                }
            else:
                if quality == "best":
                    fmt = "best"
                else:
                    h = quality.replace("p", "")
                    fmt = f"best[height<={h}]/best"
                ydl_opts = {
                    "format": fmt,
                    "outtmpl": outtmpl,
                    "progress_hooks": [_make_progress_hook(download_id)],
                    "quiet": True,
                    "no_warnings": True,
                }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            # After post-processing the extension may change (e.g., .mp3)
            if mode == "audio":
                base = os.path.splitext(filepath)[0]
                filepath = base + ".mp3"

        _update_state(download_id, status="done", filepath=filepath, percent=100)

    except yt_dlp.utils.DownloadCancelled:
        _update_state(download_id, status="cancelled")
    except Exception as exc:
        print(f"[x] Download error: {exc}")
        _update_state(download_id, status="error", error=str(exc))


def start_download(url: str, quality: str = "best", mode: str = "video",
                   bitrate: str = "192k", output_dir: Optional[str] = None) -> str:
    """Start a download in a background thread and return a download_id."""
    download_id = str(uuid.uuid4())
    if not output_dir:
        output_dir = get_downloads_folder()

    with _lock:
        _cancel_flags[download_id] = False

    thread = threading.Thread(
        target=_run_download,
        args=(download_id, url, quality, mode, bitrate, output_dir),
        daemon=True,
    )
    thread.start()
    return download_id
