# # Part of Iantirta.com
# # See LICENSE file for full copyright and licensing details.

# from __future__ import annotations

# import pytest

# from iantirta.media.song_lyrics.lyrics_solver import (
#     clean_title,
#     _duration_score,
#     _iter_title,
# )
# from iantirta.media import (
#     get_lyric,
#     BaseHTTP,
#     LyricsSolver,
#     LyricMetadata
# )


# @pytest.mark.parametrize(
#     ("title", "expected"),
#     [
#         ("Song Name (Official Video)", "song name"),
#         ("Song Name [Official Audio]", "song name"),
#         ("Song Name - Official Music Video", "song name"),
#         ("Song Name | English Translation", "song name"),
#         ("Song Name Lyrics", "song name"),
#         ("Song Name Official Audio", "song name"),
#         ("Song Name 4K", "song name"),
#         ("Song Name Karaoke", "song name"),
#         ("Song Name - Official Lyric Video", "song name"),
#         ("Song Name (Lyric Video)", "song name"),
#         ("Song Name (Music Video)", "song name"),
#     ],
# )
# def test_clean_title(title, expected):
#     assert clean_title(title) == expected


# def test_clean_title_preserves_song_content():
#     assert (
#         clean_title(
#             "Mencintaimu (OST. 2nd Miracle in Cell No.7)"
#         )
#         == "mencintaimu ost 2nd miracle in cell no7"
#     )

    
# def test_clean_title_removes_translation():
#     assert clean_title(
#         "Song Name // English Translation"
#     ) == "song name"


# def test_clean_title_removes_pipe_translation():
#     assert clean_title(
#         "Song Name | English Translation"
#     ) == "song name"


# def test_clean_title_removes_common_noise_case_insensitively():
#     assert clean_title(
#         "SONG NAME OFFICIAL LYRIC VIDEO"
#     ) == "song name"


# def test_iter_title():
#     assert list(
#         _iter_title(
#             "mencintaimu ost 2nd miracle in cell no7"
#         )
#     ) == [
#         "mencintaimu ost 2nd miracle in cell no7",
#         "mencintaimu ost 2nd miracle in cell",
#         "mencintaimu ost 2nd miracle in",
#         "mencintaimu ost 2nd miracle",
#         "mencintaimu ost 2nd",
#         "mencintaimu ost",
#         "mencintaimu",
#     ]


# def test_iter_title_queries_single_token():
#     assert list(
#         _iter_title("mencintaimu")
#     ) == ["mencintaimu"]


# def test_iter_title_queries_empty():
#     assert list(
#         _iter_title("")
#     ) == []


# def test_get_lyrics_direct(monkeypatch):
    
#     def fake_request(session, endpoint, params):
#         assert endpoint == "get"
#         assert params["track_name"] == "hello world"
#         assert params["artist_name"] == "test artist"

#         return {
#             "id": 123,
#             "trackName": "Hello World",
#             "artistName": "Test Artist",
#             "albumName": "Test Album",
#             "duration": 100,
#             "plainLyrics": "hello world",
#             "syncedLyrics": "[00:01.00]hello world",
#         }

#     monkeypatch.setattr(
#         BaseHTTP,
#         "request",
#         fake_request,
#     )

#     result = get_lyric(
#         title="Hello World",
#         artist="Test Artist",
#         duration=100,
#     )

#     assert result is not None
#     assert result.text == "hello world"
#     assert result.synced_text == "[00:01.00]hello world"
#     assert result.source == "lrclib"
#     assert result.title == "Hello World"
#     assert result.artist == "Test Artist"
#     assert result.duration == 100


# def test_get_lyrics_search_fallback(monkeypatch):

#     def fake_direct(session, title, artist, duration):
#         return None

#     def fake_search(session, params):
#         return [
#             LyricMetadata(
#                 id=123,
#                 title="Hello World",
#                 artist="Test Artist",
#                 album="Album",
#                 duration=100,
#                 plain_lyrics="hello world",
#                 synced_lyrics=None,
#             )
#         ]

#     monkeypatch.setattr(
#         LyricsSolver,
#         "_lrclib_get",
#         fake_direct,
#     )

#     monkeypatch.setattr(
#         LyricsSolver,
#         "_lrclib_search",
#         fake_search,
#     )

#     result = get_lyric(
#         title="Hello World",
#         artist="Test Artist",
#         duration=100,
#     )

#     assert result is not None
#     assert result.text == "hello world"
#     assert result.title == "Hello World"
#     assert result.artist == "Test Artist"


# def test_get_lyrics_relaxed_title_search(monkeypatch):
#     from iantirta.media import lyrics

#     queries: list[str] = []

#     def fake_direct(session, title, artist, duration):
#         return None

#     def fake_search(session, params):
#         track_name = params.get("track_name")

