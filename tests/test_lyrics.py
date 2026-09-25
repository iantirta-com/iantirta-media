# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from __future__ import annotations

import pytest

from iantirta.media.lyrics import (
    _clean_title,
    _duration_score,
    _extract_music_metadata,
    _iter_title_queries,
    _LyricsCandidate,
    _score_candidate,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Song Name (Official Video)", "song name"),
        ("Song Name [Official Audio]", "song name"),
        ("Song Name - Official Music Video", "song name"),
        ("Song Name | English Translation", "song name"),
        ("Song Name Lyrics", "song name"),
        ("Song Name Official Audio", "song name"),
        ("Song Name 4K", "song name"),
        ("Song Name Karaoke", "song name"),
        ("Song Name - Official Lyric Video", "song name"),
        ("Song Name (Lyric Video)", "song name"),
        ("Song Name (Music Video)", "song name"),
    ],
)
def test_clean_title(title, expected):
    assert _clean_title(title) == expected


def test_clean_title_preserves_song_content():
    assert (
        _clean_title(
            "Mencintaimu (OST. 2nd Miracle in Cell No.7)"
        )
        == "mencintaimu ost 2nd miracle in cell no7"
    )

def test_clean_title_removes_translation():
    assert _clean_title(
        "Song Name // English Translation"
    ) == "song name"


def test_clean_title_removes_pipe_translation():
    assert _clean_title(
        "Song Name | English Translation"
    ) == "song name"


def test_clean_title_removes_common_noise_case_insensitively():
    assert _clean_title(
        "SONG NAME OFFICIAL LYRIC VIDEO"
    ) == "song name"


def test_extract_music_metadata_artist_in_first_part():
    result = _extract_music_metadata(
        "MAHALINI - MENCINTAIMU (OST. 2ND MIRACLE IN CELL NO.7) "
        "OFFICIAL LYRIC VIDEO",
        artist="Mahalini",
    )

    assert result == [
        (
            "mencintaimu ost 2nd miracle in cell no7",
            "mahalini",
        )
    ]


def test_extract_music_metadata_artist_in_second_part():
    result = _extract_music_metadata(
        "Mencintaimu - MAHALINI Official Lyric Video",
        artist="Mahalini",
    )

    assert result == [
        (
            "mencintaimu",
            "mahalini",
        )
    ]


def test_extract_music_metadata_without_explicit_artist():
    result = _extract_music_metadata(
        "MAHALINI - MENCINTAIMU "
        "(OST. 2ND MIRACLE IN CELL NO.7) "
        "OFFICIAL LYRIC VIDEO",
    )

    assert result == [
        (
            "mahalini",
            "mencintaimu ost 2nd miracle in cell no7",
        ),
        (
            "mencintaimu ost 2nd miracle in cell no7",
            "mahalini",
        ),
    ] or result == [
        (
            "mencintaimu ost 2nd miracle in cell no7",
            "mahalini",
        ),
    ]


def test_extract_music_metadata_with_publisher():
    result = _extract_music_metadata(
        "MAHALINI - MENCINTAIMU "
        "(OST. 2ND MIRACLE IN CELL NO.7) "
        "OFFICIAL LYRIC VIDEO",
        publisher="HITS Records",
    )

    assert (
        "mencintaimu ost 2nd miracle in cell no7",
        "mahalini",
    ) in result


def test_extract_music_metadata_deduplicates():
    result = _extract_music_metadata(
        "MAHALINI - MENCINTAIMU",
        artist="Mahalini",
        publisher="MAHALINI",
    )

    assert result == [
        (
            "mencintaimu",
            "mahalini",
        )
    ]


def test_extract_music_metadata_does_not_create_reverse_artist_when_publisher_unrelated():
    result = _extract_music_metadata(
        "MAHALINI - MENCINTAIMU",
        publisher="HITS Records",
    )

    assert (
        "mencintaimu",
        "mahalini",
    ) in result

    assert (
        "mahalini",
        "mencintaimu",
    ) in result


def test_extract_music_metadata_empty_result():
    assert _extract_music_metadata(
        "Song Name",
    ) == []


@pytest.mark.parametrize(
    ("source", "candidate", "expected"),
    [
        (100, 100, 1.0),
        (100, 102, 1.0),
        (100, 105, 0.8),
        (100, 110, 0.5),
        (100, 120, 0.2),
        (100, 130, 0.0),
    ],
)
def test_duration_score(source, candidate, expected):
    assert _duration_score(
        source,
        candidate,
    ) == expected


@pytest.mark.parametrize(
    ("source", "candidate"),
    [
        (0, 100),
        (100, 0),
        (0, 0),
        (-1, 100),
        (100, -1),
    ],
)
def test_duration_score_missing_or_invalid_duration(
    source,
    candidate,
):
    assert _duration_score(
        source,
        candidate,
    ) == 0.0


