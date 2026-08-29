#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
iConverlibr.py - XDREAMY SKIN V7.8

Compact Enigma2 / Python 3+ EPG and media cleaning engine.

Design:
    raw_name        = original EPG/media identity
    clean_title     = stable local/TMDB search identity
    search_candidates = conservative TMDB queries
    event_key       = individual EPG occurrence identity

The cleaner is intentionally Unicode-aware and language-neutral.
It does not transliterate Arabic or other scripts.
"""

import atexit
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import weakref
from collections import OrderedDict
from functools import lru_cache

from enigma import eTimer, loadJPG
from Components.Sources.CurrentService import CurrentService
from Components.Sources.Event import Event
from Components.Sources.EventInfo import EventInfo
from Components.Sources.ServiceEvent import ServiceEvent
import NavigationInstance
from Components.config import config

from .iDebugger import traced, dbg, warn, err, register_health_probe


# ============================================================================
# CONFIG / ACTIVATION
# ============================================================================

XDREAMY_SKIN_MARKER = "xdreamy"

_runtime_cfg = {
    "TMDB_LANGUAGE": "en",
    "POSTERX_ENABLED": True,
    "BACKDROPX_ENABLED": True,
    "LOGOX_ENABLED": True,
    "STORAGE_PATH": None,
    "WORKER_THREADS": 3,
    "TMDB_API_KEY": "",
    "RTL_OVERVIEW": True,
    "BACKDROP_SIZE": "w500",
    "LOGO_SIZE": "w300",
}

STORAGE_PATH = None


def is_activated():
    try:
        return XDREAMY_SKIN_MARKER in str(
            config.skin.primary_skin.value or ""
        ).lower()
    except Exception:
        return False


def get_cfg(key):
    return _runtime_cfg.get(key)


def _config_value(plugin_cfg, attr, default):
    try:
        return getattr(plugin_cfg, attr).value
    except Exception:
        return default


def _normalize_storage_path(path):
    if not path:
        return None
    try:
        path = os.path.normpath(os.path.expanduser(str(path).strip()))
    except Exception:
        return None
    return None if path in ("", ".") else path


def _bootstrap_storage_from_saved_config():
    try:
        xd = config.plugins.xDreamy
        mode = getattr(xd, "storage_mode", None)
        custom = getattr(xd, "storage_custom_path", None)
        if mode is not None and custom is not None and mode.value == "custom":
            value = custom.value
            if value:
                _runtime_cfg["STORAGE_PATH"] = _normalize_storage_path(value)
    except Exception:
        pass


_bootstrap_storage_from_saved_config()


def _ensure_dir(path):
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
    except TypeError:
        try:
            os.makedirs(path)
        except OSError:
            pass
    except OSError:
        pass
    return os.path.isdir(path)


def _get_base_path():
    global STORAGE_PATH

    if STORAGE_PATH and os.path.isdir(STORAGE_PATH):
        return STORAGE_PATH

    STORAGE_PATH = None
    custom = _normalize_storage_path(_runtime_cfg.get("STORAGE_PATH"))

    if custom:
        base = (
            custom
            if os.path.basename(custom).lower() == "xdreamy"
            else os.path.join(custom, "XDREAMY")
        )
        if _ensure_dir(base):
            STORAGE_PATH = base
            return base

    for mount in ("/media/hdd", "/media/usb", "/media/mmc"):
        try:
            if os.path.isdir(mount) and os.access(mount, os.W_OK):
                base = os.path.join(mount, "XDREAMY")
                if _ensure_dir(base):
                    STORAGE_PATH = base
                    return base
        except Exception:
            pass

    base = "/tmp/XDREAMY"
    _ensure_dir(base)
    STORAGE_PATH = base
    return base


def _init_folders():
    base = _get_base_path()
    for name in ("poster", "backdrop", "logo", "backup"):
        _ensure_dir(os.path.join(base, name))
    return base


def get_base_path():
    return _get_base_path()


def get_poster_folder():
    return os.path.join(_get_base_path(), "poster")


def get_backdrop_folder():
    return os.path.join(_get_base_path(), "backdrop")


def get_logo_folder():
    return os.path.join(_get_base_path(), "logo")


def get_backup_folder():
    return os.path.join(_get_base_path(), "backup")


def get_cache_path(filename):
    return _get_base_path() if not filename else os.path.join(
        _get_base_path(), str(filename)
    )


def get_metadata_db_path():
    return os.path.join(_get_base_path(), "iMetaData.db")


def get_server_channels_json_path():
    return os.path.join(_get_base_path(), "ServerChannels.json")


@traced("iConverlibr")
def apply_plugin_config(plugin_cfg):
    global STORAGE_PATH

    defaults = (
        ("TMDB_LANGUAGE", "tmdb_language", "en"),
        ("POSTERX_ENABLED", "posterx_enabled", True),
        ("BACKDROPX_ENABLED", "backdropx_enabled", True),
        ("LOGOX_ENABLED", "logox_enabled", True),
        ("TMDB_API_KEY", "tmdb_api_key", ""),
        ("RTL_OVERVIEW", "rtl_overview", True),
        ("BACKDROP_SIZE", "backdrop_size", "w500"),
        ("LOGO_SIZE", "logo_size", "w300"),
    )

    for key, attr, default in defaults:
        _runtime_cfg[key] = _config_value(plugin_cfg, attr, default)

    try:
        _runtime_cfg["WORKER_THREADS"] = max(
            1, int(_config_value(plugin_cfg, "worker_threads", 3))
        )
    except Exception:
        _runtime_cfg["WORKER_THREADS"] = 3

    mode = _config_value(plugin_cfg, "storage_mode", "auto")

    if mode == "custom":
        _runtime_cfg["STORAGE_PATH"] = _normalize_storage_path(
            _config_value(
                plugin_cfg,
                "storage_custom_path",
                "/media/hdd/XDREAMY",
            )
        )
    else:
        _runtime_cfg["STORAGE_PATH"] = None

    STORAGE_PATH = None
    _init_folders()

    try:
        _epg_store.reopen_if_needed()
        _emc_store.reopen_if_needed()
    except Exception as exc:
        warn("iConverlibr", "config-db-reopen-EX", str(exc))

    clear_runtime_caches()
    dbg(
        "iConverlibr",
        "config-applied",
        "workers=%s" % _runtime_cfg["WORKER_THREADS"],
    )


_init_folders()


# ============================================================================
# TEXT / UNICODE
# ============================================================================

def to_text(value, encoding="utf-8"):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode(encoding, "ignore")
        except Exception:
            return ""
    try:
        return str(value)
    except Exception:
        return ""


# Do not transliterate Arabic.
# Only normalize compatibility/variant forms that are safe for identity.
_ARABIC_TRANSLATION = str.maketrans({
    "\u0622": "\u0627",  # آ
    "\u0623": "\u0627",  # أ
    "\u0625": "\u0627",  # إ
    "\u0671": "\u0627",  # ٱ
    "\u06CC": "\u064A",  # Persian ی
    "\u06D2": "\u064A",
    "\u06A9": "\u0643",  # Persian ک
    "\u0640": "",        # tatweel
})

_ARABIC_MARKS_RE = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)

_ZERO_WIDTH_RE = re.compile(
    r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F"
    r"\u00AD\u034F\u061C\u180E\u200B-\u200F\u202A-\u202E"
    r"\u2060-\u2064\u2066-\u206F\uFEFF]"
)

_RTL_RE = re.compile(
    r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F"
    r"\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def normalize_unicode_text(text, arabic=True):
    text = to_text(text)
    if not text:
        return ""

    try:
        text = unicodedata.normalize("NFKC", text)
    except Exception:
        pass

    text = _ZERO_WIDTH_RE.sub("", text)

    if arabic:
        text = text.translate(_ARABIC_TRANSLATION)
        text = _ARABIC_MARKS_RE.sub("", text)

    text = "".join(
        " " if unicodedata.category(ch) == "Zs" else ch
        for ch in text
    )

    return text.strip()


def _normalize_title_text(text):
    text = normalize_unicode_text(text)
    return re.sub(r"\s+", " ", text).strip() if text else ""


def _title_identity(text):
    text = _normalize_title_text(text)
    if not text:
        return ""
    return text.casefold().strip(" \t\r\n:;,.–—")


def is_arabic(text):
    text = to_text(text)[:300]
    if not text:
        return False
    letters = sum(ch.isalpha() for ch in text)
    if not letters:
        return False
    rtl = len(_RTL_RE.findall(text))
    return rtl / float(max(1, len(text))) > 0.20


def clean_name(name):
    return _normalize_title_text(
        to_text(name).replace("\x86", "").replace("\x87", "")
    )


# ============================================================================
# CHANNEL / EPG FILTERS
# ============================================================================

SKIP_CHANNEL_KEYWORDS = (
    "sport", "sports", "espn", "eurosport", "bein sport", "dazn",
    "sky sport", "fox sport", "nba tv", "nfl network", "golf channel",
    "motorsport", "racing", "tennis channel", "news", "cnn", "bbc news",
    "fox news", "sky news", "al jazeera", "bloomberg", "weather", "meteo",
    "tg1", "tg2", "tg3", "tg4", "tg5", "rainews", "tvp info", "tvp sport",
    "polsat sport", "canal+ sport", "sportklub",
)

_NO_INFO_WORDS = (
    "no information", "no info", "no event info", "press epg",
    "brak informacji", "brak danych", "informacja niedostępna",
    "wciśnij przycisk", "press button", "info -", "epg -",
    "brak tytułu", "no title", "niedostępne", "unavailable",
    "not available", "epg not available", "program nieznany",
    "unknown program", "zakończenie programu", "koniec programu",
    "end of program", "programmende", "fine programma",
    "fin de programme", "نهاية البرنامج", "clip time",
    "broadcasts will resume soon", "end of broadcast", "shopping hours",
    "przerwa w programie", "noticias 24 h", "telediario matinal",
    "greek music", "music videos", "news. local time",
    "fashion court", "living well", "programmes de la nuit",
)

_NO_INFO_RE = re.compile(
    "|".join(map(re.escape, _NO_INFO_WORDS)),
    re.I | re.U,
)

_SKIP_EVENT_KEYWORDS = (
    "formula 1", "formula one", "motogp", "motorsport", "nascar",
    "indycar", "grand prix", "eprix", "e-prix",
    "uefa champions league", "champions league live",
    "premier league live", "football live", "soccer live",
    "tennis live", "basketball live", "boxing live",
    "ufc live", "wwe live", "atp live", "wta live",
)


def _is_no_info(text):
    text = _normalize_title_text(text)
    return not text or bool(_NO_INFO_RE.search(text))


def _is_skip_event(text):
    text = _normalize_title_text(text).casefold()
    return bool(text) and any(k in text for k in _SKIP_EVENT_KEYWORDS)


def is_sport_or_news_channel(channel_name):
    name = clean_name(channel_name).casefold()
    return bool(name) and any(k in name for k in SKIP_CHANNEL_KEYWORDS)


# ============================================================================
# UNIVERSAL TITLE CLEANING
# ============================================================================

# The important rule is:
#   episode number = identity noise
#   season number  = useful identity
#
# Therefore:
#   House of the Dragon S02E08 -> House of the Dragon 2
#
# Numbers are normalized first, so Arabic/Persian digits work automatically.

_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


def _normalize_digits(text):
    return to_text(text).translate(_DIGIT_TRANSLATION)


def _roman_number(value):
    value = to_text(value).upper().strip()
    if not value or not re.fullmatch(
        r"I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XL|L",
        value,
    ):
        return None

    values = {"I": 1, "V": 5, "X": 10, "L": 50}
    total = 0
    previous = 0

    for char in reversed(value):
        current = values[char]
        total += -current if current < previous else current
        previous = current

    return total


def _number_value(value):
    value = to_text(value).strip()
    if value.isdigit():
        try:
            return int(value)
        except Exception:
            return None
    return _roman_number(value)


# Common episode syntax, deliberately small and language-neutral.
# We care about the structure rather than translating every language.
_EPISODE_RE = re.compile(
    r"""
    (?:
        \bS(?:EASON)?\s*(?P<s1>\d{1,3})\s*
        (?:E(?:PISODE)?|X)\s*(?P<e1>\d{1,4})\b
      |
        \b(?P<s2>\d{1,3})\s*[xX]\s*(?P<e2>\d{1,4})\b
      |
        \b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|SEZON|
            SEASONEN|MUSIM|MUSIMI|موسم)\s*
        (?P<s3>\d{1,3})\s*
        (?:EPISODE|EP|ODCINEK|ODC|FOLGE|TEIL|EPISODIO|EPISOD|
            CHAPITRE|CAPITULO|CAPÍTULO|BÖLÜM|BOLUM|PUNTATA|
            EPISODE|حلقة|جزء)\s*
        (?P<e3>\d{1,4})
        \b
      |
        \b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|SEZON|
            MUSIM|موسم)\s*(?P<s4>\d{1,3})\b
    )
    """,
    re.I | re.U | re.X,
)

# Roman-number season/episode forms.
_ROMAN_EPISODE_RE = re.compile(
    r"""
    \bS(?:EASON)?\s*
    (?P<s>I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XL|L)
    \s*
    E(?:PISODE)?\s*
    (?P<e>I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XL|L)
    \b
    """,
    re.I | re.U | re.X,
)

_ROMAN_SEASON_WORD_RE = re.compile(
    r"""
    \b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|SEZON|MUSIM|موسم)
    \s*
    (?P<s>I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XL|L)
    \b
    """,
    re.I | re.U | re.X,
)

# Common "part/episode" marker. We remove it but don't treat it as season.
_PART_RE = re.compile(
    r"""
    (?:
        \b(?:EPISODE|EP|ODCINEK|ODC|FOLGE|TEIL|EPISODIO|EPISOD|
        CHAPITRE|CAPITULO|CAPÍTULO|BÖLÜM|BOLUM|PUNTATA|PART|PT|
        حلقة|جزء)\s*[.:_-]?\s*\d{1,4}\b
    )
    """,
    re.I | re.U | re.X,
)

_PAREN_EPISODE_RE = re.compile(
    r"""
    \s*\(
        [^)]*
        (?:
            odc|ep|season|serija|p\.|#|série|stagione|temporada|sezon|
            حلقة|جزء|موسم
        )
        \s*\.?\s*\d+
        [^)]*
    \)
    """,
    re.I | re.U | re.X,
)

_TRAILING_FILM_RE = re.compile(
    r"""
    \s*,?\s*
    (?:
        film|movie|reality\s*show|talk-show|
        dokumentarni|dokumentar|documentary|reality
    )
    \s*$
    """,
    re.I | re.U | re.X,
)

_JUNK_WORDS_RE = re.compile(
    r"""
    (?<!\w)
    (?:
        hd|1080p|720p|4k|uhd|webrip|bluray|hdr|x265|x264|
        lektor|napisy|dubbing|vf|vostfr|sub
    )
    (?!\w)
    """,
    re.I | re.U | re.X,
)

_NOISE_PHRASE_RE = re.compile(r"حلقة\s+مجمعة", re.U)

_YEAR_RE = re.compile(r"(?<!\d)(?:19\d{2}|20[0-4]\d)(?!\d)")

_AMBIGUOUS_TRAILING_RE = re.compile(
    r"""
    \s+
    (?:
        \d{1,2}\s*[-–]\s*\d{1,2}
        |\d{1,3}
        |I|II|III|IV|V|VI|VII|VIII|IX|X|
         XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX
    )
    $
    """,
    re.I | re.U | re.X,
)


def _separator_normalize(text):
    text = text.replace("_", " ")
    text = re.sub(r"[|/\\]+", " ", text)
    text = re.sub(r"\s*[–—]\s*", " - ", text)
    return text


def _extract_season(text):
    """
    Return:
        season_number or None,
        text_without_episode/season markers
    """
    text = _normalize_digits(text)
    season = None

    match = _ROMAN_EPISODE_RE.search(text)
    if match:
        season = _number_value(match.group("s"))
        text = text[:match.start()] + " " + text[match.end():]
        return season, text

    match = _EPISODE_RE.search(text)
    if match:
        for key in ("s1", "s2", "s3", "s4"):
            value = match.groupdict().get(key)
            if value:
                season = _number_value(value)
                break
        text = text[:match.start()] + " " + text[match.end():]
        return season, text

    match = _ROMAN_SEASON_WORD_RE.search(text)
    if match:
        season = _number_value(match.group("s"))
        text = text[:match.start()] + " " + text[match.end():]
        return season, text

    return season, text


def _clean_candidate(candidate):
    candidate = _normalize_title_text(candidate)
    candidate = re.sub(r"[\s:;,\-–—.]+$", "", candidate)
    return _title_identity(candidate)


def simple_clean_title(raw):
    """
    Return conservative TMDB/local candidates.

    For series:
        "House of the Dragon S02E08"
            -> "house of the dragon 2"
            -> "house of the dragon"

    The first candidate is the season-aware identity when a season
    can be detected. The base title remains as a fallback.

    No transliteration is performed.
    """
    original = _normalize_title_text(raw)
    if not original:
        return []

    original = _normalize_digits(original)
    text = _separator_normalize(original)

    try:
        season, text = _extract_season(text)

        text = _PAREN_EPISODE_RE.sub(" ", text)
        text = _PART_RE.sub(" ", text)
        text = _JUNK_WORDS_RE.sub(" ", text)
        text = _NOISE_PHRASE_RE.sub(" ", text)
        text = _TRAILING_FILM_RE.sub("", text)

        # Remove obvious release/date noise, but don't remove ordinary
        # punctuation from the title itself.
        text = re.sub(r"\s*\[[^\]]*\]\s*", " ", text)
        text = re.sub(r"\s*\{[^}]*\}\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" :;,-–—.")

        if not text:
            return []

        base = _clean_candidate(text)
        if not base:
            return []

        candidates = []

        if season is not None and 0 < season < 100:
            # Season-aware local identity. This gives separate assets
            # for separate seasons.
            candidates.append("%s %d" % (base, season))

            # TMDB fallback without season.
            candidates.append(base)
        else:
            candidates.append(base)

        # Strong separator: "Title - Subtitle".
        # Keep only the prefix as a conservative fallback.
        match = re.search(r"\s+-\s+|\s+:\s+", original)
        if match:
            prefix = _clean_candidate(
                original[:match.start()].strip(" :;,-–—.")
            )
            if len(prefix) > 3 and prefix not in candidates:
                candidates.append(prefix)

        # If a year is embedded, provide a yearless fallback.
        year = _YEAR_RE.search(base)
        if year:
            yearless = _clean_candidate(
                base[:year.start()].strip(" :;,-–—.")
            )
            if yearless and yearless not in candidates:
                candidates.append(yearless)

        # Very conservative raw fallback.
        raw_clean = _clean_candidate(original)
        if raw_clean and raw_clean not in candidates:
            candidates.append(raw_clean)

        result = []
        for candidate in candidates:
            if candidate and len(candidate) > 1 and candidate not in result:
                result.append(candidate)
            if len(result) >= 4:
                break

        return result

    except Exception as exc:
        # Title parsing must never crash Enigma2.
        warn(
            "iConverlibr",
            "simple-clean-EX",
            "%s: %s" % (type(exc).__name__, exc),
        )
        return []


# ============================================================================
# ANALYZE CACHE
# ============================================================================

_ANALYZE_CACHE_MAX = 1200
_analyze_cache = OrderedDict()
_analyze_cache_lock = threading.RLock()


@traced("iConverlibr")
def analyze_epg_title(raw):
    raw = to_text(raw)
    if not raw:
        return True, "", []

    with _analyze_cache_lock:
        cached = _analyze_cache.get(raw)
        if cached is not None:
            _analyze_cache.move_to_end(raw)
            return cached

    try:
        if _is_no_info(raw) or _is_skip_event(raw):
            result = (True, "", [])
        else:
            candidates = simple_clean_title(raw)
            clean = candidates[0] if candidates else ""

            if not clean:
                result = (True, "", [])
            else:
                raw_clean = _clean_candidate(raw)
                if raw_clean and raw_clean not in candidates:
                    candidates.append(raw_clean)
                result = (False, clean, candidates[:4])

    except Exception as exc:
        warn(
            "iConverlibr",
            "title-analysis-EX",
            "%s: %s" % (type(exc).__name__, exc),
        )
        result = (True, "", [])

    with _analyze_cache_lock:
        _analyze_cache[raw] = result
        _analyze_cache.move_to_end(raw)
        while len(_analyze_cache) > _ANALYZE_CACHE_MAX:
            _analyze_cache.popitem(last=False)

    return result


def convtext(text=u""):
    if not text:
        return ""

    text = to_text(text)

    with _analyze_cache_lock:
        cached = _analyze_cache.get(text)
        if cached is not None:
            _analyze_cache.move_to_end(text)
            return cached[1]

    return analyze_epg_title(text)[1]


# ============================================================================
# EPG METADATA
# ============================================================================

def extract_epg_hints(description):
    match = _YEAR_RE.search(_normalize_title_text(description))
    return {"year": match.group(0)} if match else {}


def _format_genres(genres_string):
    if not genres_string:
        return ""
    parts = [
        x.strip()
        for x in to_text(genres_string).split(",")
        if x.strip()
    ]
    return " • ".join(parts)


_DEFAULT_OVERVIEW_CHARS_PER_LINE = 70


@lru_cache(maxsize=500)
def cached_format_overview(
    text,
    chars_per_line=_DEFAULT_OVERVIEW_CHARS_PER_LINE,
):
    if not text:
        return text

    text = to_text(text)
    sample = text[:120]
    rtl_count = len(_RTL_RE.findall(sample))

    if rtl_count <= len(sample) * 0.25:
        return text

    try:
        chars_per_line = max(1, int(chars_per_line))
    except Exception:
        chars_per_line = _DEFAULT_OVERVIEW_CHARS_PER_LINE

    lines = []
    line = []
    length = 0

    for word in text.split():
        n = len(word)
        proposed = length + n + (1 if line else 0)

        if line and proposed > chars_per_line:
            lines.append(" ".join(line))
            line = [word]
            length = n
        else:
            line.append(word)
            length = proposed

    if line:
        lines.append(" ".join(line))

    return "\n".join(lines)


def format_overview(text, chars_per_line=None):
    if not text or not get_cfg("RTL_OVERVIEW"):
        return text

    if chars_per_line is None:
        chars_per_line = _DEFAULT_OVERVIEW_CHARS_PER_LINE

    try:
        chars_per_line = max(1, int(chars_per_line))
    except Exception:
        chars_per_line = _DEFAULT_OVERVIEW_CHARS_PER_LINE

    return cached_format_overview(to_text(text), chars_per_line)


def has_useful_metadata(data):
    if not isinstance(data, dict):
        return False

    try:
        rating = float(data.get("vote_average", 0) or 0)
    except Exception:
        rating = 0

    overview = to_text(data.get("overview", "") or "")

    return bool(
        rating > 0
        or data.get("parental_rating")
        or data.get("genres")
        or data.get("year")
        or data.get("director")
        or data.get("cast")
        or len(overview) > 50
        or data.get("title")
    )


_EMPTY_METADATA = {
    "metadata_resolved": False,
    "rating": 0,
    "parental": "",
    "genres": "",
    "year": "",
    "overview": "",
    "plot": "",
    "title": "",
    "country": "",
    "director": "",
    "cast": "",
    "rated": "",
    "imdb": "",
}


def build_meta_dict(data):
    data = data if isinstance(data, dict) else {}

    try:
        rating = float(data.get("vote_average", 0) or 0)
    except Exception:
        rating = 0

    overview = to_text(data.get("overview", "") or "")
    formatted = format_overview(overview)
    parental = to_text(data.get("parental_rating", "") or "")

    return {
        "rating": rating,
        "parental": parental,
        "genres": _format_genres(data.get("genres", "")),
        "year": data.get("year", ""),
        "overview": formatted,
        "plot": formatted,
        "title": to_text(data.get("title", "") or ""),
        "country": to_text(data.get("country", "") or ""),
        "director": to_text(data.get("director", "") or ""),
        "cast": to_text(data.get("cast", "") or ""),
        "rated": parental,
        "imdb": str(rating) if rating > 0 else "",
        "metadata_resolved": True,
    }


# ============================================================================
# ASSET CACHE / RESOLUTION
# ============================================================================

_ASSET_EXISTS_CACHE_MAX = 1500
_ASSET_EXISTS_CACHE_TTL = 1.5
_asset_exists_cache = OrderedDict()
_asset_exists_lock = threading.RLock()


def _clear_asset_cache():
    with _asset_exists_lock:
        _asset_exists_cache.clear()


def file_exists_indexed(folder, filename):
    if not folder or not filename:
        return False

    key = (str(folder), str(filename))
    now = time.monotonic()

    with _asset_exists_lock:
        entry = _asset_exists_cache.get(key)
        if entry is not None:
            timestamp, exists = entry
            if now - timestamp <= _ASSET_EXISTS_CACHE_TTL:
                _asset_exists_cache.move_to_end(key)
                return exists
            del _asset_exists_cache[key]

    try:
        exists = os.path.isfile(os.path.join(folder, filename))
    except Exception:
        exists = False

    with _asset_exists_lock:
        _asset_exists_cache[key] = (now, exists)
        _asset_exists_cache.move_to_end(key)
        while len(_asset_exists_cache) > _ASSET_EXISTS_CACHE_MAX:
            _asset_exists_cache.popitem(last=False)

    return exists


def mark_file_indexed(folder, filename):
    if not folder or not filename:
        return

    try:
        exists = os.path.isfile(os.path.join(folder, filename))
    except Exception:
        exists = False

    key = (str(folder), str(filename))

    with _asset_exists_lock:
        _asset_exists_cache[key] = (time.monotonic(), exists)
        _asset_exists_cache.move_to_end(key)


def unmark_file_indexed(folder, filename):
    if folder and filename:
        with _asset_exists_lock:
            _asset_exists_cache.pop((str(folder), str(filename)), None)


def refresh_all_indexes():
    _clear_asset_cache()


def resolve_asset_paths(
    clean_title,
    want_poster=True,
    want_backdrop=True,
    want_logo=True,
):
    result = {
        "local_path": None,
        "backdrop_path": None,
        "logo_path": None,
    }

    title = to_text(clean_title).strip()
    if not title:
        return result

    checks = (
        (want_poster, get_poster_folder(), ".jpg", "local_path"),
        (want_backdrop, get_backdrop_folder(), ".jpg", "backdrop_path"),
        (want_logo, get_logo_folder(), ".png", "logo_path"),
    )

    for enabled, folder, ext, key in checks:
        if enabled:
            filename = title + ext
            if file_exists_indexed(folder, filename):
                result[key] = os.path.join(folder, filename)

    return result


# ============================================================================
# SQLITE STATE STORE
# ============================================================================

class StateStore(object):
    CACHE_MAX = 1200

    def __init__(self, emc_mode):
        self.emc_mode = bool(emc_mode)
        self.table = "emc" if self.emc_mode else "epg"
        self._conn = None
        self._db_path = None
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._closed = False
        self._connect()

        try:
            atexit.register(self.close)
        except Exception:
            pass

    def _connect(self):
        path = get_metadata_db_path()

        if self._conn is not None and self._db_path == path:
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

        self._db_path = path

        conn = sqlite3.connect(
            path,
            timeout=10,
            check_same_thread=False,
            cached_statements=128,
        )

        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-2048",
            "PRAGMA busy_timeout=10000",
        ):
            try:
                conn.execute(pragma)
            except Exception:
                pass

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS %s (
                title TEXT PRIMARY KEY,
                status TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                last_scan INTEGER NOT NULL DEFAULT 0
            )
            """ % self.table
        )
        conn.commit()

        self._conn = conn
        self._closed = False
        return conn

    def reopen_if_needed(self):
        with self._lock:
            self._connect()

    def close(self):
        with self._lock:
            self._closed = True
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None
            self._db_path = None
            self._cache.clear()

    def _cache_get(self, title):
        value = self._cache.get(title)
        if value is not None:
            self._cache.move_to_end(title)
        return value

    def _cache_put(self, title, value):
        self._cache[title] = value
        self._cache.move_to_end(title)

        while len(self._cache) > self.CACHE_MAX:
            self._cache.popitem(last=False)

    @staticmethod
    def _decode_row(row):
        if not row:
            return None

        status, data_json, last_scan = row

        try:
            data = json.loads(data_json) if data_json else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        return {
            "status": status or "",
            "data": data,
            "last_scan": int(last_scan or 0),
        }

    def get(self, title):
        title = to_text(title).strip()
        if not title:
            return None

        with self._lock:
            cached = self._cache_get(title)

            if cached is False:
                return None
            if cached is not None:
                return cached

            for attempt in range(2):
                try:
                    row = self._connect().execute(
                        "SELECT status,data,last_scan FROM %s WHERE title=?"
                        % self.table,
                        (title,),
                    ).fetchone()

                    result = self._decode_row(row)
                    self._cache_put(
                        title,
                        result if result is not None else False,
                    )
                    return result

                except (sqlite3.Error, IOError, OSError) as exc:
                    if attempt == 0:
                        try:
                            if self._conn:
                                self._conn.close()
                        except Exception:
                            pass
                        self._conn = None
                    else:
                        warn("iConverlibr", "sqlite-get-EX", str(exc))

                except Exception as exc:
                    warn("iConverlibr", "sqlite-get-EX", str(exc))
                    break

        return None

    def get_many(self, titles):
        if not titles:
            return {}

        unique = []
        seen = set()

        for title in titles:
            title = to_text(title).strip()
            if title and title not in seen:
                seen.add(title)
                unique.append(title)

        if not unique:
            return {}

        result = {}
        missing = []

        with self._lock:
            for title in unique:
                cached = self._cache_get(title)

                if cached is False:
                    continue
                if cached is None:
                    missing.append(title)
                else:
                    result[title] = cached

            if not missing:
                return result

            try:
                conn = self._connect()

                for offset in range(0, len(missing), 80):
                    chunk = missing[offset:offset + 80]
                    placeholders = ",".join("?" for _ in chunk)

                    rows = conn.execute(
                        """
                        SELECT title,status,data,last_scan
                        FROM %s WHERE title IN (%s)
                        """ % (self.table, placeholders),
                        tuple(chunk),
                    ).fetchall()

                    for title, status, data_json, last_scan in rows:
                        value = self._decode_row(
                            (status, data_json, last_scan)
                        )
                        if value is not None:
                            result[title] = value
                            self._cache_put(title, value)

                for title in missing:
                    if title not in result:
                        self._cache_put(title, False)

            except Exception as exc:
                warn("iConverlibr", "sqlite-get-many-EX", str(exc))

        return result

    def get_data(self, title):
        record = self.get(title)
        return record["data"] if record else None

    def is_ok(self, title):
        record = self.get(title)
        return bool(record and record.get("status") == "ok")

    def should_search(self, title, still_needed=None):
        record = self.get(title)

        if record is None:
            return True

        status = record.get("status")

        if status == "ok":
            return bool(still_needed)

        if status == "failed":
            return (
                time.time() - (record.get("last_scan", 0) or 0)
                > 7 * 86400
            )

        return True

    def set_record(self, title, status, data=None):
        title = to_text(title).strip()
        if not title:
            return

        payload = data if isinstance(data, dict) else {}
        now = int(time.time())

        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception:
            encoded = "{}"
            payload = {}

        with self._lock:
            for attempt in range(2):
                try:
                    conn = self._connect()

                    cursor = conn.execute(
                        """
                        UPDATE %s
                        SET status=?,data=?,last_scan=?
                        WHERE title=?
                        """ % self.table,
                        (status, encoded, now, title),
                    )

                    if cursor.rowcount == 0:
                        try:
                            conn.execute(
                                """
                                INSERT INTO %s(title,status,data,last_scan)
                                VALUES(?,?,?,?)
                                """ % self.table,
                                (title, status, encoded, now),
                            )
                        except sqlite3.IntegrityError:
                            conn.execute(
                                """
                                UPDATE %s
                                SET status=?,data=?,last_scan=?
                                WHERE title=?
                                """ % self.table,
                                (status, encoded, now, title),
                            )

                    conn.commit()

                    self._cache_put(
                        title,
                        {
                            "status": status,
                            "data": payload,
                            "last_scan": now,
                        },
                    )
                    return

                except (sqlite3.Error, IOError, OSError) as exc:
                    try:
                        if self._conn:
                            self._conn.rollback()
                    except Exception:
                        pass

                    if attempt == 0:
                        try:
                            if self._conn:
                                self._conn.close()
                        except Exception:
                            pass
                        self._conn = None
                    else:
                        err("iConverlibr", "sqlite-set-EX", str(exc))

                except Exception as exc:
                    try:
                        if self._conn:
                            self._conn.rollback()
                    except Exception:
                        pass
                    err("iConverlibr", "sqlite-set-EX", str(exc))
                    return

    def mark_not_found(self, title):
        record = self.get(title)
        self.set_record(
            title,
            "failed",
            record["data"] if record else {},
        )


