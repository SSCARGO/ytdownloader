import re
import os
import pathlib


def validate_youtube_url(url: str) -> bool:
    """Return True if url is a valid YouTube video or playlist URL."""
    patterns = [
        r"^https?://(www\.)?youtube\.com/watch\?.*v=[\w-]+",
        r"^https?://youtu\.be/[\w-]+",
        r"^https?://(www\.)?youtube\.com/shorts/[\w-]+",
        r"^https?://(www\.)?youtube\.com/playlist\?.*list=[\w-]+",
        r"^https?://(www\.)?youtube\.com/embed/[\w-]+",
    ]
    return any(re.search(p, url.strip()) for p in patterns)


def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in filenames on any major OS."""
    # Replace illegal chars with underscore
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name)
    # Collapse multiple spaces/underscores
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = re.sub(r"_+", "_", sanitized)
    # Limit length
    return sanitized[:200]


def get_downloads_folder() -> str:
    """Return the OS-appropriate Downloads folder path."""
    home = pathlib.Path.home()
    downloads = home / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return str(downloads)


def format_duration(seconds) -> str:
    """Convert seconds integer to HH:MM:SS or MM:SS string."""
    if not seconds:
        return "Unknown"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "Unknown"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_views(views) -> str:
    """Format view count with K/M/B suffix."""
    if not views:
        return "Unknown"
    try:
        views = int(views)
    except (TypeError, ValueError):
        return "Unknown"
    if views >= 1_000_000_000:
        return f"{views / 1_000_000_000:.1f}B"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)