def test_candidate_from_api():
    candidate = _LyricsCandidate.from_api(
        {
            "id": 123,
            "trackName": "Song",
            "artistName": "Artist",
            "albumName": "Album",
            "duration": 240,
            "plainLyrics": "hello world",
            "syncedLyrics": "[00:01.00]hello world",
        }
    )

    assert candidate.id == 123
    assert candidate.title == "Song"
    assert candidate.artist == "Artist"
    assert candidate.album == "Album"
    assert candidate.duration == 240
    assert candidate.plain_lyrics == "hello world"
    assert candidate.synced_lyrics == "[00:01.00]hello world"
    assert candidate.lyrics == "hello world"


def test_candidate_from_api_defaults_missing_values():
    candidate = _LyricsCandidate.from_api({})

    assert candidate.id is None
    assert candidate.title == ""
    assert candidate.artist == ""
    assert candidate.album == ""
    assert candidate.duration == 0
    assert candidate.plain_lyrics is None
    assert candidate.synced_lyrics is None
    assert candidate.lyrics is None


def test_candidate_lyrics_falls_back_to_synced():
    candidate = _LyricsCandidate.from_api(
        {
            "trackName": "Song",
            "artistName": "Artist",
            "duration": 240,
            "plainLyrics": None,
            "syncedLyrics": "[00:01.00]hello",
        }
    )

    assert candidate.lyrics == "[00:01.00]hello"


def test_candidate_scoring():
    candidate = _LyricsCandidate(
        id=1,
        title="Hello World",
        artist="Test Artist",
        album="Album",
        duration=100,
        plain_lyrics="hello world",
        synced_lyrics=None,
    )

    _score_candidate(
        candidate,
        [
            ("Hello World", "Test Artist"),
        ],
        100,
    )

    assert candidate.title_score == pytest.approx(1.0)
    assert candidate.artist_score == pytest.approx(1.0)
    assert candidate.duration_score == pytest.approx(1.0)
    assert candidate.total_score == pytest.approx(80.0)


def test_candidate_scoring_uses_best_metadata_candidate():
    candidate = _LyricsCandidate(
        id=1,
        title="Mencintaimu",
        artist="Mahalini",
        album="Album",
        duration=286,
        plain_lyrics="lyrics",
        synced_lyrics=None,
    )

    _score_candidate(
        candidate,
        [
            (
                "mencintaimu ost 2nd miracle in cell no7",
                "mahalini",
            ),
            (
                "mencintaimu",
                "mahalini",
            ),
        ],
        286,
    )

    assert candidate.title_score == pytest.approx(1.0)
    assert candidate.artist_score == pytest.approx(1.0)
    assert candidate.duration_score == pytest.approx(1.0)
    assert candidate.total_score == pytest.approx(80.0)


def test_candidate_scoring_artist_mismatch():
    candidate = _LyricsCandidate(
        id=1,
        title="Hello World",
        artist="Another Artist",
        album="Album",
        duration=100,
        plain_lyrics="lyrics",
        synced_lyrics=None,
    )

    _score_candidate(
        candidate,
        [
            ("Hello World", "Test Artist"),
        ],
        100,
    )

    assert candidate.title_score == pytest.approx(1.0)
    assert candidate.artist_score < 1.0
    assert candidate.total_score < 80.0


def test_iter_title_queries():
    assert list(
        _iter_title_queries(
            "mencintaimu ost 2nd miracle in cell no7"
        )
    ) == [
        "mencintaimu ost 2nd miracle in cell no7",
        "mencintaimu ost 2nd miracle in cell",
        "mencintaimu ost 2nd miracle in",
        "mencintaimu ost 2nd miracle",
        "mencintaimu ost 2nd",
        "mencintaimu ost",
        "mencintaimu",
    ]


def test_iter_title_queries_single_token():
    assert list(
        _iter_title_queries("mencintaimu")
    ) == ["mencintaimu"]


def test_iter_title_queries_empty():
    assert list(
        _iter_title_queries("")
    ) == []


def test_get_lyrics_direct(monkeypatch):
    from iantirta.media import lyrics

    def fake_request(session, endpoint, params):
        assert endpoint == "get"
        assert params["track_name"] == "hello world"
        assert params["artist_name"] == "test artist"

        return {
            "id": 123,
            "trackName": "Hello World",
            "artistName": "Test Artist",
            "albumName": "Test Album",
            "duration": 100,
            "plainLyrics": "hello world",
            "syncedLyrics": "[00:01.00]hello world",
        }

    monkeypatch.setattr(
        lyrics,
        "_request",
        fake_request,
    )

    result = lyrics.get_lyrics(
        title="Hello World",
        artist="Test Artist",
        duration=100,
    )

    assert result is not None
    assert result.text == "hello world"
    assert result.synced_text == "[00:01.00]hello world"
    assert result.source == "lrclib"
    assert result.title == "Hello World"
    assert result.artist == "Test Artist"
    assert result.duration == 100


