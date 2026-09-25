# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from __future__ import annotations

import logging
import re
import typing as t
from dataclasses import dataclass

import requests
from iantirta.text import filter_text, normalize

if t.TYPE_CHECKING:
    from iantirta.media.youtube import VideoInfo

__all__ = ["Lyrics", "get_lyrics"]

logger = logging.getLogger(__name__)


# Store

@dataclass(frozen=True, slots=True)
class Lyrics:
    """
    Represents lyrics retrieved from a lyrics provider.

    Attributes:
        text: Plain lyrics text.
        synced_text: Optional timestamped lyrics text.
        source: Provider or source identifier.
    """

    text: str
    synced_text: str | None = None
    source: str | None = None
    title: str | None = None
    artist: str | None = None
    duration: float | None = None


@dataclass(slots=True)
class _LyricsCandidate:
    id: int | None
    title: str
    artist: str
    album: str
    duration: float
    plain_lyrics: str | None
    synced_lyrics: str | None

    title_score: float = 0.0
    artist_score: float = 0.0
    duration_score: float = 0.0
    total_score: float = 0.0

    @classmethod
    def from_api(cls, data: dict[str, t.Any]) -> _LyricsCandidate:
        return cls(
            id=data.get("id"),
            title=data.get("trackName") or "",
            artist=data.get("artistName") or "",
            album=data.get("albumName") or "",
            duration=float(data.get("duration") or 0),
            plain_lyrics=data.get("plainLyrics"),
            synced_lyrics=data.get("syncedLyrics"),
        )

    @property
    def lyrics(self) -> str | None:
        return self.plain_lyrics or self.synced_lyrics


# Scoring

def _duration_score(
    source: float,
    candidate: float,
) -> float:
    """
    Calculate a duration similarity score.

    Args:
        source: Source duration in seconds.
        candidate: Candidate duration in seconds.

    Returns:
        Score between 0.0 and 1.0.
    """
    if source <= 0 or candidate <= 0:
        return 0.0

    difference = abs(source - candidate)

    if difference <= 2:
        return 1.0
    if difference <= 5:
        return 0.8
    if difference <= 10:
        return 0.5
    if difference <= 20:
        return 0.2

    return 0.0


def _score_candidate(
    candidate: _LyricsCandidate,
    metadata_candidates: list[tuple[str, str]],
    duration: float,
) -> None:
    """
    Score a lyrics candidate against source metadata.

    Args:
        candidate: Candidate to score.
        metadata_candidates: List of tuple[(artist candidate, title candidate)]
        duration: Source duration in seconds.
    """
    from iantirta.text import similarity

    best_title_score = 0.0
    best_artist_score = 0.0

    for title, artist in metadata_candidates:
        title_score = similarity(
            title,
            candidate.title,
            normalize={
                "punctuation": True
            },
        )

        artist_score = similarity(
            artist,
            candidate.artist,
            normalize={
                "punctuation": True
            },
        )

        best_title_score = max(
            best_title_score,
            title_score,
        )

        best_artist_score = max(
            best_artist_score,
            artist_score,
        )

    candidate.title_score = best_title_score
    candidate.artist_score = best_artist_score
    candidate.duration_score = _duration_score(
        duration,
        candidate.duration,
    )

    candidate.total_score = (
        candidate.title_score * 45
        + candidate.artist_score * 25
        + candidate.duration_score * 10
    )


# Helper

_YOUTUBE_NOISE_TEXTS = [
    "official", "official audio", "official video",
    "official music video", "music video", "lyrics",
    "lyric video", "lirik", "video", "audio", "visualizer",
    "performance", "live", "live-performance", "mv", "hd",
    "4k", "8k", "remastered", "remaster", "karaoke", "instrumental",
    "cover", "speed up", "slowed", "reverb", "nightcore"
]