_epg_store = StateStore(False)
_emc_store = StateStore(True)


def get_state_store(emc_mode):
    return _emc_store if emc_mode else _epg_store


# ============================================================================
# EVENT IDENTITY / CALLBACKS
# ============================================================================

_metadata_callbacks = {}
_metadata_callback_lock = threading.RLock()
_ready_queue = []
_ready_queue_lock = threading.RLock()
_gui_dispatcher_timer = eTimer()


def make_event_key(begin_time, raw_name, ep_marker=""):
    raw_name = clean_name(raw_name)
    ep_marker = to_text(ep_marker).strip()
    begin_time = begin_time or 0

    return (
        "%s-%s-%s" % (begin_time, raw_name, ep_marker)
        if ep_marker
        else "%s-%s" % (begin_time, raw_name)
    )


def _make_weak_renderer_ref(renderer_ref):
    try:
        return weakref.ref(renderer_ref)
    except TypeError:
        return None


def register_metadata_callback(
    clean_title,
    renderer_ref,
    method_name="changed",
    event_key=None,
):
    if not clean_title or renderer_ref is None:
        return

    key = event_key or clean_title
    weak_renderer = _make_weak_renderer_ref(renderer_ref)

    if weak_renderer is None:
        return

    with _metadata_callback_lock:
        bucket = _metadata_callbacks.setdefault(key, [])

        for existing_ref, existing_method in bucket:
            try:
                if (
                    existing_method == method_name
                    and existing_ref() is renderer_ref
                ):
                    return
            except Exception:
                pass

        bucket.append((weak_renderer, method_name))