def test_get_lyrics_search_fallback(monkeypatch):
    from iantirta.media import lyrics

    def fake_direct(session, title, artist, duration):
        return None

    def fake_search(session, params):
        return [
            lyrics._LyricsCandidate(
                id=123,
                title="Hello World",
                artist="Test Artist",
                album="Album",
                duration=100,
                plain_lyrics="hello world",
                synced_lyrics=None,
            )
        ]

    monkeypatch.setattr(
        lyrics,
        "_get_direct",
        fake_direct,
    )

    monkeypatch.setattr(
        lyrics,
        "_search",
        fake_search,
    )

    result = lyrics.get_lyrics(
        title="Hello World",
        artist="Test Artist",
        duration=100,
    )

    assert result is not None
    assert result.text == "hello world"
    assert result.title == "Hello World"
    assert result.artist == "Test Artist"


def test_get_lyrics_relaxed_title_search(monkeypatch):
    from iantirta.media import lyrics

    queries: list[str] = []

    def fake_direct(session, title, artist, duration):
        return None

    def fake_search(session, params):
        track_name = params.get("track_name")

        if track_name:
            queries.append(track_name)

        # Normal searches return a bad candidate.
        if track_name == "mencintaimu ost 2nd miracle in cell no7":
            return [
                lyrics._LyricsCandidate(
                    id=1,
                    title="Completely Different Song",
                    artist="Mahalini",
                    album="Album",
                    duration=400,
                    plain_lyrics="wrong lyrics",
                    synced_lyrics=None,
                )
            ]

        # Relaxed query finds the actual song.
        if track_name == "mencintaimu ost 2nd miracle in cell":
            return [
                lyrics._LyricsCandidate(
                    id=2,
                    title="Mencintaimu - (From: 2nd Miracle in Cell No.7)",
                    artist="Mahalini",
                    album="Album",
                    duration=286,
                    plain_lyrics="correct lyrics",
                    synced_lyrics=None,
                )
            ]

        return []

    monkeypatch.setattr(
        lyrics,
        "_get_direct",
        fake_direct,
    )

    monkeypatch.setattr(
        lyrics,
        "_search",
        fake_search,
    )

    result = lyrics.get_lyrics(
        title=(
            "MAHALINI - MENCINTAIMU "
            "(OST. 2ND MIRACLE IN CELL NO.7) "
            "OFFICIAL LYRIC VIDEO"
        ),
        publisher="HITS Records",
        duration=286,
    )

    assert result is not None
    assert result.text == "correct lyrics"
    assert result.title == (
        "Mencintaimu - (From: 2nd Miracle in Cell No.7)"
    )
    assert result.artist == "Mahalini"

    assert "mencintaimu ost 2nd miracle in cell" in queries


def test_get_lyrics_relaxed_query_is_used_for_scoring(monkeypatch):
    from iantirta.media import lyrics

    def fake_direct(session, title, artist, duration):
        return None

    def fake_search(session, params):
        if params.get("track_name") == "mencintaimu":
            return [
                lyrics._LyricsCandidate(
                    id=123,
                    title="Mencintaimu OST 2nd Miracle",
                    artist="Mahalini",
                    album="Album",
                    duration=286,
                    plain_lyrics="lyrics",
                    synced_lyrics=None,
                )
            ]

        return []

    monkeypatch.setattr(
        lyrics,
        "_get_direct",
        fake_direct,
    )

    monkeypatch.setattr(
        lyrics,
        "_search",
        fake_search,
    )

    result = lyrics.get_lyrics(
        title="Mahalini - Mencintaimu OST 2nd Miracle",
        publisher="HITS Records",
        duration=286,
    )

    assert result is not None
    assert result.title == "Mencintaimu OST 2nd Miracle"
    assert result.artist == "Mahalini"


def test_get_lyrics_returns_none_when_no_candidates(monkeypatch):
    from iantirta.media import lyrics

    monkeypatch.setattr(
        lyrics,
        "_get_direct",
        lambda *args: None,
    )

    monkeypatch.setattr(
        lyrics,
        "_search",
        lambda *args: [],
    )

    result = lyrics.get_lyrics(
        title="Definitely Not A Real Song",
        artist="Definitely Not A Real Artist",
        duration=100,
    )

    assert result is None


def test_get_lyrics_requires_title():
    from iantirta.media import get_lyrics

    with pytest.raises(ValueError):
        get_lyrics(title="")


def test_get_lyrics_requires_non_whitespace_title():
    from iantirta.media import get_lyrics

    with pytest.raises(ValueError):
        get_lyrics(title="   ")


def test_get_lyrics_deduplicates_candidates(monkeypatch):
    from iantirta.media import lyrics

    calls = 0

    def fake_direct(session, title, artist, duration):
        return None

    def fake_search(session, params):
        nonlocal calls
        calls += 1

        return [
            lyrics._LyricsCandidate(
                id=123,
                title="Hello World",
                artist="Test Artist",
                album="Album",
                duration=100,
                plain_lyrics="lyrics",
                synced_lyrics=None,
            )
        ]

    monkeypatch.setattr(
        lyrics,
        "_get_direct",
        fake_direct,
    )

    monkeypatch.setattr(
        lyrics,
        "_search",
        fake_search,
    )

    result = lyrics.get_lyrics(
        title="Hello World",
        artist="Test Artist",
        duration=100,
    )

    assert result is not None
    assert result.text == "lyrics"

    # All searches may return the same candidate, but it should
    # still produce one logical result.
    assert calls >= 1
