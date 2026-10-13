
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, fields

import requests.exceptions

from iantirta.media._http._http import BaseHTTP

__all__ = [
    "LyricMetadata",
    "LyricsSolver",
    "get_lyric",
]

_logger = logging.getLogger(__name__)


TITLE_OR_ARTIST_RE = re.compile(r"^(?P<first>.+?)\s*[-–—]\s*(?P<second>.+?)$")

YOUTUBE_TRANSLATE_RE = re.compile(r"\s*(?:\/\/\/|\/\/|｜|\|)\s*.*$")

YOUTUBE_NOISE_WORDS = [
    "official", "official audio", "official video",
    "official music video", "music video", "lyrics",
    "lyric video", "lirik", "video", "audio", "visualizer",
    "performance", "live", "live-performance", "mv", "hd",
    "4k", "8k", "remastered", "remaster", "karaoke", "instrumental",
    "cover", "speed up", "slowed", "reverb", "nightcore"
]


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


@dataclass
class LyricMetadata:
    id: int
    trackName: str
    artistName: str
    albumName: str
    duration: float
    name: str
    plainLyrics: str

    score: float | None = None
    title_score: float | None = None
    artist_score: float | None = None
    duration_score: float | None = None

    @classmethod
    def from_dict(cls, **datas):
        valid_keys = {f.name for f in fields(cls)}
        valid_datas = {k: v for k, v in datas.items() if k in valid_keys}
        
        return cls(**valid_datas)

    def make_score(self, title: str, artist: str, duration: float, *, logger=None) -> None:
        from iantirta.text import similarity
        (logger or _logger).debug(f"Making Score between: {title} {artist} {duration}")
        self.title_score = similarity(
            self.trackName,
            title,
            normalize={"punctuation": True},
        )
        self.artist_score = similarity(
            self.artistName,
            artist,
            normalize={"punctuation": True},
        )
        self.duration_score = _duration_score(
            self.duration,
            duration,
        )
        self.score = (
            (self.title_score * 45)
            + (self.artist_score * 25)
            + (self.duration_score * 10)
        )


def clean_title(title: str) -> str:
    import iantirta.text as text_utils

    title = title.strip()

    YOUTUBE_TRANSLATE_RE.sub(title, "")

    title = text_utils.normalize(title, kaldi=True)
    title = text_utils.filter_text(title, YOUTUBE_NOISE_WORDS)
    
    return title.strip(" -–—")


def _iter_title(title: str) -> Iterator[str]:
    tokens = title.split()

    for size in range(len(tokens), 0, -1):
        yield " ".join(tokens[:size])