def unregister_metadata_callback(
    clean_title,
    renderer_obj,
    event_key=None,
):
    if not clean_title or renderer_obj is None:
        return

    key = event_key or clean_title

    with _metadata_callback_lock:
        bucket = _metadata_callbacks.get(key)

        if not bucket:
            return

        alive = []

        for ref, method_name in bucket:
            renderer = ref()

            if renderer is not None and renderer is not renderer_obj:
                alive.append((ref, method_name))

        if alive:
            _metadata_callbacks[key] = alive
        else:
            _metadata_callbacks.pop(key, None)


def notify_metadata_ready(clean_title, event_key=None):
    if not clean_title:
        return

    with _ready_queue_lock:
        _ready_queue.append(("meta", clean_title, event_key))

    _schedule_drain()


def queue_gui_callback(callback, *args):
    if callback is None:
        return

    with _ready_queue_lock:
        _ready_queue.append(("call", callback, args))

    _schedule_drain()


def _schedule_drain():
    try:
        _gui_dispatcher_timer.start(0, True)
    except Exception:
        pass


def _safe_renderer_changed(renderer, method_name):
    try:
        method = getattr(renderer, method_name, None)

        if method is None:
            return

        changed_default = getattr(
            renderer,
            "CHANGED_DEFAULT",
            None,
        )

        if changed_default is None:
            method()
        else:
            method((changed_default,))

    except Exception as exc:
        err("Dispatcher", "meta-callback-EX", str(exc))


