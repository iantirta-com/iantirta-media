# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from __future__ import annotations

import typing as t
from dataclasses import dataclass
from pathlib import Path

from .files import MediaFile

__all__ = [
    "DownloadOptions",
    "VideoInfo",
    "download_media",
    "extract_info",
]


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """
    Options controlling media downloads.

    Args:
        cookies: Optional cookies file.
        retries: Number of download retries.
        socket_timeout: Network timeout in seconds.
    """

    cookies: Path | None = None
    retries: int = 3
    socket_timeout: int = 30


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """
    Metadata extracted from a media URL.

    Args:
        title: Media title.
        artist: Artist name.
        uploader: Uploader or channel name.
        duration: Duration in seconds.
        source: Original media URL.
        thumbnail: Optional thumbnail URL.
    """

    title: str
    duration: float
    source: str
    uploader: str | None = None
    artist: str | None = None
    thumbnail: str | None = None


def download_media(
    url: str,
    output_dir: str | Path,
    *,
    options: DownloadOptions | None = None,
) -> MediaFile:
    """
    Download audio from a media URL.

    Args:
        url: URL of the media to download.
        output_dir: Directory where the downloaded file will be stored.
        cookies: Optional path to a cookies file.

    Returns:
        A MediaFile containing the downloaded video and extracted audio.

    Raises:
        ValueError: If `url` is empty.
        FileNotFoundError: If the cookies file does not exist.
        RuntimeError: If the download fails.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError(
            "Youtube audio download requires 'yt-dlp'. "
            "Install it with: pip install 'iantirta-karaoke[youtube]'"
        ) from exc
  
    if not url.strip():
        raise ValueError("url must not be empty")

    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cookiefile: str | None = None
    download_options = options or DownloadOptions()

    if download_options.cookies is not None:
        cookie_path = Path(download_options.cookies).expanduser().resolve()

        if not cookie_path.is_file():
            raise FileNotFoundError(
                f"Cookie file does not exist: {cookie_path}"
            )

        cookiefile = str(cookie_path)

    yt_options = {
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,

        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "continuedl": True,

        "retries": download_options.retries,
        "fragment_retries": download_options.retries,
        "socket_timeout": download_options.socket_timeout,
    }

    if cookiefile is not None:
        yt_options["cookiefile"] = cookiefile

    try:
        with yt_dlp.YoutubeDL(yt_options) as ydl:
            info = ydl.extract_info(url, download=True)

            video_path = Path(ydl.prepare_filename(info))

            if not video_path.is_file():
                raise FileNotFoundError(
                    f"Download completed but output file was not found: "
                    f"{video_path}"
                )

    except Exception as exc:
        raise RuntimeError(
            f"Failed to download audio from {url!r}"
        ) from exc

    return MediaFile(
        path=video_path,
        source=url,
        title=info.get("title"),
        artist=info.get("artist"),
        duration=float(info.get("duration") or 0),
    )


def extract_info(url: str) -> VideoInfo:
    """
    Extract metadata from a media URL.

    Args:
        url: URL of the media to inspect.

    Returns:
        Extracted media metadata.

    Raises:
        ValueError: If `url` is empty.
        RuntimeError: If metadata extraction fails.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError(
            "Youtube url extraction requires 'yt-dlp'. "
            "Install it with: pip install 'iantirta-karaoke[youtube]'"
        ) from exc

    if not url.strip():
        raise ValueError("url must not be empty")

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to extract media information from {url!r}"
        ) from exc

    return VideoInfo(
        title=info.get("title") or "Unknown",
        artist=(
            info.get("artist")
            or None
        ),
        uploader=(
            info.get("uploader")
            or info.get("channel")
        ),
        duration=float(info.get("duration") or 0),
        source=url,
        thumbnail=info.get("thumbnail"),
    )
