# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

import argparse
import logging
from pathlib import Path

import pytest

from iantirta.media import (
    DownloadOptions,
    download_media,
    extract_info,
    get_lyrics,
)

URL = "https://www.youtube.com/watch?v=WOal7KSVbTI"
OUTPUT = Path("test-output")


@pytest.mark.manual
def test_extract_info():
    print("\n=== EXTRACT INFO ===")

    info = extract_info(URL)

    print(f"Title:     {info.title}")
    print(f"Artist:    {info.artist}")
    print(f"Publisher: {info.uploader}")
    print(f"Duration:  {info.duration:.1f}s")
    print(f"Thumbnail: {info.thumbnail}")

    assert info.title
    assert info.duration >= 0


@pytest.mark.manual
def test_get_lyrics_real():
    print("\n=== GET LYRICS ===")

    info = extract_info(URL)

    lyrics = get_lyrics(
        title=info.title,
        artist=info.artist,
        publisher=info.uploader,
        duration=info.duration,
    )

    if lyrics is None:
        print("No lyrics found.")
        return

    print(f"Source: {lyrics.source}")
    print(f"Title:  {lyrics.title}")
    print(f"Artist: {lyrics.artist}")
    print()
    print(lyrics.text[:500] + "...")

    assert lyrics.text


@pytest.mark.manual
def test_download_media():
    print("\n=== DOWNLOAD MEDIA ===")

    media = download_media(
        URL,
        OUTPUT,
        options=DownloadOptions(),
    )

    print(f"Video: {media.path}")
    print(f"Audio: {media.audio}")
    print(f"Audio path: {media.audio.path}")

    assert media.path.is_file()

    if media.audio.path is not None:
        assert media.audio.path.is_file()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A script with dynamic log levels.")
    
    parser.add_argument(
        '-l', '--loglevel',
        default='WARNING',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Set the logging level (default: WARNING)"
    )
    
    args = parser.parse_args()

    logging.basicConfig(
        level=args.loglevel.upper(),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)

    test_extract_info()
    test_get_lyrics_real()
    test_download_media()