@traced("iConverlibr")
def _drain_ready_queue():
    with _ready_queue_lock:
        if not _ready_queue:
            return

        items = list(_ready_queue)
        del _ready_queue[:]

    meta_events = set()
    direct_calls = []

    for item in items:
        if not item:
            continue

        if item[0] == "meta" and len(item) >= 3:
            meta_events.add((item[1], item[2]))

        elif item[0] == "call" and len(item) >= 3:
            direct_calls.append((item[1], item[2]))

    for clean_title, event_key in meta_events:
        keys = [event_key] if event_key else []

        if clean_title not in keys:
            keys.append(clean_title)

        callbacks = []

        with _metadata_callback_lock:
            for key in keys:
                callbacks.extend(
                    _metadata_callbacks.get(key, [])
                )

        for weak_renderer, method_name in callbacks:
            renderer = weak_renderer()

            if renderer is not None:
                _safe_renderer_changed(
                    renderer,
                    method_name,
                )

    for callback, args in direct_calls:
        try:
            callback(*args)
        except Exception as exc:
            err("Dispatcher", "gui-callback-EX", str(exc))

    with _metadata_callback_lock:
        dead = []

        for key, bucket in _metadata_callbacks.items():
            alive = [
                entry
                for entry in bucket
                if entry[0]() is not None
            ]

            if alive:
                _metadata_callbacks[key] = alive
            else:
                dead.append(key)

        for key in dead:
            _metadata_callbacks.pop(key, None)

    with _ready_queue_lock:
        more = bool(_ready_queue)

    if more:
        _schedule_drain()