@dataclass
class LyricsSolver:
    title: str
    artist: str
    duration: float

    threshold: float = 70.0

    _resolved: str | None = None

    logger: logging.Logger | None = None

    def __post_init__(self):
        if not self.logger:
            self.logger = _logger

        self.http_api = BaseHTTP()

    def _lrclib_search(self, params):
        """Lrclib api search

        Supported parameters:
            the same as get without id and duration

            q: str (conditional)
        """
        url = "https://lrclib.net/api/search"
        res = self.http_api.request("get", url, params=params)
        self.http_api.raise_for_status(res)

        return res.json()

    def _lrclib_get(self, params):
        """Lrclib api get
        
        Supported parameters:
            track_name: str (required)
            artist_name: str (required)
            album_name: str
            duration: float

            **or**
            id: str
        """
        url = "https://lrclib.net/api/get"
        res = self.http_api.request("get", url, params=params)
        self.http_api.raise_for_status(res)

        return res.json()

    def _resolved_lyrics(self) -> str:
        
        match = TITLE_OR_ARTIST_RE.match(self.title)

        title = clean_title(self.title)
        self.logger.debug(f"Clean Title: {title}")
        
        title_candidates = []
        artist_candidates = []

        if match:
            first = match.group("first").strip()
            second = match.group("second").strip()

            first = clean_title(first)
            second = clean_title(second)

            if first.lower() in self.artist.lower() or self.artist.lower() in first.lower():
                # first is artist and artist is artist
                artist_candidates.append(self.artist)
                title_candidates.append(second)

            elif second.lower() in self.artist.lower() or self.artist.lower() in second.lower():
                # second is artist and artist is artist
                artist_candidates.append(self.artist)
                title_candidates.append(first)

            else:
                # artist is a channel name or first and second is not artist
                # we can't possibly know from this.
                artist_candidates.extend([first, second])
                title_candidates.extend([first, second, title])
        else:
            # means that title doesnt have any artist name in it.
            title_candidates.append(title)
            artist_candidates.append(self.artist)

        self.logger.debug(f"Title candidates={title_candidates}, Artist candidates={artist_candidates}")

        seen: set[tuple[str, str]] = set()
        candidates: list[tuple[str, str]] = []
        for _artist in artist_candidates:
            for _title in title_candidates:
                key = (
                    _title.casefold(),
                    _artist.casefold(),
                )
                if key in seen:
                    continue

                seen.add(key)
                candidates.append(
                    (_title, _artist)
                )

        self.logger.debug(f"Get candidates={candidates}")
        for _title, _artist in candidates:
            for __title in _iter_title(_title):
                params = {"track_name": __title, "artist_name": _artist, "duration": self.duration}
                param_variations = [
                    {"track_name": __title, "artist_name": _artist, "duration": self.duration},
                    {"track_name": __title, "artist_name": _artist}
                ]
                for params in param_variations:
                    try:
                        res = self._lrclib_get(params)
                        return LyricMetadata.from_dict(**res)
    
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 404:
                            self.logger.warning(f"Lyric not found using params={params}")
                            continue
                        raise


        #         lyric.make_score(self.title, self.lyrics)

        #         if lyric.score > self.threshold:
        #             return lyric.lyric
        #         else:
        #             _logger.warning(f"Dropping lyrics as its score doesnt meet the threshold.")

        # _logger.debug("Cannot get from direct api get, trying to search...")
        # for _title in title_candidates:
        #     titles = _iter_title(_title)
        #     for __title in titles:
        #         params = {"track_name": __title}
        #         self.logger.debug(f"Searching for: {params}")
        #         try:
        #             res = self._lrclib_search(params)
        #         except NotFound:
        #             continue

        #         for r in res:
        #             r_artist = str(r.get("artistName", "")).lower()
        #             r_album = str(r.get("albumName", "")).lower()
        #             r_name = str(r.get("name", "")).lower()
        #             r_track = str(r.get("trackName", "")).lower()

        #             lyric_debug_str = (
        #                 f'title=`{r.get("name")}` '
        #                 f'artistName=`{r.get("artistName")}` '
        #                 f'albumName=`{r.get("albumName")}` '
        #                 f'duration=`{r.get("duration")}` '
        #                 f'trackName=`{r.get("trackName")}` '
        #             )
        #             exact_match = (
        #                 r_artist in artist_candidates or 
        #                 r_album in artist_candidates or 
        #                 r_name in title_candidates or 
        #                 r_track in title_candidates
        #             )
        #             partial_artist = any(cand.lower() in r_artist for cand in artist_candidates)
        #             partial_title = any(cand.lower() in r_name for cand in title_candidates)

        #             if exact_match or partial_artist or partial_title:
        #                 lyric = LyricMetadata.from_dict(**r)
        #                 lyric.make_score(self.title, self.artist, self.duration)
        #                 if lyric.score > self.threshold:
        #                     return lyric.plainLyrics
        #                 else:
        #                     self.logger.warning(f"Dropping lyrics as its score doesnt meet the threshold ({lyric.score}/{self.threshold}). {lyric_debug_str}")
        #             else:
        #                 self.logger.warning(f"Dropping result as the artist name doesnt really match with ours, {lyric_debug_str}")
        #             # if r["artistName"] in artist_candidates:
        #             #     lyric = LrcLibLyric.from_dict(r)

        #             #     lyric.make_score(self.title, self.lyrics)
        #             #     if lyric.score > self.threshold:
        #             #         return lyric.lyric

        #             #     else:
        #             #         self.logger.warning(f"Dropping lyrics as its score doesnt meet the threshold.")
        #             # else:
        #             #     self.logger.warning(f"Dropping result as the artist name doesnt really match with ours, {r}")

        raise RuntimeError()
            
    @property
    def resolved(self) -> LyricMetadata:
        if self._resolved is None:
            self._resolved = self._resolved_lyrics()

        return self._resolved


def get_lyric(title: str, artist: str, duration: float, *, logger=None) -> LyricMetadata:
    return LyricsSolver(logger=logger).resolved


if __name__ == "__main__":
    from iantirta.telemetry.netsvc import setup_logger
    setup_logger("iantirta")
    _logger.setLevel(logging.DEBUG)

    # lyric = LyricsSolver(
    #     "MAHALINI - MENCINTAIMU (OST. 2ND MIRACLE IN CELL NO.7) OFFICIAL LYRIC VIDEO",
    #     "HITS Records",
    #     286
    # )
    # lyric = LyricsSolver(
    #     "Naura Ayu - Jalan Tengah | Official Music Video",
    #     "Trinity Optima Production",
    #     349
    # )
    lyric = LyricsSolver(
        "The Panturas - You and Me Against the World (Official Music Video)",
        "The Panturas",
        220
    )
    print(
        lyric.resolved
    )