#         if track_name:
#             queries.append(track_name)

#         # Normal searches return a bad candidate.
#         if track_name == "mencintaimu ost 2nd miracle in cell no7":
#             return [
#                 lyrics._LyricsCandidate(
#                     id=1,
#                     title="Completely Different Song",
#                     artist="Mahalini",
#                     album="Album",
#                     duration=400,
#                     plain_lyrics="wrong lyrics",
#                     synced_lyrics=None,
#                 )
#             ]

#         # Relaxed query finds the actual song.
#         if track_name == "mencintaimu ost 2nd miracle in cell":
#             return [
#                 lyrics._LyricsCandidate(
#                     id=2,
#                     title="Mencintaimu - (From: 2nd Miracle in Cell No.7)",
#                     artist="Mahalini",
#                     album="Album",
#                     duration=286,
#                     plain_lyrics="correct lyrics",
#                     synced_lyrics=None,
#                 )
#             ]

#         return []

#     monkeypatch.setattr(
#         lyrics,
#         "_get_direct",
#         fake_direct,
#     )

#     monkeypatch.setattr(
#         lyrics,
#         "_search",
#         fake_search,
#     )

#     result = lyrics.get_lyrics(
#         title=(
#             "MAHALINI - MENCINTAIMU "
#             "(OST. 2ND MIRACLE IN CELL NO.7) "
#             "OFFICIAL LYRIC VIDEO"
#         ),
#         publisher="HITS Records",
#         duration=286,
#     )

#     assert result is not None
#     assert result.text == "correct lyrics"
#     assert result.title == (
#         "Mencintaimu - (From: 2nd Miracle in Cell No.7)"
#     )
#     assert result.artist == "Mahalini"

#     assert "mencintaimu ost 2nd miracle in cell" in queries


# def test_get_lyrics_relaxed_query_is_used_for_scoring(monkeypatch):
#     from iantirta.media import lyrics

#     def fake_direct(session, title, artist, duration):
#         return None

#     def fake_search(session, params):
#         if params.get("track_name") == "mencintaimu":
#             return [
#                 lyrics._LyricsCandidate(
#                     id=123,
#                     title="Mencintaimu OST 2nd Miracle",
#                     artist="Mahalini",
#                     album="Album",
#                     duration=286,
#                     plain_lyrics="lyrics",
#                     synced_lyrics=None,
#                 )
#             ]

#         return []

#     monkeypatch.setattr(
#         lyrics,
#         "_get_direct",
#         fake_direct,
#     )

#     monkeypatch.setattr(
#         lyrics,
#         "_search",
#         fake_search,
#     )

#     result = lyrics.get_lyrics(
#         title="Mahalini - Mencintaimu OST 2nd Miracle",
#         publisher="HITS Records",
#         duration=286,
#     )

#     assert result is not None
#     assert result.title == "Mencintaimu OST 2nd Miracle"
#     assert result.artist == "Mahalini"


# def test_get_lyrics_returns_none_when_no_candidates(monkeypatch):
#     from iantirta.media import lyrics

#     monkeypatch.setattr(
#         lyrics,
#         "_get_direct",
#         lambda *args: None,
#     )

#     monkeypatch.setattr(
#         lyrics,
#         "_search",
#         lambda *args: [],
#     )

#     result = lyrics.get_lyrics(
#         title="Definitely Not A Real Song",
#         artist="Definitely Not A Real Artist",
#         duration=100,
#     )

#     assert result is None


# def test_get_lyrics_requires_title():
#     from iantirta.media import get_lyrics

#     with pytest.raises(ValueError):
#         get_lyrics(title="")


# def test_get_lyrics_requires_non_whitespace_title():
#     from iantirta.media import get_lyrics

#     with pytest.raises(ValueError):
#         get_lyrics(title="   ")


# def test_get_lyrics_deduplicates_candidates(monkeypatch):

#     calls = 0

#     def fake_direct(session, params):
#         return None

#     def fake_search(session, params):
#         nonlocal calls
#         calls += 1

#         return [
#             LyricMetadata(
#                 id=123,
#                 title="Hello World",
#                 artist="Test Artist",
#                 album="Album",
#                 duration=100,
#                 plain_lyrics="lyrics",
#                 synced_lyrics=None,
#             )
#         ]

#     monkeypatch.setattr(
#         LyricsSolver,
#         "_lrclib_get",
#         fake_direct,
#     )

#     monkeypatch.setattr(
#         LyricsSolver,
#         "_lrclib_search",
#         fake_search,
#     )

#     result = get_lyric(
#         title="Hello World",
#         artist="Test Artist",
#         duration=100,
#     )

#     assert result is not None
#     assert result.text == "lyrics"

#     # All searches may return the same candidate, but it should
#     # still produce one logical result.
#     assert calls >= 1