try:
    _gui_dispatcher_timer.callback.append(_drain_ready_queue)
except Exception as exc:
    err("Dispatcher", "timer-init-EX", str(exc))


# ============================================================================
# MEDIA / SERVICE
# ============================================================================

_VIDEO_EXTS = (
    ".mkv", ".avi", ".mp4", ".ts", ".mov", ".iso",
    ".m2ts", ".m4v", ".mpeg", ".mpg", ".wmv",
)


def is_video_file(path):
    if not path:
        return False

    try:
        return str(path).lower().endswith(_VIDEO_EXTS)
    except Exception:
        return False


def _navigation_service_ref():
    try:
        nav = NavigationInstance.instance
        return (
            nav.getCurrentlyPlayingServiceReference()
            if nav
            else None
        )
    except Exception:
        return None


def get_service_ref(source):
    if source is None:
        return None

    try:
        if hasattr(source, "toString") and not hasattr(
            source,
            "getCurrentService",
        ):
            return source
    except Exception:
        pass

    try:
        getter = getattr(
            source,
            "getCurrentService",
            None,
        )

        if callable(getter):
            service = getter()

            if service is not None:
                if hasattr(service, "toString"):
                    return service

                ref = service.getCurrentServiceRef()

                if ref is not None:
                    return ref
    except Exception:
        pass

    if isinstance(source, CurrentService):
        try:
            return source.getCurrentServiceRef()
        except Exception:
            pass

    if isinstance(source, (EventInfo, Event)):
        return _navigation_service_ref()

    if isinstance(source, ServiceEvent):
        try:
            return source.getCurrentService()
        except Exception:
            pass

    if source.__class__.__name__ in (
        "EMCServiceEvent",
        "Service",
    ):
        try:
            service = getattr(source, "service", None)
            if service is not None:
                return service
        except Exception:
            pass

    return _navigation_service_ref()


def get_movie_path(source):
    if source is None:
        return None

    for obj in (
        source,
        getattr(source, "service", None),
    ):
        if obj is None:
            continue

        try:
            getter = getattr(obj, "getPath", None)

            if callable(getter):
                path = getter()

                if path:
                    return path
        except Exception:
            pass

    try:
        getter = getattr(
            source,
            "getCurrentService",
            None,
        )

        if callable(getter):
            service = getter()

            getter = (
                getattr(service, "getPath", None)
                if service
                else None
            )

            if callable(getter):
                path = getter()

                if path:
                    return path
    except Exception:
        pass

    if isinstance(source, ServiceEvent):
        try:
            service = source.getCurrentService()
            getter = (
                getattr(service, "getPath", None)
                if service
                else None
            )

            if callable(getter):
                return getter()
        except Exception:
            pass

    if isinstance(source, CurrentService):
        try:
            ref = source.getCurrentServiceRef()
            getter = (
                getattr(ref, "getPath", None)
                if ref
                else None
            )

            if callable(getter):
                return getter()
        except Exception:
            pass

    return None


def detect_media(source):
    movie_path = get_movie_path(source)

    if not movie_path or not is_video_file(movie_path):
        return {
            "is_media": False,
            "movie_path": None,
            "clean_title": "",
            "year": "",
            "is_episode": False,
            "ep_marker": "",
        }

    clean, year, is_ep, ep_marker = clean_filename(movie_path)

    return {
        "is_media": True,
        "movie_path": movie_path,
        "clean_title": clean,
        "year": year,
        "is_episode": is_ep,
        "ep_marker": ep_marker,
    }


# ============================================================================
# EMC / FILENAME CLEANING
# ============================================================================

_S_EMARK_RE = re.compile(
    r"\bS\s*(\d{1,2})[\s._-]*E\s*(\d{1,3})\b",
    re.I,
)