def _clean_title(title: str) -> str:
    """
    Remove common video metadata from a song title.

    Args:
        title: Raw media title.

    Returns:
        Cleaned song title.
    """
    title = title.strip()

    # Remove translations such as:
    # Song Name // English Translation
    title = re.sub(
        r"\s*(?:///|//|｜|\|)\s*.*$",
        "",
        title,
    )

    # Remove parenthesized metadata commonly found in video titles.
    title = re.sub(
        r"\s*\(\s*"
        r"(?:"
        r"|original soundtrack\b.*?"
        r"|official\b.*?"
        r"|lyric(?:s)?\b.*?"
        r"|music video\b.*?"
        r"|official music video\b.*?"
        r"|official lyric video\b.*?"
        r"|audio\b.*?"
        r"|video\b.*?"
        r")"
        r"\)\s*",
        " ",
        title,
        flags=re.IGNORECASE,
    )

    # Remove common trailing video metadata.
    title = re.sub(
        r"\s+(?:"
        r"official"
        r"|official audio"
        r"|official video"
        r"|official music video"
        r"|official lyric video"
        r"|lyric video"
        r"|lyrics video"
        r"|lyrics"
        r"|audio"
        r"|video"
        r")\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = normalize(title, kaldi=True)
    title = filter_text(title, _YOUTUBE_NOISE_TEXTS)
    return title.strip(" -–—")


def _extract_music_metadata(
    title: str,
    artist: str | None = None,
    publisher: str | None = None,
) -> list[tuple[str, str]]:
    """
    Generate possible (title, artist) pairs from media metadata.

    The input may contain YouTube-style titles such as:

        MAHALINI - MENCINTAIMU (Official Lyric Video)

    Returns candidates ordered from most likely to least likely.
    """
    title = title.strip()
    artist = (artist or "").strip()
    publisher = (publisher or "").strip()

    candidates: list[tuple[str, str]] = []

    # Look for "Artist - Title".
    match = re.match(
        r"^(?P<first>.+?)\s*[-–—]\s*(?P<second>.+?)$",
        title,
    )

    if match:
        first = match.group("first").strip()
        second = match.group("second").strip()

        if not artist and not publisher:
            candidates.append((first, second))
            candidates.append((second, first))

    if artist:
        if match:
            # if artist in the first part
            if artist.casefold() in first.casefold():
                candidates.append((second, first))
            # if artist belong ot the second part
            elif artist.casefold() in second.casefold():
                candidates.append((first, second))
            # if artist doesn't belong to any of the part
            else:
                candidates.append((title, artist))
        else:
            candidates.append((title, artist))

    if publisher:
        if match:
            # if publisher in the first part in title, 
            # it means publisher == artist == first
            if publisher.casefold() in first.casefold():
                candidates.append((second, first))
            # if publisher in the first part in title, 
            # it means publisher == artist == second
            elif publisher.casefold() in second.casefold():
                candidates.append((first, second))
            # if publisher doesn't belong to any of the part
            # it means either `Artist - Title` or `Title - Artist`
            else:
                candidates.append((second, first))
                candidates.append((first, second))
        else:
            # Just in case, maybe add publisher as an artist
            candidates.append((title, publisher))

    # Normalize and deduplicate.
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for candidate_title, candidate_artist in candidates:
        candidate_title = _clean_title(candidate_title)
        candidate_artist = _clean_title(candidate_artist)

        if not candidate_title or not candidate_artist:
            continue

        key = (
            candidate_title.casefold(),
            candidate_artist.casefold(),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(
            (candidate_title, candidate_artist)
        )

    return result


# API

_LRCLIB_API = "https://lrclib.net/api"


def _request(
    session: requests.Session,
    endpoint: str,
    params: dict[str, t.Any],
) -> t.Any:
    """
    Send a request to LRCLIB.

    Args:
        session: HTTP session used for the request.
        endpoint: LRCLIB API endpoint.
        params: Query parameters.

    Returns:
        Decoded JSON response.

    Raises:
        RuntimeError: If the request fails.
    """
    url = f"{_LRCLIB_API}/{endpoint}"

    logger.debug(
        "LRCLIB request: endpoint=%s params=%r",
        endpoint,
        params,
    )

    try:
        response = session.get(
            url,
            params=params,
            timeout=30,
        )

        # if not found meaning it doesn't exist inside lrclib
        # and we return early before `raise_for_status()``
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        return response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"LRCLIB request failed: {endpoint}"
        ) from exc

    except ValueError as exc:
        raise RuntimeError(
            f"LRCLIB returned invalid JSON: {endpoint}"
        ) from exc


def _get_direct(
    session: requests.Session,
    title: str,
    artist: str,
    duration: float,
) -> _LyricsCandidate | None:
    """
    Retrieve a direct LRCLIB match.

    Args:
        session: HTTP session.
        title: Song title.
        artist: Artist name.
        duration: Song duration in seconds.

    Returns:
        Matching lyrics candidate, or None.
    """
    if not title or not artist:
        return None

    data = _request(
        session,
        "get",
        {
            "track_name": title,
            "artist_name": artist,
            "duration": round(duration),
        },
    )

    if not isinstance(data, dict):
        return None

    candidate = _LyricsCandidate.from_api(data)

    if not candidate.lyrics:
        return None

    return candidate


def _search(
    session: requests.Session,
    params: dict[str, t.Any],
) -> list[_LyricsCandidate]:
    """
    Search LRCLIB for lyrics candidates.

    Args:
        session: HTTP session.
        params: LRCLIB search parameters.

    Returns:
        Matching lyrics candidates.
    """
    data = _request(
        session,
        "search",
        params,
    )

    if not isinstance(data, list):
        return []

    return [
        _LyricsCandidate.from_api(item)
        for item in data
        if isinstance(item, dict)
    ]


def _iter_title_queries(title: str) -> t.Iterator[str]:
    tokens = title.split()

    for size in range(len(tokens), 0, -1):
        yield " ".join(tokens[:size])


def get_lyrics(
    *,
    title: str,
    artist: str | None = None,
    publisher: str | None = None,
    duration: float | None = None,
) -> Lyrics | None:
    """
    Retrieve lyrics for a song.

    The function first attempts a direct LRCLIB lookup and then
    searches for candidates when a direct match is unavailable.

    Args:
        title: Song title.
        artist: Optional artist name.
        duration: Optional song duration in seconds.

    Returns:
        A Lyrics object if a sufficiently matching result is found,
        otherwise None.

    Raises:
        ValueError: If `title` is empty.
        RuntimeError: If LRCLIB cannot be reached.
    """
    if not title.strip():
        raise ValueError("title must not be empty")

    duration = float(duration or 0)

    candidates_metadata = _extract_music_metadata(
        title,
        artist,
        publisher,
    )

    logger.info(
        "Lyrics metadata candidates: [title, artist]\n > %r",
        candidates_metadata,
    )

    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (X11; Linux x86_64) '
            'AppleWebKit/537.36 '
            '(KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    })

    # First: exact-ish lookup.
    for query_title, query_artist in candidates_metadata:
        candidate = _get_direct(
            session,
            query_title,
            query_artist,
            duration,
        )

        if candidate is None:
            continue

        logger.info(
            "Found direct LRCLIB match: %r - %r",
            query_title,
            query_artist,
        )

        return Lyrics(
            text=(
                candidate.plain_lyrics
                or candidate.synced_lyrics
                or ""
            ),
            synced_text=candidate.synced_lyrics,
            source="lrclib",
            title=candidate.title,
            artist=candidate.artist,
            duration=candidate.duration,
        )

    # Second: candidate searches.
    searches: list[dict[str, t.Any]] = []

    for query_title, query_artist in candidates_metadata:
        searches.extend(
            [
                {
                    "track_name": query_title,
                    "artist_name": query_artist,
                },
                {
                    "q": f"{query_artist} {query_title}",
                },
                {
                    "track_name": query_title,
                },
            ]
        )

    candidates: dict[t.Hashable, _LyricsCandidate] = {}

    for params in searches:
        for candidate in _search(session, params):
            key: t.Hashable = (
                candidate.id
                if candidate.id is not None
                else (
                    candidate.artist.casefold(),
                    candidate.title.casefold(),
                )
            )

            candidates[key] = candidate

    best = None
    low_conf = False
    if candidates:
        for candidate in candidates.values():
            _score_candidate(
                candidate,
                candidates_metadata,
                duration,
            )

        best = max(
            candidates.values(),
            key=lambda candidate: candidate.total_score,
        )

        # Same threshold as the old implementation for now.
        if best.total_score < 70:
            logger.warning(
                "Best LRCLIB candidate below confidence threshold: %.2f",
                best.total_score,
            )
            low_conf = True
    else:
        low_conf = True

    if low_conf:
        for meta_title, meta_artist in candidates_metadata:
            for query_title in _iter_title_queries(meta_title):
                for candidate in _search(
                    session,
                    {
                        "track_name": query_title,
                        "artist_name": meta_artist,
                    },
                ):
                    _score_candidate(
                        candidate,
                        [(meta_title, meta_artist)],
                        duration,
                    )

                    if (
                        best is None
                        or candidate.total_score > best.total_score
                    ):
                        best = candidate

                if best is not None and best.total_score >= 70:
                    break

    if best is None:
        logger.info("No suitable LRCLIB candidate found")
        return None

    logger.info(
        "Best LRCLIB candidate: %r - %r score=%.2f",
        best.artist,
        best.title,
        best.total_score,
    )

    # Same threshold as the old implementation for now.
    if best.total_score < 70:
        logger.warning(
            "Best LRCLIB candidate below confidence threshold: %.2f",
            best.total_score,
        )
        return None

    if not best.lyrics:
        return None

    return Lyrics(
        text=best.plain_lyrics or best.synced_lyrics or "",
        synced_text=best.synced_lyrics,
        source="lrclib",
        title=best.title,
        artist=best.artist,
        duration=best.duration,
    )
