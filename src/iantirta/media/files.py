# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from __future__ import annotations

import subprocess
import typing as t
from dataclasses import dataclass
from pathlib import Path

if t.TYPE_CHECKING:
    from iantirta.audio.files import AudioFile


__all__ = ["MediaFile"]


@dataclass(frozen=True, slots=True)
class MediaFile:
    """
    Represents a locally available media file.

    Args:
        path: Path to the primary media file.
        source: Original source URL or identifier.
        audio: AudioFile representation for the media.
        title: Optional media title.
        artist: Optional artist, uploader, or channel name.
        duration: Optional duration in seconds.

    Returns:
        A structured representation of a local media file.
    """

    path: Path
    source: str
    title: str | None = None
    artist: str | None = None
    duration: float | None = None


    @property
    def audio(self) -> AudioFile:
        from iantirta.audio import get_audio_info

        if self.path.suffix.lower() == ".wav":
            return get_audio_info(self.path)

        audio_path = self.path.with_suffix(".wav")

        if not audio_path.is_file():
            self._extract_audio(audio_path)

        return get_audio_info(audio_path)


    def _extract_audio(self, output: Path) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-loglevel", "panic",
            "-i", str(self.path),
            "-vn",
            str(output),
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ffmpeg was not found. Please install FFmpeg."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Failed to extract audio from {self.path}\n"
                f"Command: {cmd}\n"
                f"Error:\n{exc.stderr}"
            ) from exc