_X_EMARK_RE = re.compile(
    r"\b(\d{1,2})x(\d{1,3})\b",
    re.I,
)

_SEASON_MARKER_RE = re.compile(
    r"\bseason[\s._-]*\d+\b",
    re.I,
)

_EPISODE_MARKER_RE = re.compile(
    r"\bepisode[\s._-]*\d+\b",
    re.I,
)

_FILENAME_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})(?!\d)"
)

_DATE_PREFIX_RE = re.compile(
    r"^\d{8}\s+\d{4}\s*[-–]\s*"
)

_BRACKET_YEAR_RE = re.compile(
    r"[\[(]\s*((?:19|20)\d{2})\s*[\])]"
)

_BRACKET_RE = re.compile(r"\[[^\]]+\]")
_PAREN_RE = re.compile(r"\([^)]*\)")
_BRACE_RE = re.compile(r"\{[^}]+\}")

_GARBAGE_RE = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:480p|576p|720p|1080p|1440p|2160p|4K)\b",
        r"\b(?:WEBRip|WEB[\- ]DL|WEB|BluRay|BRRip|BRRiP|BDRip|DVDRip|DvDrip|HDRip|HDTV|CAM|TS|TC|SCR|AMZN)\b",
        r"\b(?:x264|x265|h264|h265|HEVC|AVC|XViD|XviD|XVID)\b",
        r"\b(?:8bit|10bit|10bits|12bit)\b",
        r"\b(?:HDR|HDR10|DV|Dolby Vision)\b",
        r"\b(?:AAC|AC3|EAC3|DD|DDP|DTS|TRUEHD|Atmos|MP3)\b",
        r"\b(?:REPACK|PROPER|INTERNAL|EXTENDED|REMASTERED|UNRATED|REMUX|LIMITED)\b",
        r"\b\d+(?:\.\d+)?\s*(?:GB|MB)\b",
        r"\b(?:YTS|PSA|RARBG|GECKOS|DRONES|COCAIN|SPARKS|DiAMOND|FGT|ION10|RUSTED|ETRG)\b",
        r"\b(?:mp4|mkv|avi)\b",
    )
)

# Keep the original channel-prefix support, but don't make a generic
# uppercase word automatically disappear.
_CHANNEL_PREFIX_RE = re.compile(
    r"""
    ^
    (?:
        BBC|ZDF|CNN|RAI|TVP|RTL|Vox|
        ProSieben|SAT\.?1|HBO|Sky|Canal\+
    )
    \s*[–-]\s*
    """,
    re.I | re.X,
)

_SCENE_GROUP_RE = re.compile(
    r"""
    ^
    (?:
        COCAIN|GECKOS|DRONES|SPARKS|DiAMOND|FGT|ION10|RARBG|
        YIFY|YTS|ETRG|XVID|RUSTED|WAR|GETiT
    )-
    """,
    re.I | re.X,
)

_filename_cache = OrderedDict()
_FILENAME_CACHE_MAX = 700
_filename_cache_lock = threading.RLock()


def is_emc_episode(filename):
    text = _normalize_digits(to_text(filename))

    return bool(
        _S_EMARK_RE.search(text)
        or _X_EMARK_RE.search(text)
        or _SEASON_MARKER_RE.search(text)
        or _EPISODE_MARKER_RE.search(text)
    )


def extract_emc_year(filename):
    match = _FILENAME_YEAR_RE.search(to_text(filename))
    return match.group(1) if match else ""


def _remove_filename_garbage(name):
    for pattern in _GARBAGE_RE:
        name = pattern.sub(" ", name)
    return name


@traced("iConverlibr")
def _clean_filename_uncached(raw):
    raw = to_text(raw)

    if not raw or not is_video_file(raw):
        return "", "", False, ""

    name = normalize_unicode_text(
        os.path.splitext(os.path.basename(raw))[0]
    )
    name = _normalize_digits(name)

    name = _DATE_PREFIX_RE.sub("", name)
    name = _SCENE_GROUP_RE.sub("", name)
    name = _CHANNEL_PREFIX_RE.sub("", name)

    is_ep = is_emc_episode(name)
    ep_marker = ""

    match = _S_EMARK_RE.search(name)

    if match:
        ep_marker = "S%02dE%02d" % (
            int(match.group(1)),
            int(match.group(2)),
        )
    else:
        match = _X_EMARK_RE.search(name)

        if match:
            ep_marker = "S%02dE%02d" % (
                int(match.group(1)),
                int(match.group(2)),
            )

    if is_ep:
        name = _S_EMARK_RE.sub(" ", name)
        name = _X_EMARK_RE.sub(" ", name)
        name = _SEASON_MARKER_RE.sub(" ", name)
        name = _EPISODE_MARKER_RE.sub(" ", name)

    name = _BRACKET_YEAR_RE.sub(r" \1 ", name)
    name = name.replace("_", " ").replace(".", " ")

    name = _BRACKET_RE.sub(" ", name)
    name = _PAREN_RE.sub(" ", name)
    name = _BRACE_RE.sub(" ", name)

    name = _remove_filename_garbage(name)
    name = re.sub(r"\s+", " ", name).strip()

    year_match = _FILENAME_YEAR_RE.search(name)
    year = year_match.group(1) if year_match else ""

    if year_match:
        title_part = name[:year_match.start()].strip(" -._")
        title_part = re.sub(r"\s+", " ", title_part).strip(" -._")
        name = ("%s %s" % (title_part, year)).strip()

    name = re.sub(r"\s+-\s+", " ", name)
    name = name.replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip(" -._")

    clean_title = name

    if year and name.endswith(year):
        clean_title = _FILENAME_YEAR_RE.sub(
            "",
            name,
        ).strip()

    clean_title = _normalize_title_text(clean_title)

    invalid = {
        "",
        "rarbg",
        "com",
        "www",
        "sample",
        "trailer",
        "yts",
        "psa",
    }

    if clean_title.casefold() in invalid:
        return "", "", is_ep, ep_marker

    return clean_title, year, is_ep, ep_marker


def clean_filename(raw):
    if not raw:
        return "", "", False, ""

    raw = to_text(raw)

    with _filename_cache_lock:
        cached = _filename_cache.get(raw)

        if cached is not None:
            _filename_cache.move_to_end(raw)
            return cached

    try:
        result = _clean_filename_uncached(raw)
    except Exception as exc:
        warn(
            "iConverlibr",
            "filename-clean-EX",
            "%s: %s" % (type(exc).__name__, exc),
        )
        result = ("", "", False, "")

    with _filename_cache_lock:
        _filename_cache[raw] = result
        _filename_cache.move_to_end(raw)

        while len(_filename_cache) > _FILENAME_CACHE_MAX:
            _filename_cache.popitem(last=False)

    return result


def build_emc_candidates(filename):
    clean, year, is_ep, _ = clean_filename(filename)

    if not clean:
        return []

    candidates = []

    if year and not is_ep:
        candidates.append("%s %s" % (clean, year))

    candidates.append(clean)

    raw_name = normalize_unicode_text(
        os.path.splitext(
            os.path.basename(to_text(filename))
        )[0]
    )

    raw_name = _normalize_digits(raw_name)
    raw_name = re.sub(r"[._\-]+", " ", raw_name)
    raw_name = re.sub(r"\s+", " ", raw_name).strip()

    if raw_name and raw_name not in candidates:
        candidates.append(raw_name)

    result = []

    for candidate in candidates:
        candidate = _normalize_title_text(candidate)

        if candidate and candidate not in result:
            result.append(candidate)

    return result


def get_sidecar_path(video_path, ext=".jpg"):
    if not video_path:
        return None

    base, _ = os.path.splitext(video_path)
    return base + ext


# ============================================================================
# WIDGET COUNTERS
# ============================================================================

_nxts_refcounts = {}

_widget_refcounts = {
    "poster": 0,
    "backdrop": 0,
    "logo": 0,
    "info": 0,
    "parental": 0,
}

_widget_lock = threading.RLock()


def register_nxts_slot(nxts):
    try:
        nxts = int(nxts)
    except Exception:
        return

    if nxts < 0:
        return

    with _widget_lock:
        _nxts_refcounts[nxts] = (
            _nxts_refcounts.get(nxts, 0) + 1
        )


