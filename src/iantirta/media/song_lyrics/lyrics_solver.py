
import re


TITLE_OR_ARTIST_RE = re.compile(r"^(?P<first>.+?)\s*[-–—]\s*(?P<second>.+?)$")

YOUTUBE_TRANSLATE_RE = re.compile(r"\s*(?:///|//|｜|\|)\s*.*$")

YOUTUBE_NOISE_WORDS = [
    "official", "official audio", "official video",
    "official music video", "music video", "lyrics",
    "lyric video", "lirik", "video", "audio", "visualizer",
    "performance", "live", "live-performance", "mv", "hd",
    "4k", "8k", "remastered", "remaster", "karaoke", "instrumental",
    "cover", "speed up", "slowed", "reverb", "nightcore"
]

def clean_title(title: str) -> str:
    import iantirta.text as text_utils

    title = title.strip()

    YOUTUBE_TRANSLATE_RE.sub(title, "")

    title = text_utils.filter_words(title, YOUTUBE_NOISE_WORDS)

    return title.strip(" ( )").strip(" ()")

class LyricsSolver:
    title: str
    artist: str
    duration: float

    _resolved: str | None = None

    def _lrclib_search(self):
        """Lrclib api search

        Supported parameters:
            the same as get without id and duration

            q: str (conditional)
        """
        url = "https://lrclib.net/api/search"

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
        res = http_api.request(url, params)
        http_api.raise_for_status(res)

        return res.json()

    def _resolved_lyrics(self) -> str:
        title = clean_title(self.title)

        match = TITLE_OR_ARTIST_RE.match(title)

        title_candidates = []
        artist_candidates = []

        if match:
            first = match.group("first").strip()
            second = match.group("second").strip()

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

        for _artist in artist_candidates:
            for _title in title_candidates:
                params = {"track_name": _title, "artist_name": _artist}
                try:
                    res = self._lrclib_get(params)
                except NotFound as e:
                    params.remove("duration")
                    try:
                        res = self._lrclib_get(params)
                    except NotFound:
                        continue

                lyric = LrcLibLyric.from_dict(res)

                lyric.make_score(self.title, self.lyrics)

                if lyric.score > self.threshold:
                    return lyric.lyric
                else:
                    logger.warning(f"Dropping lyrics as its score doesnt meet the threshold.")

        for _title in title_candidates:
            titles = _iter_title(_title)
            for __title in titles:
                params = {"q": __title}
                try:
                    res = self._lrclib_search(params)
                except NotFound:
                    continue

                for r in res:
                    if r["artistName"] in artist_candidates:
                        lyric = LrcLibLyric.from_dict(r)

                        lyric.make_score(self.title, self.lyrics)
                        if lyric.score > self.threshold:
                            return lyric.lyric

                        else:
                            logger.warning(f"Dropping lyrics as its score doesnt meet the threshold.")
                    else:
                        logger.warning("Dropping result as the artist name doesnt really match with ours")

        raise RuntimeError()
            
    @property
    def resolved(self) -> str:
        if self._resolved is None:
            self._resolved = self._resolved_lyrics()

        return self._resolved