def unregister_nxts_slot(nxts):
    try:
        nxts = int(nxts)
    except Exception:
        return

    with _widget_lock:
        if nxts not in _nxts_refcounts:
            return

        value = _nxts_refcounts[nxts] - 1

        if value <= 0:
            del _nxts_refcounts[nxts]
        else:
            _nxts_refcounts[nxts] = value


def register_widget_present(kind):
    if kind in _widget_refcounts:
        with _widget_lock:
            _widget_refcounts[kind] += 1


def unregister_widget_present(kind):
    if kind in _widget_refcounts:
        with _widget_lock:
            _widget_refcounts[kind] = max(
                0,
                _widget_refcounts[kind] - 1,
            )


def widget_present(kind):
    with _widget_lock:
        return _widget_refcounts.get(kind, 0) > 0


# ============================================================================
# FALLBACK PIXMAPS
# ============================================================================

_fallback_pixmaps = {}
_fallback_loaded = threading.Event()
_fallback_loading = False
_fallback_lock = threading.RLock()


def _ensure_fallbacks_loaded():
    global _fallback_loading

    if _fallback_loaded.is_set():
        return

    with _fallback_lock:
        if _fallback_loaded.is_set() or _fallback_loading:
            return

        _fallback_loading = True

        def _load():
            global _fallback_loading

            try:
                try:
                    skin = str(
                        config.skin.primary_skin.value
                    ).replace("/skin.xml", "")
                except Exception:
                    skin = "default"

                for name in (
                    "noposter.jpg",
                    "nobackdrop.jpg",
                ):
                    paths = (
                        "/usr/share/enigma2/%s/main/%s"
                        % (skin, name),
                        "/usr/share/enigma2/skin_default/main/%s"
                        % name,
                        "/tmp/%s" % name,
                    )

                    for path in paths:
                        if not os.path.isfile(path):
                            continue

                        try:
                            pixmap = loadJPG(path)

                            if pixmap:
                                _fallback_pixmaps[name] = pixmap
                        except Exception:
                            pass

                        break

            finally:
                with _fallback_lock:
                    _fallback_loading = False
                    _fallback_loaded.set()

        try:
            thread = threading.Thread(
                target=_load,
                name="XDREAMY-Fallback",
                daemon=True,
            )
        except TypeError:
            thread = threading.Thread(
                target=_load,
                name="XDREAMY-Fallback",
            )

        try:
            thread.start()
        except Exception:
            with _fallback_lock:
                _fallback_loading = False


def get_fallback_pixmap(name):
    _ensure_fallbacks_loaded()

    return (
        _fallback_pixmaps.get(name)
        if _fallback_loaded.is_set()
        else None
    )


# ============================================================================
# ZAP CONTEXT
# ============================================================================

class ZapContext(object):
    __slots__ = (
        "_ref_str",
        "_slots",
        "_ch_skip",
        "_slot_count",
        "generation",
        "missing",
        "_missing_titles",
        "_lock",
        "_analyzed_cache",
        "_events_raw",
        "_slot_0_built",
        "_slots_built",
    )

    def __init__(
        self,
        ref_str,
        events,
        ch_skip=False,
        generation=0,
    ):
        self._ref_str = ref_str
        self._ch_skip = bool(ch_skip)
        self.generation = generation
        self._slot_count = 0
        self._slots = {}
        self.missing = []
        self._missing_titles = set()
        self._lock = threading.RLock()
        self._analyzed_cache = {}
        self._events_raw = list(events) if events else []
        self._slot_0_built = False
        self._slots_built = set()

        # Never allow a bad first event to break service switching.
        try:
            self._build_slot(0)
        except Exception as exc:
            warn(
                "iConverlibr",
                "zap-slot0-EX",
                "%s: %s" % (type(exc).__name__, exc),
            )

    def schedule_retry(self):
        return False

    def _build_slot(self, nxts):
        with self._lock:
            if nxts in self._slots_built:
                return self._slots.get(nxts)

        if nxts < 0 or nxts >= len(self._events_raw):
            return None

        evt = self._events_raw[nxts]

        if (
            not isinstance(evt, (tuple, list))
            or len(evt) < 5
            or not evt[4]
        ):
            return None

        try:
            raw = clean_name(evt[4])
            desc = evt[5] if len(evt) > 5 else ""
            begin_time = evt[1] if len(evt) > 1 else 0

            with self._lock:
                analyzed = self._analyzed_cache.get(raw)

            if analyzed is None:
                analyzed = analyze_epg_title(raw)

                with self._lock:
                    self._analyzed_cache[raw] = analyzed

            skip, clean, candidates = analyzed
            skip = bool(skip or self._ch_skip)

            rec = _epg_store.get(clean) if clean else None
            data = rec["data"] if rec else {}

            if clean:
                assets = resolve_asset_paths(clean)
            else:
                assets = {
                    "local_path": None,
                    "backdrop_path": None,
                    "logo_path": None,
                }

            meta = (
                build_meta_dict(data)
                if clean and has_useful_metadata(data)
                else None
            )

            slot = {
                "clean_title": clean,
                "local_path": assets["local_path"],
                "backdrop_path": assets["backdrop_path"],
                "logo_path": assets["logo_path"],
                "skip": skip,
                "search_candidates": candidates,
                "event_key": make_event_key(begin_time, raw),
                "raw_name": raw,
                "description": desc,
                "hint_year": (
                    extract_epg_hints(desc).get("year")
                    if desc
                    else None
                ),
                "begin_time": begin_time,
                "slot_index": nxts,
            }

            slot.update(meta or _EMPTY_METADATA)

            with self._lock:
                self._slots[nxts] = slot
                self._slot_count = max(
                    self._slot_count,
                    nxts + 1,
                )
                self._slot_0_built |= nxts == 0
                self._slots_built.add(nxts)

                if (
                    clean
                    and not skip
                    and (
                        not assets["local_path"]
                        or not assets["backdrop_path"]
                        or not assets["logo_path"]
                    )
                    and clean not in self._missing_titles
                ):
                    self._missing_titles.add(clean)
                    self.missing.append(
                        (
                            clean,
                            raw,
                            candidates,
                            slot["hint_year"],
                        )
                    )

            return slot

        except Exception as exc:
            warn(
                "iConverlibr",
                "zap-build-slot-EX",
                "%s: %s" % (type(exc).__name__, exc),
            )

            # Mark the slot as built so a permanently bad event isn't
            # repeatedly processed on every renderer update.
            with self._lock:
                self._slots_built.add(nxts)

            return None

    def get_slot(self, nxts):
        with self._lock:
            slot = self._slots.get(nxts)

            if slot is not None:
                return slot

        return self._build_slot(nxts)

    def update_slot_metadata(
        self,
        clean_title,
        meta_dict,
        event_key=None,
    ):
        if not clean_title or not meta_dict:
            return

        changed = False

        with self._lock:
            for slot in self._slots.values():
                if slot.get("clean_title") != clean_title:
                    continue

                if (
                    event_key
                    and slot.get("event_key") != event_key
                ):
                    continue

                slot.update(meta_dict)
                changed = True

            if changed:
                self.generation += 1

    def update_slot_asset(
        self,
        clean_title,
        kind,
        path,
        event_key=None,
    ):
        key = {
            "poster": "local_path",
            "backdrop": "backdrop_path",
            "logo": "logo_path",
        }.get(kind)

        if not key:
            return

        path = (
            to_text(path).strip()
            if path
            else None
        )

        with self._lock:
            for slot in self._slots.values():
                if slot.get("clean_title") != clean_title:
                    continue

                if (
                    event_key
                    and slot.get("event_key") != event_key
                ):
                    continue

                slot[key] = path

            self.generation += 1

        if path:
            folder = {
                "poster": get_poster_folder,
                "backdrop": get_backdrop_folder,
                "logo": get_logo_folder,
            }[kind]

            try:
                mark_file_indexed(
                    folder(),
                    os.path.basename(path),
                )
            except Exception:
                pass

    def is_valid_for(self, ref_str):
        return self._ref_str == ref_str

    @property
    def ref_str(self):
        return self._ref_str


# ============================================================================
# EPG CACHE / GLOBAL ZAP
# ============================================================================

class _EpgCache(object):
    __slots__ = (
        "_data",
        "_ref",
        "_last_fetch",
        "_lock",
    )

    def __init__(self):
        self._data = []
        self._ref = None
        self._last_fetch = 0
        self._lock = threading.RLock()

    def clear(self):
        with self._lock:
            self._data = []
            self._ref = None
            self._last_fetch = 0

    def get(self, service_ref):
        if not service_ref:
            return []

        try:
            ref_str = service_ref.toString()
        except Exception:
            return []

        now = time.monotonic()

        with self._lock:
            if (
                self._ref == ref_str
                and self._data
                and now - self._last_fetch < 2.0
            ):
                return self._data

        events = []

        try:
            from enigma import eEPGCache

            epg = eEPGCache.getInstance()

            if epg:
                result = epg.lookupEvent([
                    "IBOCTESX",
                    (ref_str, 0, -1, -1),
                ])

                if result:
                    events = list(result)

        except Exception as exc:
            warn(
                "iConverlibr",
                "epg-cache-lookup-EX",
                str(exc),
            )

        with self._lock:
            self._data = events
            self._ref = ref_str
            self._last_fetch = now
            return self._data


_epg_cache = _EpgCache()
_zap_ctx = None
_zap_ctx_lock = threading.RLock()
_current_ref = [None]
_batch_request_fn = [None]


def set_batch_request_fn(fn):
    _batch_request_fn[0] = fn if callable(fn) else None


def invalidate_zap_context(
    force=False,
    for_title=None,
):
    global _zap_ctx

    with _zap_ctx_lock:
        if _zap_ctx is None:
            return

        if force:
            _zap_ctx = None
            return

        current = _current_ref[0]

        if not current or not _zap_ctx.is_valid_for(current):
            _zap_ctx = None
            return

        if for_title:
            if any(
                slot.get("clean_title") == for_title
                for slot in _zap_ctx._slots.values()
            ):
                _zap_ctx = None
        else:
            _zap_ctx = None


def update_global_zap_asset(
    clean_title,
    kind,
    path,
    event_key=None,
):
    global _zap_ctx

    if not clean_title or kind not in (
        "poster",
        "backdrop",
        "logo",
    ):
        return

    with _zap_ctx_lock:
        ctx = _zap_ctx

        if ctx is None:
            return

        try:
            ctx.update_slot_asset(
                clean_title,
                kind,
                path,
                event_key,
            )
        except Exception as exc:
            err(
                "iConverlibr",
                "update-global-zap-asset-EX",
                str(exc),
            )

    if path:
        folder = {
            "poster": get_poster_folder,
            "backdrop": get_backdrop_folder,
            "logo": get_logo_folder,
        }[kind]

        try:
            mark_file_indexed(
                folder(),
                os.path.basename(path),
            )
        except Exception:
            pass


# ============================================================================
# EVENT SOURCE METADATA
# ============================================================================

@traced("iConverlibr")
def get_event_source_metadata(event_source):
    try:
        evt = event_source.event

        if not evt:
            return None

        raw = clean_name(evt.getEventName())

        if (
            not raw
            or _is_no_info(raw)
            or _is_skip_event(raw)
        ):
            return None

        skip, clean, candidates = analyze_epg_title(raw)

        if skip or not clean:
            return None

        begin_time = evt.getBeginTime() or 0
        event_key = make_event_key(begin_time, raw)
        assets = resolve_asset_paths(clean)

        rec = _epg_store.get(clean)
        data = rec["data"] if rec else {}

        try:
            desc = evt.getExtendedDescription() or ""
        except Exception:
            desc = ""

        slot = {
            "clean_title": clean,
            "local_path": assets["local_path"],
            "backdrop_path": assets["backdrop_path"],
            "logo_path": assets["logo_path"],
            "skip": False,
            "search_candidates": candidates,
            "event_key": event_key,
            "raw_name": raw,
            "description": desc,
            "hint_year": extract_epg_hints(desc).get("year"),
            "begin_time": begin_time,
        }

        slot.update(
            build_meta_dict(data)
            if has_useful_metadata(data)
            else _EMPTY_METADATA
        )

        return slot

    except Exception as exc:
        warn(
            "iConverlibr",
            "event-source-metadata-EX",
            str(exc),
        )
        return None


# ============================================================================
# ZAP CONTEXT CREATION
# ============================================================================

@traced("iConverlibr")
def get_zap_context(service_ref):
    global _zap_ctx

    if service_ref is None:
        return None

    try:
        ref_str = service_ref.toString()
    except Exception:
        return None

    if not ref_str:
        return None

    _current_ref[0] = ref_str

    if (
        "FROM BOUQUET" in ref_str
        or "ORDER BY bouquet" in ref_str
    ):
        return ZapContext(
            "bouquet",
            [],
            True,
        )

    with _zap_ctx_lock:
        if (
            _zap_ctx is not None
            and _zap_ctx.is_valid_for(ref_str)
        ):
            return _zap_ctx

    ch_skip = False

    try:
        from ServiceReference import ServiceReference as SR

        ch_skip = is_sport_or_news_channel(
            SR(service_ref).getServiceName()
        )
    except Exception:
        pass

    try:
        generation = int(
            time.time() * 1000
        ) % 1000000

        events = (
            []
            if ch_skip
            else _epg_cache.get(service_ref)
        )

        new_ctx = ZapContext(
            ref_str,
            events or [],
            ch_skip,
            generation=generation,
        )

    except Exception as exc:
        # This is deliberately defensive because get_zap_context()
        # runs from renderer/UI update paths.
        err(
            "iConverlibr",
            "zap-context-EX",
            "%s: %s" % (type(exc).__name__, exc),
        )
        return None

    with _zap_ctx_lock:
        if (
            _zap_ctx is not None
            and _zap_ctx.is_valid_for(ref_str)
        ):
            return _zap_ctx

        _zap_ctx = new_ctx

    request_fn = _batch_request_fn[0]

    if request_fn and new_ctx.missing:
        try:
            request_fn(list(new_ctx.missing))
        except Exception as exc:
            err(
                "iConverlibr",
                "batch-request-EX",
                str(exc),
            )

    return new_ctx


# ============================================================================
# SEARCH CACHE
# ============================================================================

_SEARCH_TTL = 1800
_SEARCH_CACHE_MAX = 500
_search_cache = OrderedDict()
_search_lock = threading.RLock()


def get_cached_search(clean_title):
    clean_title = to_text(clean_title).strip()

    if not clean_title:
        return None

    now = time.monotonic()

    with _search_lock:
        entry = _search_cache.get(clean_title)

        if entry is None:
            return None

        timestamp, result = entry

        if now - timestamp > _SEARCH_TTL:
            del _search_cache[clean_title]
            return None

        _search_cache.move_to_end(clean_title)
        return result


def set_cached_search(clean_title, result):
    clean_title = to_text(clean_title).strip()

    if not clean_title or not result:
        return

    with _search_lock:
        _search_cache[clean_title] = (
            time.monotonic(),
            result,
        )

        _search_cache.move_to_end(clean_title)

        while len(_search_cache) > _SEARCH_CACHE_MAX:
            _search_cache.popitem(last=False)


# ============================================================================
# CACHE RESET
# ============================================================================

def clear_runtime_caches():
    with _analyze_cache_lock:
        _analyze_cache.clear()

    with _filename_cache_lock:
        _filename_cache.clear()

    with _search_lock:
        _search_cache.clear()

    _clear_asset_cache()

    try:
        cached_format_overview.cache_clear()
    except Exception:
        pass

    try:
        _epg_cache.clear()
    except Exception:
        pass

    invalidate_zap_context(force=True)


# ============================================================================
# HEALTH
# ============================================================================

def _health_probe():
    try:
        with _zap_ctx_lock:
            zap_valid = _zap_ctx is not None

        with _metadata_callback_lock:
            callback_keys = len(_metadata_callbacks)

        with _ready_queue_lock:
            queued = len(_ready_queue)

        with _analyze_cache_lock:
            analyzed = len(_analyze_cache)

        with _filename_cache_lock:
            filenames = len(_filename_cache)

        with _search_lock:
            searches = len(_search_cache)

        return {
            "zap_context": zap_valid,
            "metadata_callback_keys": callback_keys,
            "gui_queue": queued,
            "analyze_cache": analyzed,
            "filename_cache": filenames,
            "search_cache": searches,
            "storage": get_base_path(),
        }

    except Exception:
        return {}


try:
    register_health_probe(
        "iConverlibr",
        _health_probe,
    )
except Exception:
    pass


# ============================================================================
# END
# ============================================================================