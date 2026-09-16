#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
iConverlibr.py - XDREAMY SKIN V8.20

Compact Enigma2 / Python 3+ EPG and media cleaning engine.

Pipeline:

    raw_name
        -> Unicode normalization
        -> separator normalization
        -> safe metadata removal
        -> season / episode extraction
        -> generic release/noise removal
        -> trailing label cleanup
        -> year extraction
        -> stable clean title
        -> conservative search candidates

Design:
    raw_name          = original EPG/media identity
    clean_title       = stable local/TMDB search identity
    search_candidates = conservative TMDB queries
    event_key         = individual EPG occurrence identity

The cleaner is Unicode-aware and language-neutral.
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


from .iDebugger import (
    traced,
    dbg,
    warn,
    err,
    register_health_probe,
)


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
    "WORKER_THREADS": 4,
    "TMDB_API_KEY": "",
    "RTL_OVERVIEW": True,
    "BACKDROP_SIZE": "w500",
    "LOGO_SIZE": "w300",
    # Downloader diagnostics. Keep all disabled by default after debugging.
    "LOG_FOUND_EVENTS": False,
    "LOG_DEBUG_SEARCH": False,
    "LOG_DEBUG_CACHE": False,
    "LOG_DEBUG_QUEUE": False,
}


STORAGE_PATH = None


def is_activated():
    try:
        return XDREAMY_SKIN_MARKER in str(
            getattr(
                config.skin.primary_skin,
                "value",
                "",
            )
            or ""
        ).lower()
    except Exception:
        return False


def get_cfg(key):
    return _runtime_cfg.get(key)


def _config_value(plugin_cfg, attr, default):
    try:
        value = getattr(
            plugin_cfg,
            attr,
        )
        return value.value
    except Exception:
        return default


def _normalize_storage_path(path):
    if not path:
        return None

    try:
        path = os.path.normpath(
            os.path.expanduser(
                str(path).strip()
            )
        )
    except Exception:
        return None

    if path in ("", "."):
        return None

    return path


def _bootstrap_storage_from_saved_config():
    try:
        xd = config.plugins.xDreamy

        mode = getattr(
            xd,
            "storage_mode",
            None,
        )

        custom = getattr(
            xd,
            "storage_custom_path",
            None,
        )

        if (
            mode is not None
            and custom is not None
            and getattr(
                mode,
                "value",
                None,
            ) == "custom"
        ):
            value = getattr(
                custom,
                "value",
                None,
            )

            if value:
                _runtime_cfg["STORAGE_PATH"] = (
                    _normalize_storage_path(
                        value
                    )
                )

    except Exception:
        pass


_bootstrap_storage_from_saved_config()


def _ensure_dir(path):
    if not path:
        return False

    try:
        os.makedirs(
            path,
            exist_ok=True,
        )
    except TypeError:
        try:
            os.makedirs(path)
        except OSError:
            pass
    except OSError:
        pass

    try:
        return os.path.isdir(path)
    except Exception:
        return False


def _get_base_path():
    global STORAGE_PATH

    if STORAGE_PATH:
        try:
            if os.path.isdir(STORAGE_PATH):
                return STORAGE_PATH
        except Exception:
            pass

    STORAGE_PATH = None

    custom = _normalize_storage_path(
        _runtime_cfg.get(
            "STORAGE_PATH"
        )
    )

    if custom:
        if (
            os.path.basename(
                custom
            ).lower()
            == "xdreamy"
        ):
            base = custom
        else:
            base = os.path.join(
                custom,
                "XDREAMY",
            )

        if _ensure_dir(base):
            STORAGE_PATH = base
            return base

    for mount in (
        "/media/hdd",
        "/media/usb",
        "/media/mmc",
    ):
        try:
            if (
                os.path.isdir(mount)
                and os.access(
                    mount,
                    os.W_OK,
                )
            ):
                base = os.path.join(
                    mount,
                    "XDREAMY",
                )

                if _ensure_dir(base):
                    STORAGE_PATH = base
                    return base

        except Exception:
            pass

    base = "/tmp/XDREAMY"

    if _ensure_dir(base):
        warn(
            "iConverlibr",
            "storage-fallback",
            base,
        )

    STORAGE_PATH = base
    return base


def _init_folders():
    base = _get_base_path()

    for name in (
        "poster",
        "backdrop",
        "logo",
        "backup",
    ):
        _ensure_dir(
            os.path.join(
                base,
                name,
            )
        )

    return base


def get_base_path():
    return _get_base_path()


def get_poster_folder():
    return os.path.join(
        _get_base_path(),
        "poster",
    )


def get_backdrop_folder():
    return os.path.join(
        _get_base_path(),
        "backdrop",
    )


def get_logo_folder():
    return os.path.join(
        _get_base_path(),
        "logo",
    )


def get_backup_folder():
    return os.path.join(
        _get_base_path(),
        "backup",
    )


def get_cache_path(filename):
    """
    Return a path rooted in XDREAMY storage.

    Only the basename is accepted, preventing path traversal.
    """
    base = _get_base_path()

    if not filename:
        return base

    return os.path.join(
        base,
        os.path.basename(
            to_text(filename)
        ),
    )


def get_metadata_db_path():
    return os.path.join(
        _get_base_path(),
        "iMetaData.db",
    )


def get_server_channels_json_path():
    return os.path.join(
        _get_base_path(),
        "ServerChannels.json",
    )


@traced("iConverlibr")
def apply_plugin_config(plugin_cfg):
    global STORAGE_PATH

    defaults = (
        (
            "TMDB_LANGUAGE",
            "tmdb_language",
            "en",
        ),
        (
            "POSTERX_ENABLED",
            "posterx_enabled",
            True,
        ),
        (
            "BACKDROPX_ENABLED",
            "backdropx_enabled",
            True,
        ),
        (
            "LOGOX_ENABLED",
            "logox_enabled",
            True,
        ),
        (
            "TMDB_API_KEY",
            "tmdb_api_key",
            "",
        ),
        (
            "RTL_OVERVIEW",
            "rtl_overview",
            True,
        ),
        (
            "BACKDROP_SIZE",
            "backdrop_size",
            "w500",
        ),
        (
            "LOGO_SIZE",
            "logo_size",
            "w300",
        ),
    )

    for key, attr, default in defaults:
        _runtime_cfg[key] = _config_value(
            plugin_cfg,
            attr,
            default,
        )

    try:
        _runtime_cfg["WORKER_THREADS"] = max(
            1,
            int(
                _config_value(
                    plugin_cfg,
                    "worker_threads",
                    4,
                )
            ),
        )
    except Exception:
        _runtime_cfg["WORKER_THREADS"] = 4

    mode = _config_value(
        plugin_cfg,
        "storage_mode",
        "auto",
    )

    if mode == "custom":
        _runtime_cfg["STORAGE_PATH"] = (
            _normalize_storage_path(
                _config_value(
                    plugin_cfg,
                    "storage_custom_path",
                    "/media/hdd/XDREAMY",
                )
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
        warn(
            "iConverlibr",
            "config-db-reopen-EX",
            str(exc),
        )

    clear_runtime_caches()

    dbg(
        "iConverlibr",
        "config-applied",
        "workers=%s"
        % _runtime_cfg["WORKER_THREADS"],
    )


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
            return value.decode(
                encoding,
                "ignore",
            )
        except Exception:
            return ""

    try:
        return str(value)
    except Exception:
        return ""


_ARABIC_TRANSLATION = str.maketrans({
    "\u0622": "\u0627",
    "\u0623": "\u0627",
    "\u0625": "\u0627",
    "\u0671": "\u0627",
    "\u06CC": "\u064A",
    "\u06D2": "\u064A",
    "\u06A9": "\u0643",
    "\u0640": "",
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


_SPACE_RE = re.compile(
    r"\s+",
    re.UNICODE,
)


def normalize_unicode_text(
    text,
    arabic=True,
):
    text = to_text(text)

    if not text:
        return ""

    try:
        text = unicodedata.normalize(
            "NFKC",
            text,
        )
    except Exception:
        pass

    text = _ZERO_WIDTH_RE.sub(
        "",
        text,
    )

    if arabic:
        text = text.translate(
            _ARABIC_TRANSLATION
        )

        text = _ARABIC_MARKS_RE.sub(
            "",
            text,
        )

    # NFKC does not normalize every spacing
    # character to ASCII whitespace.
    text = "".join(
        " "
        if unicodedata.category(ch) == "Zs"
        else ch
        for ch in text
    )

    return text.strip()


def _normalize_title_text(text):
    text = normalize_unicode_text(text)

    if not text:
        return ""

    return _SPACE_RE.sub(
        " ",
        text,
    ).strip()


def is_arabic(text):
    text = to_text(text)[:300]

    if not text:
        return False

    letters = 0
    rtl_letters = 0

    for ch in text:
        if not ch.isalpha():
            continue

        letters += 1

        if _RTL_RE.search(ch):
            rtl_letters += 1

    if not letters:
        return False

    return (
        rtl_letters
        / float(letters)
        > 0.20
    )


# ----------------------------------------------------------------------------
# Romanized Arabic detection
# ----------------------------------------------------------------------------

# Expanded list of common Arabic transliteration fragments
_ARABIC_TRANSLIT_FRAGMENTS = (
    "el", "al", "ibn", "bin", "abu", "wa", "fi", "min", "li", "ya",
    "ma", "kull", "nass", "qalb", "hob", "lila", "dahab", "kha'en",
    "maddah", "ankaboot", "zawga", "matab", "sinai", "antar", "akher",
    "khalil", "habibati", "ezay", "kher", "baraka", "sabahak", "azhar",
    "alf", "nowaylati", "darb", "seed", "ahlan", "shaqet", "faisal",
    "thalatha", "thaleth", "rabi", "hamza", "mustafa", "mohamed", "ahmed",
    "ali", "omar", "khaled", "layla", "hoda", "samir", "nadia", "farid",
    "gamal", "nabil", "sherif", "hany", "tarek", "yasser", "amr", "mostafa",
    "ibrahim", "ismail", "abdullah", "rahman", "raheem", "karim", "jamil",
    "rasheed", "sameh", "maged", "sayed", "hassan", "hussain", "youssef",
    "nour", "amal", "hadi", "sami", "majid", "fateen", "oomak", "me",
    "periferya", "imperya", "buzaglos", "lobosco", "stanlio", "ollio",
    "maja", "kabaretowy", "czesuaf", "kryminalne", "zagadki", "jorku",
    "sittat", "tadeel", "shadad", "shaddad", "antr", "bad", "bi",
    "sitt", "banat", "tehebak", "zelt", "thonoub", "woroud", "haneen",
    "katebet", "eadaam", "motawahesh", "mintaqa", "amina", "zawga", "akher",
    "kher", "baraka", "sinai", "matab", "antar", "ibin", "shadad",
    "ahlan", "shaqet", "faisal", "nowaylati", "darb", "seed", "maddah",
    "ostouret", "wadi", "azhar", "hob", "kha'en", "woroud", "thonoub",
    "zelt", "habibati", "takoun",
)


def looks_romanized_arabic(value):
    """
    Detect if a Latin-script string is likely a romanized Arabic title.

    Rules:
        - If it contains Arabizi digits (2-9) → True
        - If any core fragment appears → True
        - If at least two distinct fragments from the full list appear → True
    """
    value = to_text(value)

    if not value:
        return False

    # If it contains Arabic script, it's not romanized (but we may still use it)
    if re.search(r"[\u0600-\u06FF]", value):
        return False

    lower = value.lower()

    # 1. Check for Arabizi digits
    if re.search(r"[2-9]", lower):
        return True

    # 2. Check for any fragment (most common)
    for frag in _ARABIC_TRANSLIT_FRAGMENTS:
        if frag in lower:
            return True

    # 3. Count distinct fragments (at least 2)
    count = 0
    for frag in _ARABIC_TRANSLIT_FRAGMENTS:
        if frag in lower:
            count += 1
            if count >= 2:
                return True

    return False


def clean_name(name):
    return _normalize_title_text(
        to_text(name)
        .replace("\x86", "")
        .replace("\x87", "")
    )


# ============================================================================
# CHANNEL / EPG FILTERS
# ============================================================================

def _compile_keyword_matchers(keywords):
    """
    Compile keyword groups once.

    Historically _match_keywords() constructed a fresh regular
    expression for every single keyword on every invocation. That is
    unnecessarily expensive because channel/event filtering is a hot path.
    """

    phrase_parts = []
    word_parts = []

    for keyword in keywords:
        keyword = to_text(
            keyword
        ).strip()

        if not keyword:
            continue

        escaped = re.escape(
            keyword
        )

        if " " in keyword:
            phrase_parts.append(
                escaped
            )
        else:
            word_parts.append(
                escaped
            )

    phrase_re = (
        re.compile(
            "|".join(
                phrase_parts
            ),
            re.I | re.U,
        )
        if phrase_parts
        else None
    )

    word_re = (
        re.compile(
            r"(?<!\w)(?:"
            + "|".join(
                word_parts
            )
            + r")(?!\w)",
            re.I | re.U,
        )
        if word_parts
        else None
    )

    return (
        phrase_re,
        word_re,
    )


def _match_compiled_keywords(
    text,
    matchers,
):
    if not text:
        return False

    phrase_re, word_re = matchers

    if (
        phrase_re is not None
        and phrase_re.search(text)
    ):
        return True

    if (
        word_re is not None
        and word_re.search(text)
    ):
        return True

    return False


SKIP_CHANNEL_KEYWORDS = (
    "sport",
    "sports",
    "espn",
    "eurosport",
    "bein sport",
    "dazn",
    "sky sport",
    "fox sport",
    "nba tv",
    "nfl network",
    "golf channel",
    "motorsport",
    "racing",
    "tennis channel",
    "news",
    "cnn",
    "bbc news",
    "fox news",
    "sky news",
    "al jazeera",
    "bloomberg",
    "weather",
    "meteo",
    "tg1",
    "tg2",
    "tg3",
    "tg4",
    "tg5",
    "rainews",
    "tvp info",
    "tvp sport",
    "polsat sport",
    "canal+ sport",
    "sportklub",
)


_NO_INFO_WORDS = (
    "no information",
    "no info",
    "no event info",
    "press epg",
    "brak informacji",
    "brak danych",
    "informacja niedostępna",
    "wciśnij przycisk",
    "press button",
    "info -",
    "epg -",
    "info wciśnij",
    "info press",
    "brak tytułu",
    "no title",
    "niedostępne",
    "unavailable",
    "not available",
    "epg not available",
    "program nieznany",
    "unknown program",
    "our broadcasts will resume",
    "premium channel",
    "daystar channel",
    "zakończenie programu",
    "koniec programu",
    "end of program",
    "programmende",
    "fine programma",
    "fin de programme",
    "نهاية البرنامج",
    "لا توجد معلومات",
    "برامج قناة",
    "قناة تجريبية",
    "test channel",
    "programmes de la nuit",
)


_NO_INFO_RE = re.compile(
    "|".join(
        re.escape(word)
        for word in _NO_INFO_WORDS
    ),
    re.I | re.U,
)


_SKIP_EVENT_KEYWORDS = (
    # Explicit sports / live-match signals only. Generic TV-program names,
    # news, weather, magazine, documentary and entertainment labels are kept.
    "sport",
    "sports",
    "game day",
    "playoff",
    "tournament",
    "grand prix",
    "formula 1",
    "formula e",
    "qualifying",
    "football",
    "soccer",
    "basketball",
    "tennis",
    "golf",
    "baseball",
    "hockey",
    "volleyball",
    "boxing",
    "wrestling",
    "ufc",
    "mma",
    "bkfc",
    "motorsport",
    "racing",
    "piłka",
    "mecz",
    "mecze",
    "mistrzostwa",
    "puchar",
    "turniej",
    "zawody",
    "siatkówka",
    "koszykówka",
    "piłka nożna",
    "hokej",
    "żużel",
    "walka",
    "kolarstwo",
    "narciarstwo",
    "skoki",
    "coppa italia",
    "tour de france",
    "championnat",
    "coupe du monde",
)


_SKIP_EVENT_MATCHERS = (
    _compile_keyword_matchers(
        _SKIP_EVENT_KEYWORDS
    )
)


_SKIP_CHANNEL_MATCHERS = (
    _compile_keyword_matchers(
        SKIP_CHANNEL_KEYWORDS
    )
)


def _match_keywords(text, keywords):
    """
    Compatibility wrapper.

    For the known hot-path keyword sets, use their precompiled matchers.
    For arbitrary external callers, compile once locally.
    """
    text = to_text(text)

    if not text:
        return False

    if keywords is SKIP_CHANNEL_KEYWORDS:
        return _match_compiled_keywords(
            text,
            _SKIP_CHANNEL_MATCHERS,
        )

    if keywords is _SKIP_EVENT_KEYWORDS:
        return _match_compiled_keywords(
            text,
            _SKIP_EVENT_MATCHERS,
        )

    return _match_compiled_keywords(
        text,
        _compile_keyword_matchers(
            keywords
        ),
    )


def _is_no_info(text):
    text = _normalize_title_text(text)

    return (
        not text
        or bool(
            _NO_INFO_RE.search(text)
        )
    )


def _is_skip_event(text):
    text = _normalize_title_text(text)

    if not text:
        return False

    return _match_compiled_keywords(
        text,
        _SKIP_EVENT_MATCHERS,
    )


def is_sport_or_news_channel(channel_name):
    name = clean_name(
        channel_name
    )

    if not name:
        return False

    return _match_compiled_keywords(
        name,
        _SKIP_CHANNEL_MATCHERS,
    )


# ============================================================================
# UNIVERSAL TITLE CLEANING
# ============================================================================

_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


def _normalize_digits(text):
    return to_text(text).translate(
        _DIGIT_TRANSLATION
    )


def _roman_number(value):
    value = to_text(
        value
    ).upper().strip()

    if not value:
        return None

    if not re.fullmatch(
        r"I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XL|L",
        value,
    ):
        return None

    values = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
    }

    total = 0
    previous = 0

    for char in reversed(value):
        current = values[char]

        if current < previous:
            total -= current
        else:
            total += current

        previous = current

    return total


def _number_value(value):
    value = to_text(
        value
    ).strip()

    if value.isdigit():
        try:
            return int(value)
        except Exception:
            return None

    return _roman_number(value)


_ROMAN_NUM = (
    r"XXXVIII|XXVIII|XXXVII|XXXIII|XLVIII|XXXIX|XVIII|XLIII|"
    r"XXXVI|XXXIV|XLVII|XXVII|XXXII|XXIII|XLVI|XVII|XXVI|XXIX|"
    r"XXXV|VIII|XLIX|XLII|XXXI|XXII|XLIV|XXIV|XIII|VII|XII|XVI|"
    r"XXX|XIV|XLV|XXI|XIX|III|XLI|XXV|IV|XL|IX|XX|II|XV|XI|VI|V|I|X"
)


_ROMAN_EPISODE_RE = re.compile(
    r"\bS(?:EASON)?\s*(?P<s>"
    + _ROMAN_NUM
    + r")\s*E(?:PISODE)?\s*(?P<e>"
    + _ROMAN_NUM
    + r")\b",
    re.I | re.U,
)


_ROMAN_SEASON_WORD_RE = re.compile(
    r"\b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|"
    r"SEZON|MUSIM|موسم)(?:\s+|[-.:]+)\s*(?P<s>"
    + _ROMAN_NUM
    + r")\b",
    re.I | re.U,
)


_EPISODE_RE = re.compile(
    r"""
    (?:
        \bS(?:EASON)?\s*(?P<s1>\d{1,3})\s*
        (?:E(?:P(?:ISODE)?)?|X)\s*(?P<e1>\d{1,4})\b

      |
        \b(?P<s2>\d{1,3})\s*[xX]\s*(?P<e2>\d{1,4})\b

      |
        \b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|
            SEZON|SEASONEN|MUSIM|MUSIMI|موسم)\s*
        (?P<s3>\d{1,3})\s*
        (?:EPISODE|EP|ODCINEK|ODC|FOLGE|TEIL|EPISODIO|
            EPISOD|CHAPITRE|CAPITULO|CAPÍTULO|BÖLÜM|BOLUM|
            PUNTATA|حلقة|جزء)\s*
        (?P<e3>\d{1,4})\b

      |
        \b(?:SEASON|SAISON|SERIE|SERIES|STAGIONE|TEMPORADA|
            SEZON|MUSIM|موسم)\s*(?P<s4>\d{1,3})\b
    )
    """,
    re.I | re.U | re.X,
)


# NEW: Arabic season/part marker (ج or جزء)
_ARABIC_SEASON_RE = re.compile(
    r"\b(?:ج|جزء)\s*(\d{1,3})\b",
    re.I | re.U,
)


_PART_RE = re.compile(
    r"\b(?:part|parte|جزء)\.?\s*[.:_-]?\s*\d{1,3}\b",
    re.I | re.U,
)

_TITLE_EPISODE_DASH_RE = re.compile(
    r"\s+-\s+\d{1,3}\s*[.:]\s*",
    re.I | re.U,
)

_SEASON_SUFFIX_RE = re.compile(
    r"(?:^|\s)S\s*(\d{1,3})\s*$",
    re.I | re.U,
)

_NUMERIC_SEASON_BEFORE_EP_RE = re.compile(
    r"(?:^|\s)(?P<s>\d{1,3})\s*(?=[:,.-]?\s*(?:EPISODE|EP|ODCINEK|ODC|FOLGE|EPISODIO|EPISOD|PUNTATA|CAPITULO|CAPÍTULO|CHAPITRE|BÖLÜM|BOLUM|PT\.?|P\.?)\b)",
    re.I | re.U,
)

_NUMBERED_SEASON_TITLE_PART_RE = re.compile(
    r"(?:^|\s)(?P<s>\d{1,2})\s*-\s*[^-]+?\b(?:P(?:ART)?\.?|PARTE)\s*\d{1,3}\s*$",
    re.I | re.U,
)

_ROMAN_SEASON_BEFORE_EP_RE = re.compile(
    r"(?:^|\s)(?P<s>" + _ROMAN_NUM + r")(?=\s*(?:[-:,.]?\s*)?(?:EPISODE|EP|ODCINEK|ODC|FOLGE|EPISODIO|EPISOD|PUNTATA|CAPITULO|CAPÍTULO|CHAPITRE|BÖLÜM|BOLUM|PT\.?|P\.?)\b)",
    re.I | re.U,
)

_PAREN_ROMAN_SEASON_BEFORE_EP_RE = re.compile(
    r"\(\s*(?P<s>" + _ROMAN_NUM + r")\s*\)(?=\s*(?:[-:,.]?\s*)?(?:EPISODE|EP|ODCINEK|ODC|FOLGE|EPISODIO|EPISOD|PUNTATA|CAPITULO|CAPÍTULO|CHAPITRE|BÖLÜM|BOLUM|PT\.?|P\.?)\b)",
    re.I | re.U,
)

_PAREN_EPISODE_RE = re.compile(
    r"""
    \s*\(
        [^)]*
        (?:
            odc|ep|season|serija|p\.|#|série|stagione|
            temporada|sezon|حلقة|جزء|موسم
        )
        \s*\.?\s*
        \d+
        (?:\s*[,/&]\s*\d+)*
        [^)]*
    \)
    """,
    re.I | re.U | re.X,
)


_NUMBERED_SEASON_MARKER_RE = re.compile(
    r"""
    \b
    (?P<s>\d{1,3})
    \s*
    (?:[:,]\s*|\s*[-–—]\s*)
    (?:ep(?:isode)?|odc)\.?
    \s*
    \d{1,4}
    (?:\s*[,/&]\s*\d{1,4})*
    (?:\s*[.:,-]\s*[^-–—:,()]{0,40})?
    \b
    """,
    re.I | re.U | re.X,
)


_NUMBERED_SEASON_PAREN_RE = re.compile(
    r"""
    (?:
        \s(?P<s>\d{1,3})\s*
        \(
            (?:
                (?:ep(?:isode)?|odc)\.?\s*\d{1,4}
                (?:\s*[,/&]\s*\d{1,4})*
                |
                \d{1,2}(?:\s*[,/&]\s*\d{1,2})*
            )
        \)

      |
        \s(?P<sr>
    """
    + _ROMAN_NUM
    + r"""
        )\s*
        \(
            (?:
                (?:ep(?:isode)?|odc)\.?\s*
            )?
            \d{1,4}
            (?:\s*[,/&]\s*\d{1,4})*
        \)
    )
    """,
    re.I | re.U | re.X,
)


_PAREN_SLASH_EPISODE_RE = re.compile(
    r"\s*\(\s*\d+\s*/\s*\d+\s*\)\s*$",
    re.I | re.U,
)


_TRAILING_EPISODE_PAREN_RE = re.compile(
    r"""
    \s*
    \(
        (?!
            (?:19\d{2}|20[0-4]\d)
            \s*\)
        )
        \d{1,4}
    \)
    \s*$
    """,
    re.I | re.U | re.X,
)


_DASH_SINGLE_EPISODE_RE = re.compile(
    r"\s*[-–—]\s*(\d{1,3})\s*$",
    re.I | re.U,
)


_SEASON_EPISODE_DASH_RE = re.compile(
    r"""
    (?:^|\s)
    (?P<s>\d{1,3})
    \s*[-–—]\s*
    (?:
        (?:ep(?:isode)?|odc)\.?\s*
    )?
    (?P<e>\d{1,4})
    \s*$
    """,
    re.I | re.U | re.X,
)


_TRAILING_BARE_MARKER_RE = re.compile(
    r"""
    \s*[-–—:]\s*
    (?:
        ep(?:isode)?
        |
        odc(?:inek)?
        |
        part
        |
        folge
        |
        episodio
        |
        puntata
    )
    \.?\s*$
    """,
    re.I | re.U | re.X,
)


_CONTENT_FLAG_RE = re.compile(
    r"""
    \s*
    \(
        \s*
        (?:NEW|REPEAT|HD|UHD|\+\d+)
        \s*
    \)
    \s*
    """,
    re.I | re.U | re.X,
)


_TRAILING_FILM_RE = re.compile(
    r"""
    \s*,\s*
    \b
    (?:
        film|movie|talk-show|serija|
        dokumentarni|dokumentar|
        pillole|galeria|promo|promocyjny|trailer|
        PrimaTv|Prima\s*TV|RaiCultura\.it|Pickbox|AXN|Sky|
        Canal\+|HBO|tv\s*film|film\s*tv|
        مسلسل|برنامج
    )
    \s*$
    """,
    re.I | re.U | re.X,
)


_JUNK_WORDS_RE = re.compile(
    r"""
    (?<!\w)
    (?:
        hd|fhd|sd|1080p|720p|576p|1440p|2160p|4k|uhd|webrip|web-dl|
        hdtv|bluray|brrip|hdr|hdr10|dolby|atmos|aac|ac3|eac3|5\.1|
        x265|x264|h264|h265|hevc|avc|
        lektor|napisy|dubbing|vf|vostfr|sub|
        primatv|prima\s*tv|pickbox|axn|canal\+|
        raicultura\.it|rai\s+news|tg1|tg2|tg3|tg4|tg5|
        promo|promocyjny|trailer|show\s+reel|showreel|coming\s+soon|
        zapowiedzi|wkrótce|telezakupy|teleshopping|
        blok\s+promocyjny|powtórki|rediffusion|redif|
        wiederholung|wdh|
        مسلسل|برنامج|حلقة|جزء|
        ح\s*\d+|ج\s*\d+
    )
    (?!\w)
    """,
    re.I | re.U | re.X,
)


_NOISE_PHRASE_RE = re.compile(
    r"حلقة\s+مجمعة",
    re.I | re.U,
)


_YEAR_RE = re.compile(
    r"(?<!\d)(?:19\d{2}|20[0-4]\d)(?!\d)"
)


_BRACKET_YEAR_RE = re.compile(
    r"[\[(]\s*((?:19|20)\d{2})\s*[\])]"
)


def _separator_normalize(text):
    text = to_text(text).replace("_", " ")
    text = re.sub(r"[|\\]+", " ", text)
    text = re.sub(r"\s*[–—]\s*", " - ", text)
    return text

# ---------------------------------------------------------------------------
# Search preparation
# ---------------------------------------------------------------------------
# The EPG value is not "cleaned" into a new title.  It is decomposed into
# identity and context blocks so TMDB receives the strongest identity text.
_EP_MARKER_RE = re.compile(
    r"(?<!\w)(?:episode|episod|ep|odcinek|odc|folge|teil|episodio|"
    r"capitulo|capítulo|chapitre|bölüm|bolum|puntata|epsiode|حلقة|ح)"
    r"\.?\s*#?\s*(\d{1,4})(?:\s*[,/&]\s*(\d{1,4}))?",
    re.I | re.U,
)
_PART_MARKER_RE = re.compile(
    r"(?<!\w)(?:part|parte|جزء)\.?\s*#?\s*(\d{1,3})\b",
    re.I | re.U,
)
_SEASON_WORD_RE = re.compile(
    r"(?<!\w)(?:season|saison|serie|series|stagione|temporada|sezon|"
    r"musim|musi(?:mi)?|موسم)\s*[:.]?\s*(\d{1,3}|" + _ROMAN_NUM + r")\b",
    re.I | re.U,
)
_S_ROMAN_RE = re.compile(r"(?<!\w)S\s*(\d{1,3}|" + _ROMAN_NUM + r")\b", re.I | re.U)
_AR_SEASON_BLOCK_RE = re.compile(r"(?<!\w)(?:ج|جزء)\s*(\d{1,3})\b", re.I | re.U)
_SEASON_EP_DASH_BLOCK_RE = re.compile(
    r"(?<!\w)(?P<s>\d{1,3}|" + _ROMAN_NUM + r")\s*-\s*(?:ep(?:isode)?|odc)\.?\s*(?P<e>\d{1,4})\b",
    re.I | re.U,
)
_NUM_SEASON_BEFORE_EP_RE = re.compile(
    r"(?<!\w)(\d{1,3})\s*[,.:\-]\s*(?=(?:ep(?:isode)?|odc)\.?\s*\d)",
    re.I | re.U,
)
_ROMAN_SEASON_PAREN_EP_RE = re.compile(
    r"(?<!\w)(?P<s>" + _ROMAN_NUM + r")\s*\(\s*(?:ep(?:isode)?|odc)\.?\s*(?P<e>\d{1,4})\s*\)",
    re.I | re.U,
)
_ROMAN_SEASON_PAREN_NUM_RE = re.compile(
    r"(?<!\w)(" + _ROMAN_NUM + r")\s*\(\s*\d{1,4}\s*\)",
    re.I | re.U,
)
_NUM_SEASON_PAREN_NUM_RE = re.compile(
    r"(?<!\w)(?P<s>\d{1,3})\s*\(\s*(?:ep(?:isode)?|odc)\.?\s*(?P<e>\d{1,4})\s*\)",
    re.I | re.U,
)
_TRAILING_EP_PAREN_RE = re.compile(r"\s*\(\s*(?:ep(?:isode)?|odc)\.?\s*\d{1,4}\s*\)\s*$", re.I | re.U)
_NUM_SEASON_COMMA_EP_RE = re.compile(
    r"(?<!\w)(\d{1,3})\s*,\s*(?=(?:ep(?:isode)?|odc)\.?\s*\d)", re.I | re.U
)
_DASH_EP_TITLE_RE = re.compile(r"\s+-\s+(\d{1,3})\s*[.:]\s+(.+)$", re.I | re.U)

# Common EPG form: "Series 27 - 1" = season 27, episode 1.
# Kept deliberately narrow: 1-2 digit season + 1-3 digit episode, with
# a real title before it. This does not touch titles such as "The 100".
_SEASON_EP_TRAILING_RE = re.compile(
    r"(?<!\w)(?P<s>\d{1,2})\s*[-–—]\s*(?P<e>\d{1,3})\s*$",
    re.I | re.U,
)

# Leading season form: "4 Title - Ep. 4". Only considered when an
# explicit episode marker is also present, so ordinary numbered titles stay.
_LEADING_SEASON_EP_RE = re.compile(
    r"^(?P<s>\d{1,2})\s+(?P<title>.+?)\s+-\s+(?:episode|episod|epsiode|ep|odcinek|odc|folge|teil|episodio|capitulo|capítulo|chapitre|bölüm|bolum|puntata)\.?\s*#?\s*(?P<e>\d{1,4})\b",
    re.I | re.U,
)

_DANGLING_EP_MARKER_RE = re.compile(
    r"\s+(?:episode|episod|epsiode|ep|odcinek|odc|folge|teil|episodio|capitulo|capítulo|chapitre|bölüm|bolum|puntata|part|parte|pt|p|حلقة|ح|جزء)\.?\s*$",
    re.I | re.U,
)


def _block_cleanup(text):
    text = _normalize_title_text(text)
    text = _normalize_digits(text)
    text = _separator_normalize(text)
    text = _CONTENT_FLAG_RE.sub(" ", text)
    text = _NOISE_PHRASE_RE.sub(" ", text)
    text = _JUNK_WORDS_RE.sub(" ", text)
    for _ in range(3):
        cleaned = _TRAILING_FILM_RE.sub(" ", text).strip()
        if cleaned == text:
            break
        text = cleaned
    return _SPACE_RE.sub(" ", text).strip()


def _search_identity_text(text):
    text = _block_cleanup(text)
    # Keep meaningful punctuation.  Only normalize spacing around structural
    # punctuation; TMDB can use the resulting natural title as its query.
    text = re.sub(r"\s*([:/!?])\s*", r"\1 ", text)
    text = re.sub(r"\s*&\s*", " & ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s*\(\s*", " (", text)
    text = re.sub(r"\s*\)\s*", ") ", text)
    text = re.sub(r"\s+-\s+", " - ", text)
    return _SPACE_RE.sub(" ", text).strip(" -,:;.")


def _remove_span(text, match):
    return (text[:match.start()] + " " + text[match.end():]).strip()


def prepare_search_title(raw):
    original = _normalize_digits(_separator_normalize(_normalize_title_text(raw)))
    if not original:
        return {
            "raw": "", "identity": "", "secondary_title": "",
            "season": None, "part": None, "episode": None, "episode_title": "",
            "year": "", "auxiliary": [], "blocks": []
        }
    text = original
    blocks = []
    season = None
    part = None
    episode = None
    episode_title = ""
    year = ""
    auxiliary = []

    def add(kind, value):
        value = _SPACE_RE.sub(" ", to_text(value)).strip()
        if value:
            blocks.append((kind, value))

    # Year is context, not identity.  Preserve it only as metadata.
    ym = _BRACKET_YEAR_RE.search(text)
    if ym:
        year = ym.group(1)
        add("YEAR", year)
        text = _remove_span(text, ym)
    else:
        ym = re.search(r"(?:^|[ ,(/-])((?:19|20)\d{2})(?=$|[ ,)/-])", text)
        if ym:
            year = ym.group(1)
            add("YEAR", year)
            text = _remove_span(text, ym)

    # Compact season/episode forms are very common in EPG feeds: S01E02,
    # S1EP2, 1x02 and their Roman-number equivalent.  The original file already
    # defined the structural regexes but the main parser did not execute them.
    compact = _EPISODE_RE.search(text)
    if compact:
        groups = compact.groupdict()
        season_value = (groups.get("s1") or groups.get("s2") or
                        groups.get("s3") or groups.get("s4"))
        episode_value = (groups.get("e1") or groups.get("e2") or groups.get("e3"))
        if season_value:
            season = _number_value(season_value)
            add("SEASON", season_value)
        if episode_value:
            episode = int(episode_value)
            add("EPISODE", episode_value)
        text = _remove_span(text, compact)

    if season is None:
        roman_compact = _ROMAN_EPISODE_RE.search(text)
        if roman_compact:
            season = _number_value(roman_compact.group("s"))
            episode = _number_value(roman_compact.group("e"))
            add("SEASON", roman_compact.group("s"))
            add("EPISODE", roman_compact.group("e"))
            text = _remove_span(text, roman_compact)

    # Leading season + explicit episode: "4 Title - Ep. 4".
    lm = _LEADING_SEASON_EP_RE.search(text)
    if lm:
        season = int(lm.group("s"))
        episode = int(lm.group("e"))
        add("SEASON", lm.group("s"))
        add("EPISODE", lm.group("e"))
        text = lm.group("title")

    # Explicit season + episode forms have the highest structural confidence.
    m = None if season is not None else _SEASON_EP_DASH_BLOCK_RE.search(text)
    if m:
        season = _number_value(m.group("s"))
        episode = int(m.group("e"))
        add("SEASON", m.group("s"))
        add("EPISODE", m.group("e"))
        text = _remove_span(text, m)

    # A written season marker must be handled before the weaker numeric-before-
    # episode fallback. Otherwise "One Love Season 4 - Ep.404" becomes
    # "One Love Season" after only the numeral is removed.
    if season is None:
        m = _SEASON_WORD_RE.search(text)
        if m:
            season = _number_value(m.group(1))
            add("SEASON", m.group(1))
            text = _remove_span(text, m)

    if season is None:
        m = _NUM_SEASON_BEFORE_EP_RE.search(text)
        if not m:
            m = _NUM_SEASON_COMMA_EP_RE.search(text)
        if m:
            season = _number_value(m.group(1))
            add("SEASON", m.group(1))
            text = _remove_span(text, m)

    if season is None:
        m = _AR_SEASON_BLOCK_RE.search(text)
        if m:
            season = int(m.group(1))
            add("SEASON", m.group(1))
            text = _remove_span(text, m)

    # Roman/numeric season immediately before an episode parenthesis.
    if season is None:
        m = _ROMAN_SEASON_PAREN_EP_RE.search(text)
        if m:
            season = _number_value(m.group("s"))
            episode = int(m.group("e"))
            add("SEASON", m.group("s"))
            add("EPISODE", m.group("e"))
            text = _remove_span(text, m)
        else:
            m = _ROMAN_SEASON_PAREN_NUM_RE.search(text)
            if m:
                season = _number_value(m.group(1))
                pm = re.search(r"\(\s*(\d{1,4})\s*\)", text[m.start():])
                episode = int(pm.group(1)) if pm else None
                add("SEASON", m.group(1))
                if episode is not None:
                    add("EPISODE", str(episode))
                text = _remove_span(text, m)
            else:
                m = _NUM_SEASON_PAREN_NUM_RE.search(text)
                if m:
                    season = int(m.group("s"))
                    episode = int(m.group("e"))
                    add("SEASON", m.group("s"))
                    add("EPISODE", m.group("e"))
                    text = _remove_span(text, m)

    # S2 / S II is an identity-adjacent context block.
    if season is None:
        m = _S_ROMAN_RE.search(text)
        if m:
            season = _number_value(m.group(1))
            add("SEASON", m.group(1))
            text = _remove_span(text, m)

    # Part is context, not an episode/TV signal. Keep it out of the search
    # identity, but retain the number for optional result interpretation.
    pm_part = _PART_MARKER_RE.search(text)
    if pm_part:
        part = int(pm_part.group(1))
        add("PART", pm_part.group(1))
        text = _remove_span(text, pm_part)

    # Episode marker.  The text after the marker is an episode title, not part
    # of the series identity.  Do this after season/part extraction.
    em = _EP_MARKER_RE.search(text)
    if em:
        episode = int(em.group(1))
        add("EPISODE", em.group(1))
        prefix = text[:em.start()].strip()
        tail = text[em.end():].strip(" .:-,/")
        if tail:
            episode_title = _block_cleanup(tail)
            if episode_title:
                add("EPISODE_TITLE", episode_title)
        else:
            # Many EPG providers put the episode name before the marker:
            #   Series Name - Episode Name ep.7
            # Keep the real series identity separate from that episode name.
            sep = re.search(r"\s+-\s+", prefix)
            if sep:
                left = prefix[:sep.start()].strip(" -,:;.")
                right = prefix[sep.end():].strip(" -,:;.")
                if len(left) >= 2 and len(right) >= 3:
                    episode_title = _block_cleanup(right)
                    if episode_title:
                        add("EPISODE_TITLE", episode_title)
                        prefix = left
        text = prefix
    else:
        had_dangling_ep = bool(_DANGLING_EP_MARKER_RE.search(text))
        text = _DANGLING_EP_MARKER_RE.sub(" ", text).strip()
        if had_dangling_ep:
            # Some feeds publish a dangling EP marker after an episode title:
            #   Grand Hotel - All Secrets Stay Here - Ep
            # Treat the final hyphen block as episode context, not series name.
            sep = re.search(r"\s+-\s+", text)
            if sep:
                left = text[:sep.start()].strip(" -,:;.")
                right = text[sep.end():].strip(" -,:;.")
                if len(left) >= 2 and len(right) >= 3:
                    episode_title = _block_cleanup(right)
                    if episode_title:
                        add("EPISODE_TITLE", episode_title)
                        text = left
        # Vzpomínky I (13), Odpadlík V (9), etc. The parenthesized number is
        # an episode only when a season numeral immediately precedes it.
        pm = re.search(r"\(\s*(\d{1,4})\s*\)\s*$", text)
        if pm:
            before = text[:pm.start()].rstrip()
            sm = re.search(r"(?:^|\s)(" + _ROMAN_NUM + r")\s*$", before, re.I | re.U)
            if sm:
                season = _number_value(sm.group(1))
                episode = int(pm.group(1))
                add("SEASON", sm.group(1))
                add("EPISODE", pm.group(1))
                text = before[:sm.start()].strip()
            else:
                # Bare trailing (13) is intentionally retained; it may be
                # part of a title or a non-season parenthetical.
                pass

    # Numeric season followed by an explicit episode may have been left in
    # forms such as "Title 13, ep. 12" after marker removal.
    if season is None:
        m = re.search(r"(?:^|\s)(\d{1,3})\s*(?=,?\s*(?:ep(?:isode)?|odc)\.?\s*\d)", text, re.I | re.U)
        if m:
            season = int(m.group(1))
            add("SEASON", m.group(1))
            text = _remove_span(text, m)
            em = _EP_MARKER_RE.search(text)
            if em:
                episode = int(em.group(1))
                add("EPISODE", em.group(1))
                tail = text[em.end():].strip(" .:-,/")
                if tail:
                    episode_title = _block_cleanup(tail)
                    add("EPISODE_TITLE", episode_title)
                text = text[:em.start()]

    # Common season/episode EPG form: "Title 27 - 1".  Treat the two
    # trailing numbers as context only when both sides are numeric and there
    # is a meaningful title before them.
    if season is None and episode is None:
        sm = _SEASON_EP_TRAILING_RE.search(text)
        if sm and len(text[:sm.start()].strip()) >= 3:
            season = int(sm.group("s"))
            episode = int(sm.group("e"))
            add("SEASON", sm.group("s"))
            add("EPISODE", sm.group("e"))
            text = text[:sm.start()]

    # Episode-only dash form: title - 4. Episode Name.  The number is an
    # instance block, while the text after it is episode title.
    if episode is None:
        dm = _DASH_EP_TITLE_RE.search(text)
        if dm:
            try:
                n = int(dm.group(1))
            except Exception:
                n = 0
            if 0 < n <= 999:
                episode = n
                add("EPISODE", dm.group(1))
                episode_title = _block_cleanup(dm.group(2))
                if episode_title:
                    add("EPISODE_TITLE", episode_title)
                text = text[:dm.start()]

    # Cleanup left behind by an explicit season marker, e.g.
    # "One Love Season 4 - Ep.404".  Only remove the standalone marker word;
    # never remove arbitrary words that merely resemble a season label.
    text = re.sub(r"(?i)(?:^|\s)(?:season|saison|stagione|temporada|sezon|musim)(?:\s*$)", " ", text)
    text = _block_cleanup(text)
    identity = _search_identity_text(text)
    if not identity:
        identity = _search_identity_text(original)

    # Remove only well-known broadcast suffixes from auxiliary text; unknown
    # text is retained as identity rather than guessed away.
    secondary_title = ""
    if ":" in identity:
        head, tail = identity.split(":", 1)
        head = head.strip(" -,:;.")
        tail = tail.strip(" -,:;.")
        if head and tail and len(head) > 1 and len(tail) > 1:
            secondary_title = tail

    if identity:
        add("IDENTITY", identity)
    return {
        "raw": original,
        "identity": identity,
        "secondary_title": secondary_title,
        "season": season,
        "part": part,
        "episode": episode,
        "episode_title": episode_title,
        "year": year,
        "auxiliary": auxiliary,
        "blocks": blocks,
    }


def _extract_season(text):
    profile = prepare_search_title(text)
    identity = profile.get("identity") or _block_cleanup(text)
    return profile.get("season"), identity


def _episode_program_prefix(original):
    return prepare_search_title(original).get("identity", "")


def _clean_candidate(candidate):
    return _search_identity_text(candidate)


def _dedupe_candidates(candidates, limit=4):
    result = []
    seen = set()
    for candidate in candidates:
        candidate = _search_identity_text(candidate)
        key = candidate.casefold()
        if candidate and len(candidate) > 2 and key not in seen:
            seen.add(key)
            result.append(candidate)
            if len(result) >= limit:
                break
    return result


def simple_clean_title(raw):
    """Return the canonical program identity only.

    Season, part and episode numbers are metadata/context. They should not be
    manufactured into alternate title queries because doing so can turn a
    correct program identity into a different search string. The downloader
    receives the structured season/episode values separately.
    """
    profile = prepare_search_title(raw)
    identity = profile.get("identity") or ""
    if not identity:
        return []
    return [identity]


# ============================================================================
# ANALYZE CACHE
# ============================================================================

_ANALYZE_CACHE_MAX = 1200

_analyze_cache = OrderedDict()
_analyze_cache_lock = threading.RLock()
_analyze_profile_cache = OrderedDict()


@traced("iConverlibr")
def analyze_epg_title(raw):
    raw = to_text(raw)

    if not raw:
        return (
            True,
            "",
            [],
        )

    with _analyze_cache_lock:
        cached = _analyze_cache.get(raw)

        if cached is not None:
            _analyze_cache.move_to_end(raw)
            return cached

    try:
        if (
            _is_no_info(raw)
            or _is_skip_event(raw)
        ):
            result = (
                True,
                "",
                [],
            )
        else:
            profile = prepare_search_title(raw)
            with _analyze_cache_lock:
                _analyze_profile_cache[raw] = profile
                _analyze_profile_cache.move_to_end(raw)

            identity = profile.get("identity") or ""
            # One canonical search identity. Season/year/episode are context,
            # not alternate TMDB queries. Keep the compatibility list, but do
            # not manufacture ranked title variants here.
            candidates = [identity] if identity else []
            clean = identity

            if not clean:
                result = (
                    True,
                    "",
                    [],
                )
            else:
                result = (
                    False,
                    clean,
                    candidates[:4],
                )

    except Exception as exc:
        warn(
            "iConverlibr",
            "title-analysis-EX",
            "%s: %s"
            % (
                type(exc).__name__,
                exc,
            ),
        )

        result = (
            True,
            "",
            [],
        )

    with _analyze_cache_lock:
        _analyze_cache[raw] = result
        _analyze_cache.move_to_end(raw)

        while (
            len(_analyze_cache)
            > _ANALYZE_CACHE_MAX
        ):
            _analyze_cache.popitem(
                last=False
            )

    return result


def get_epg_title_profile(raw):
    """Return structured EPG data without running the cleaner twice."""
    raw = to_text(raw)
    if not raw:
        return {
            "raw": "", "identity": "", "secondary_title": "",
            "season": None, "part": None, "episode": None, "episode_title": "",
            "year": "", "auxiliary": [], "blocks": []
        }

    with _analyze_cache_lock:
        cached_profile = _analyze_profile_cache.get(raw)
        if cached_profile is not None:
            return cached_profile

    try:
        profile = prepare_search_title(raw)
    except Exception as exc:
        warn("iConverlibr", "title-profile-EX", "%s: %s" % (type(exc).__name__, exc))
        profile = {
            "raw": raw, "identity": "", "secondary_title": "",
            "season": None, "part": None, "episode": None, "episode_title": "",
            "year": "", "auxiliary": [], "blocks": []
        }

    with _analyze_cache_lock:
        _analyze_profile_cache[raw] = profile
        _analyze_profile_cache.move_to_end(raw)
        while len(_analyze_profile_cache) > _ANALYZE_CACHE_MAX:
            _analyze_profile_cache.popitem(last=False)
    return profile

def convtext(text=u""):
    if not text:
        return ""

    text = to_text(text)

    with _analyze_cache_lock:
        cached = _analyze_cache.get(text)

        if cached is not None:
            _analyze_cache.move_to_end(text)
            return cached[1]

    return analyze_epg_title(
        text
    )[1]


# ============================================================================
# EPG METADATA
# ============================================================================

def extract_epg_hints(description):
    match = _YEAR_RE.search(
        _normalize_title_text(
            description
        )
    )

    return (
        {"year": match.group(0)}
        if match
        else {}
    )


def _format_genres(genres_string):
    if not genres_string:
        return ""

    return " • ".join(
        part.strip()
        for part in to_text(
            genres_string
        ).split(",")
        if part.strip()
    )


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

    rtl_count = len(
        _RTL_RE.findall(sample)
    )

    if (
        rtl_count
        <= len(sample) * 0.25
    ):
        return text

    try:
        chars_per_line = max(
            1,
            int(chars_per_line),
        )
    except Exception:
        chars_per_line = (
            _DEFAULT_OVERVIEW_CHARS_PER_LINE
        )

    lines = []
    line = []
    length = 0

    for word in text.split():
        n = len(word)

        proposed = (
            length
            + n
            + (1 if line else 0)
        )

        if (
            line
            and proposed > chars_per_line
        ):
            lines.append(
                " ".join(line)
            )

            line = [word]
            length = n
        else:
            line.append(word)
            length = proposed

    if line:
        lines.append(
            " ".join(line)
        )

    return "\n".join(lines)


def format_overview(
    text,
    chars_per_line=None,
):
    if (
        not text
        or not get_cfg(
            "RTL_OVERVIEW"
        )
    ):
        return text

    if chars_per_line is None:
        chars_per_line = (
            _DEFAULT_OVERVIEW_CHARS_PER_LINE
        )

    try:
        chars_per_line = max(
            1,
            int(chars_per_line),
        )
    except Exception:
        chars_per_line = (
            _DEFAULT_OVERVIEW_CHARS_PER_LINE
        )

    return cached_format_overview(
        to_text(text),
        chars_per_line,
    )


def has_useful_metadata(data):
    if not isinstance(data, dict):
        return False

    try:
        rating = float(
            data.get(
                "vote_average",
                0,
            )
            or 0
        )
    except Exception:
        rating = 0

    overview = to_text(
        data.get(
            "overview",
            "",
        )
        or ""
    )

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
    data = (
        data
        if isinstance(data, dict)
        else {}
    )

    try:
        rating = float(
            data.get(
                "vote_average",
                0,
            )
            or 0
        )
    except Exception:
        rating = 0

    overview = to_text(
        data.get(
            "overview",
            "",
        )
        or ""
    )

    formatted = format_overview(
        overview
    )

    parental = to_text(
        data.get(
            "parental_rating",
            "",
        )
        or ""
    )

    return {
        "rating": rating,
        "parental": parental,
        "genres": _format_genres(
            data.get(
                "genres",
                "",
            )
        ),
        "year": data.get(
            "year",
            "",
        ),
        "overview": formatted,
        "plot": formatted,
        "title": to_text(
            data.get(
                "title",
                "",
            )
            or ""
        ),
        "country": to_text(
            data.get(
                "country",
                "",
            )
            or ""
        ),
        "director": to_text(
            data.get(
                "director",
                "",
            )
            or ""
        ),
        "cast": to_text(
            data.get(
                "cast",
                "",
            )
            or ""
        ),
        "rated": parental,
        "imdb": (
            str(rating)
            if rating > 0
            else ""
        ),
        "metadata_resolved": True,
    }


# ============================================================================
# ASSET CACHE
# ============================================================================

_ASSET_EXISTS_CACHE_MAX = 1500
_ASSET_EXISTS_CACHE_TTL = 1.5

_asset_exists_cache = OrderedDict()
_asset_exists_lock = threading.RLock()


def _clear_asset_cache():
    with _asset_exists_lock:
        _asset_exists_cache.clear()


def file_exists_indexed(
    folder,
    filename,
):
    if not folder or not filename:
        return False

    key = (
        str(folder),
        str(filename),
    )

    now = time.monotonic()

    with _asset_exists_lock:
        entry = _asset_exists_cache.get(
            key
        )

        if entry is not None:
            timestamp, exists = entry

            if (
                now - timestamp
                <= _ASSET_EXISTS_CACHE_TTL
            ):
                _asset_exists_cache.move_to_end(
                    key
                )
                return exists

            del _asset_exists_cache[key]

    try:
        exists = os.path.isfile(
            os.path.join(
                folder,
                filename,
            )
        )
    except Exception:
        exists = False

    with _asset_exists_lock:
        _asset_exists_cache[key] = (
            now,
            exists,
        )

        _asset_exists_cache.move_to_end(
            key
        )

        while (
            len(_asset_exists_cache)
            > _ASSET_EXISTS_CACHE_MAX
        ):
            _asset_exists_cache.popitem(
                last=False
            )

    return exists


def mark_file_indexed(
    folder,
    filename,
):
    if not folder or not filename:
        return

    try:
        exists = os.path.isfile(
            os.path.join(
                folder,
                filename,
            )
        )
    except Exception:
        exists = False

    key = (
        str(folder),
        str(filename),
    )

    with _asset_exists_lock:
        _asset_exists_cache[key] = (
            time.monotonic(),
            exists,
        )

        _asset_exists_cache.move_to_end(
            key
        )

        while (
            len(_asset_exists_cache)
            > _ASSET_EXISTS_CACHE_MAX
        ):
            _asset_exists_cache.popitem(
                last=False
            )


def unmark_file_indexed(
    folder,
    filename,
):
    if folder and filename:
        with _asset_exists_lock:
            _asset_exists_cache.pop(
                (
                    str(folder),
                    str(filename),
                ),
                None,
            )


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

    title = to_text(
        clean_title
    ).strip()

    if not title:
        return result

    checks = (
        (
            want_poster,
            get_poster_folder,
            ".jpg",
            "local_path",
        ),
        (
            want_backdrop,
            get_backdrop_folder,
            ".jpg",
            "backdrop_path",
        ),
        (
            want_logo,
            get_logo_folder,
            ".png",
            "logo_path",
        ),
    )

    for enabled, folder_fn, ext, key in checks:
        if not enabled:
            continue

        try:
            folder = folder_fn()

            filename = (
                title + ext
            )

            if file_exists_indexed(
                folder,
                filename,
            ):
                result[key] = os.path.join(
                    folder,
                    filename,
                )

        except Exception:
            pass

    return result


# ============================================================================
# SQLITE STATE STORE
# ============================================================================

class StateStore(object):
    CACHE_MAX = 1200

    def __init__(self, emc_mode):
        self.emc_mode = bool(
            emc_mode
        )

        self.table = (
            "emc"
            if self.emc_mode
            else "epg"
        )

        self._conn = None
        self._db_path = None
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._closed = False

        self._connect()

        try:
            atexit.register(
                self.close
            )
        except Exception:
            pass

    def _connect(self):
        path = get_metadata_db_path()

        if (
            self._conn is not None
            and self._db_path == path
        ):
            try:
                self._conn.execute(
                    "SELECT 1"
                )
                self._closed = False
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

            self._conn = None

        parent = os.path.dirname(path)

        if parent:
            _ensure_dir(parent)

        self._db_path = path

        conn = sqlite3.connect(
            path,
            timeout=10,
            check_same_thread=False,
            cached_statements=128,
        )

        pragmas = (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-2048",
            "PRAGMA busy_timeout=10000",
        )

        for pragma in pragmas:
            try:
                conn.execute(
                    pragma
                )
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
            """
            % self.table
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
        value = self._cache.get(
            title
        )

        if value is not None:
            self._cache.move_to_end(
                title
            )

        return value

    def _cache_put(self, title, value):
        self._cache[title] = value
        self._cache.move_to_end(
            title
        )

        while (
            len(self._cache)
            > self.CACHE_MAX
        ):
            self._cache.popitem(
                last=False
            )

    @staticmethod
    def _decode_row(row):
        if not row:
            return None

        status, data_json, last_scan = row

        try:
            data = (
                json.loads(data_json)
                if data_json
                else {}
            )

            if not isinstance(
                data,
                dict,
            ):
                data = {}

        except Exception:
            data = {}

        try:
            last_scan = int(
                last_scan or 0
            )
        except Exception:
            last_scan = 0

        return {
            "status": status or "",
            "data": data,
            "last_scan": last_scan,
        }

    def get(self, title):
        title = to_text(
            title
        ).strip()

        if not title:
            return None

        with self._lock:
            cached = self._cache_get(
                title
            )

            if cached is False:
                return None

            if cached is not None:
                return cached

            for attempt in range(2):
                try:
                    conn = self._connect()

                    row = conn.execute(
                        """
                        SELECT status,data,last_scan
                        FROM %s
                        WHERE title=?
                        """
                        % self.table,
                        (title,),
                    ).fetchone()

                    result = self._decode_row(
                        row
                    )

                    self._cache_put(
                        title,
                        (
                            result
                            if result is not None
                            else False
                        ),
                    )

                    return result

                except (
                    sqlite3.Error,
                    IOError,
                    OSError,
                ) as exc:

                    if attempt == 0:
                        try:
                            if self._conn:
                                self._conn.close()
                        except Exception:
                            pass

                        self._conn = None

                    else:
                        warn(
                            "iConverlibr",
                            "sqlite-get-EX",
                            str(exc),
                        )

                except Exception as exc:
                    warn(
                        "iConverlibr",
                        "sqlite-get-EX",
                        str(exc),
                    )
                    break

        return None

    def get_many(self, titles):
        if not titles:
            return {}

        unique = []
        seen = set()

        for title in titles:
            title = to_text(
                title
            ).strip()

            if (
                title
                and title not in seen
            ):
                seen.add(title)
                unique.append(title)

        if not unique:
            return {}

        result = {}
        missing = []

        with self._lock:
            for title in unique:
                cached = self._cache_get(
                    title
                )

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

                # 80 is intentionally conservative for old
                # SQLite builds and SQLite variable limits.
                for offset in range(
                    0,
                    len(missing),
                    80,
                ):
                    chunk = missing[
                        offset:offset + 80
                    ]

                    placeholders = ",".join(
                        "?"
                        for _ in chunk
                    )

                    rows = conn.execute(
                        """
                        SELECT title,status,data,last_scan
                        FROM %s
                        WHERE title IN (%s)
                        """
                        % (
                            self.table,
                            placeholders,
                        ),
                        tuple(chunk),
                    ).fetchall()

                    for (
                        title,
                        status,
                        data_json,
                        last_scan,
                    ) in rows:

                        value = self._decode_row(
                            (
                                status,
                                data_json,
                                last_scan,
                            )
                        )

                        if value is not None:
                            result[title] = value

                            self._cache_put(
                                title,
                                value,
                            )

                for title in missing:
                    if title not in result:
                        self._cache_put(
                            title,
                            False,
                        )

            except Exception as exc:
                warn(
                    "iConverlibr",
                    "sqlite-get-many-EX",
                    str(exc),
                )

        return result

    def get_data(self, title):
        record = self.get(title)

        return (
            record["data"]
            if record
            else None
        )

    def is_ok(self, title):
        record = self.get(title)

        return bool(
            record
            and record.get(
                "status"
            ) == "ok"
        )

    def should_search(
        self,
        title,
        still_needed=None,
    ):
        record = self.get(title)

        if record is None:
            return True

        status = record.get(
            "status"
        )

        if status == "ok":
            return bool(
                still_needed
            )

        if status == "failed":
            try:
                age = (
                    time.time()
                    - (
                        record.get(
                            "last_scan",
                            0,
                        )
                        or 0
                    )
                )
            except Exception:
                age = 999999999

            return age > (
                5 * 60
            )

        return True

    def set_record(
        self,
        title,
        status,
        data=None,
    ):
        title = to_text(
            title
        ).strip()

        if not title:
            return

        payload = (
            data
            if isinstance(data, dict)
            else {}
        )

        now = int(
            time.time()
        )

        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
        except Exception:
            encoded = "{}"
            payload = {}

        with self._lock:
            for attempt in range(2):
                try:
                    conn = self._connect()

                    # Atomic upsert (compatible with modern SQLite)
                    conn.execute(
                        """
                        INSERT INTO %s
                            (title,status,data,last_scan)
                        VALUES(?,?,?,?)
                        ON CONFLICT(title) DO UPDATE SET
                            status=excluded.status,
                            data=excluded.data,
                            last_scan=excluded.last_scan
                        """
                        % self.table,
                        (
                            title,
                            status,
                            encoded,
                            now,
                        ),
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

                except sqlite3.OperationalError:
                    # Fallback for older SQLite without ON CONFLICT
                    try:
                        cursor = conn.execute(
                            """
                            UPDATE %s
                            SET status=?,data=?,last_scan=?
                            WHERE title=?
                            """
                            % self.table,
                            (
                                status,
                                encoded,
                                now,
                                title,
                            ),
                        )

                        if cursor.rowcount == 0:
                            conn.execute(
                                """
                                INSERT INTO %s
                                (title,status,data,last_scan)
                                VALUES(?,?,?,?)
                                """
                                % self.table,
                                (
                                    title,
                                    status,
                                    encoded,
                                    now,
                                ),
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

                    except sqlite3.IntegrityError:
                        # Another thread may have inserted the title
                        conn.execute(
                            """
                            UPDATE %s
                            SET status=?,data=?,last_scan=?
                            WHERE title=?
                            """
                            % self.table,
                            (
                                status,
                                encoded,
                                now,
                                title,
                            ),
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

                except (
                    sqlite3.Error,
                    IOError,
                    OSError,
                ) as exc:
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
                        err(
                            "iConverlibr",
                            "sqlite-set-EX",
                            str(exc),
                        )

                except Exception as exc:
                    try:
                        if self._conn:
                            self._conn.rollback()
                    except Exception:
                        pass

                    err(
                        "iConverlibr",
                        "sqlite-set-EX",
                        str(exc),
                    )
                    return

    def mark_not_found(self, title):
        record = self.get(title)

        self.set_record(
            title,
            "failed",
            (
                record["data"]
                if record
                else {}
            ),
        )


_epg_store = StateStore(False)
_emc_store = StateStore(True)


def get_state_store(emc_mode):
    return (
        _emc_store
        if emc_mode
        else _epg_store
    )


# ============================================================================
# EVENT IDENTITY / CALLBACKS
# ============================================================================

_metadata_callbacks = {}
_metadata_callback_lock = threading.RLock()

_ready_queue = []
_ready_queue_lock = threading.RLock()

_gui_dispatcher_timer = eTimer()


def make_event_key(
    begin_time,
    raw_name,
    ep_marker="",
):
    raw_name = clean_name(
        raw_name
    )

    ep_marker = to_text(
        ep_marker
    ).strip()

    begin_time = begin_time or 0

    if ep_marker:
        return "%s-%s-%s" % (
            begin_time,
            raw_name,
            ep_marker,
        )

    return "%s-%s" % (
        begin_time,
        raw_name,
    )


def _make_weak_renderer_ref(renderer):
    try:
        return weakref.ref(
            renderer
        )
    except TypeError:
        return None


def register_metadata_callback(
    clean_title,
    renderer_ref,
    method_name="changed",
    event_key=None,
):
    if (
        not clean_title
        or renderer_ref is None
    ):
        return

    key = (
        event_key
        or clean_title
    )

    weak_renderer = (
        _make_weak_renderer_ref(
            renderer_ref
        )
    )

    if weak_renderer is None:
        return

    with _metadata_callback_lock:
        bucket = _metadata_callbacks.setdefault(
            key,
            [],
        )

        for (
            existing_ref,
            existing_method,
        ) in bucket:

            try:
                if (
                    existing_method
                    == method_name
                    and existing_ref()
                    is renderer_ref
                ):
                    return
            except Exception:
                pass

        bucket.append(
            (
                weak_renderer,
                method_name,
            )
        )


def unregister_metadata_callback(
    clean_title,
    renderer_obj,
    event_key=None,
):
    if (
        not clean_title
        or renderer_obj is None
    ):
        return

    key = (
        event_key
        or clean_title
    )

    with _metadata_callback_lock:
        bucket = _metadata_callbacks.get(
            key
        )

        if not bucket:
            return

        alive = []

        for ref, method_name in bucket:
            try:
                renderer = ref()
            except Exception:
                renderer = None

            if (
                renderer is not None
                and renderer is not renderer_obj
            ):
                alive.append(
                    (
                        ref,
                        method_name,
                    )
                )

        if alive:
            _metadata_callbacks[key] = alive
        else:
            _metadata_callbacks.pop(
                key,
                None,
            )


def notify_metadata_ready(
    clean_title,
    event_key=None,
):
    if not clean_title:
        return

    with _ready_queue_lock:
        _ready_queue.append(
            (
                "meta",
                clean_title,
                event_key,
            )
        )

    _schedule_drain()


def queue_gui_callback(
    callback,
    *args,
):
    if callback is None:
        return

    with _ready_queue_lock:
        _ready_queue.append(
            (
                "call",
                callback,
                args,
            )
        )

    _schedule_drain()


def _schedule_drain():
    try:
        _gui_dispatcher_timer.start(
            0,
            True,
        )
    except Exception:
        pass


def _safe_renderer_changed(
    renderer,
    method_name,
):
    try:
        method = getattr(
            renderer,
            method_name,
            None,
        )

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
            method(
                (
                    changed_default,
                )
            )

    except Exception as exc:
        err(
            "Dispatcher",
            "meta-callback-EX",
            str(exc),
        )


@traced("iConverlibr")
def _drain_ready_queue():
    with _ready_queue_lock:
        if not _ready_queue:
            return

        items = list(
            _ready_queue
        )

        del _ready_queue[:]

    meta_events = set()
    direct_calls = []

    for item in items:
        if not item:
            continue

        if (
            item[0] == "meta"
            and len(item) >= 3
        ):
            meta_events.add(
                (
                    item[1],
                    item[2],
                )
            )

        elif (
            item[0] == "call"
            and len(item) >= 3
        ):
            direct_calls.append(
                (
                    item[1],
                    item[2],
                )
            )

    for clean_title, event_key in meta_events:
        keys = []

        if event_key:
            keys.append(
                event_key
            )

        if clean_title not in keys:
            keys.append(
                clean_title
            )

        callbacks = []

        with _metadata_callback_lock:
            for key in keys:
                callbacks.extend(
                    _metadata_callbacks.get(
                        key,
                        [],
                    )
                )

        for (
            weak_renderer,
            method_name,
        ) in callbacks:

            try:
                renderer = weak_renderer()
            except Exception:
                renderer = None

            if renderer is not None:
                _safe_renderer_changed(
                    renderer,
                    method_name,
                )

    for callback, args in direct_calls:
        try:
            callback(*args)
        except Exception as exc:
            err(
                "Dispatcher",
                "gui-callback-EX",
                str(exc),
            )

    # Clean dead references.
    with _metadata_callback_lock:
        dead = []

        for key, bucket in list(
            _metadata_callbacks.items()
        ):
            alive = []

            for entry in bucket:
                try:
                    renderer = entry[0]()
                except Exception:
                    renderer = None

                if renderer is not None:
                    alive.append(entry)

            if alive:
                _metadata_callbacks[key] = alive
            else:
                dead.append(key)

        for key in dead:
            _metadata_callbacks.pop(
                key,
                None,
            )

    with _ready_queue_lock:
        more = bool(
            _ready_queue
        )

    if more:
        _schedule_drain()


try:
    _gui_dispatcher_timer.callback.append(
        _drain_ready_queue
    )
except Exception as exc:
    err(
        "Dispatcher",
        "timer-init-EX",
        str(exc),
    )


# ============================================================================
# MEDIA / SERVICE
# ============================================================================

_VIDEO_EXTS = (
    ".mkv",
    ".avi",
    ".mp4",
    ".ts",
    ".mov",
    ".iso",
    ".m2ts",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".wmv",
)


def is_video_file(path):
    if not path:
        return False

    try:
        return str(path).lower().endswith(
            _VIDEO_EXTS
        )
    except Exception:
        return False


def _navigation_service_ref():
    try:
        nav = NavigationInstance.instance

        if not nav:
            return None

        return (
            nav.getCurrentlyPlayingServiceReference()
        )

    except Exception:
        return None


def get_service_ref(source):
    if source is None:
        return None

    # eServiceReference-like object.
    try:
        if (
            hasattr(
                source,
                "toString",
            )
            and not hasattr(
                source,
                "getCurrentService",
            )
        ):
            return source
    except Exception:
        pass

    # CurrentService-like source.
    try:
        getter = getattr(
            source,
            "getCurrentService",
            None,
        )

        if callable(getter):
            service = getter()

            if service is not None:
                if hasattr(
                    service,
                    "toString",
                ):
                    return service

                ref_getter = getattr(
                    service,
                    "getCurrentServiceRef",
                    None,
                )

                if callable(ref_getter):
                    ref = ref_getter()

                    if ref is not None:
                        return ref

    except Exception:
        pass

    if isinstance(
        source,
        CurrentService,
    ):
        try:
            return source.getCurrentServiceRef()
        except Exception:
            pass

    if isinstance(
        source,
        (
            EventInfo,
            Event,
        ),
    ):
        return _navigation_service_ref()

    if isinstance(
        source,
        ServiceEvent,
    ):
        try:
            return source.getCurrentService()
        except Exception:
            pass

    if source.__class__.__name__ in (
        "EMCServiceEvent",
        "Service",
    ):
        try:
            service = getattr(
                source,
                "service",
                None,
            )

            if service is not None:
                return service

        except Exception:
            pass

    return _navigation_service_ref()


def get_movie_path(source):
    if source is None:
        return None

    objects = (
        source,
        getattr(
            source,
            "service",
            None,
        ),
    )

    for obj in objects:
        if obj is None:
            continue

        try:
            getter = getattr(
                obj,
                "getPath",
                None,
            )

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

            if service:
                getter = getattr(
                    service,
                    "getPath",
                    None,
                )

                if callable(getter):
                    path = getter()

                    if path:
                        return path

    except Exception:
        pass

    if isinstance(
        source,
        ServiceEvent,
    ):
        try:
            service = source.getCurrentService()

            getter = (
                getattr(
                    service,
                    "getPath",
                    None,
                )
                if service
                else None
            )

            if callable(getter):
                return getter()

        except Exception:
            pass

    if isinstance(
        source,
        CurrentService,
    ):
        try:
            ref = source.getCurrentServiceRef()

            getter = (
                getattr(
                    ref,
                    "getPath",
                    None,
                )
                if ref
                else None
            )

            if callable(getter):
                return getter()

        except Exception:
            pass

    return None


def detect_media(source):
    movie_path = get_movie_path(
        source
    )

    if (
        not movie_path
        or not is_video_file(movie_path)
    ):
        return {
            "is_media": False,
            "movie_path": None,
            "clean_title": "",
            "year": "",
            "is_episode": False,
            "ep_marker": "",
        }

    (
        clean,
        year,
        is_ep,
        ep_marker,
    ) = clean_filename(
        movie_path
    )

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
    re.I | re.U,
)


_X_EMARK_RE = re.compile(
    r"\b(\d{1,2})x(\d{1,3})\b",
    re.I | re.U,
)


_SEASON_MARKER_RE = re.compile(
    r"\bseason[\s._-]*\d+\b",
    re.I | re.U,
)


_EPISODE_MARKER_RE = re.compile(
    r"\bepisode[\s._-]*\d+\b",
    re.I | re.U,
)


_FILENAME_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})(?!\d)"
)


_DATE_PREFIX_RE = re.compile(
    r"^\d{8}\s+\d{4}\s*[-–]\s*"
)


_BRACKET_RE = re.compile(
    r"\[[^\]]+\]"
)


_PAREN_RE = re.compile(
    r"\([^)]*\)"
)


_BRACE_RE = re.compile(
    r"\{[^}]+\}"
)


_GARBAGE_RE = tuple(
    re.compile(
        pattern,
        re.I | re.U,
    )
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


_CHANNEL_PREFIX_RE = re.compile(
    r"""
    ^
    (?:
        BBC|ZDF|CNN|RAI|TVP|RTL|Vox|
        ProSieben|SAT\.?1|HBO|Sky|Canal\+
    )
    \s*[–-]\s*
    """,
    re.I | re.U | re.X,
)


_SCENE_GROUP_RE = re.compile(
    r"""
    ^
    (?:
        COCAIN|GECKOS|DRONES|SPARKS|DiAMOND|FGT|ION10|RARBG|
        YIFY|YTS|ETRG|XVID|RUSTED|WAR|GETiT
    )-
    """,
    re.I | re.U | re.X,
)


_filename_cache = OrderedDict()

_FILENAME_CACHE_MAX = 700

_filename_cache_lock = threading.RLock()


def is_emc_episode(filename):
    text = _normalize_digits(
        to_text(filename)
    )

    return bool(
        _S_EMARK_RE.search(text)
        or _X_EMARK_RE.search(text)
        or _SEASON_MARKER_RE.search(text)
        or _EPISODE_MARKER_RE.search(text)
    )


def extract_emc_year(filename):
    match = _FILENAME_YEAR_RE.search(
        to_text(filename)
    )

    return (
        match.group(1)
        if match
        else ""
    )


def _remove_filename_garbage(name):
    for pattern in _GARBAGE_RE:
        name = pattern.sub(
            " ",
            name,
        )

    return name


def _extract_filename_episode_marker(name):
    """
    Return:
        (is_episode, normalized_marker)

    This performs the detection once rather than calling
    is_emc_episode() and then searching the same patterns again.
    """

    match = _S_EMARK_RE.search(
        name
    )

    if match:
        try:
            return (
                True,
                "S%02dE%02d"
                % (
                    int(match.group(1)),
                    int(match.group(2)),
                ),
            )
        except Exception:
            return (
                True,
                "",
            )

    match = _X_EMARK_RE.search(
        name
    )

    if match:
        try:
            return (
                True,
                "S%02dE%02d"
                % (
                    int(match.group(1)),
                    int(match.group(2)),
                ),
            )
        except Exception:
            return (
                True,
                "",
            )

    if _SEASON_MARKER_RE.search(name):
        return (
            True,
            "",
        )

    if _EPISODE_MARKER_RE.search(name):
        return (
            True,
            "",
        )

    return (
        False,
        "",
    )


@traced("iConverlibr")
def _clean_filename_uncached(raw):
    raw = to_text(raw)

    if (
        not raw
        or not is_video_file(raw)
    ):
        return (
            "",
            "",
            False,
            "",
        )

    name = normalize_unicode_text(
        os.path.splitext(
            os.path.basename(raw)
        )[0]
    )

    name = _normalize_digits(
        name
    )

    name = _DATE_PREFIX_RE.sub(
        "",
        name,
    )

    name = _SCENE_GROUP_RE.sub(
        "",
        name,
    )

    name = _CHANNEL_PREFIX_RE.sub(
        "",
        name,
    )

    is_ep, ep_marker = (
        _extract_filename_episode_marker(
            name
        )
    )

    if is_ep:
        name = _S_EMARK_RE.sub(
            " ",
            name,
        )

        name = _X_EMARK_RE.sub(
            " ",
            name,
        )

        name = _SEASON_MARKER_RE.sub(
            " ",
            name,
        )

        name = _EPISODE_MARKER_RE.sub(
            " ",
            name,
        )

    # Preserve bracketed year before removing bracket metadata.
    name = _BRACKET_YEAR_RE.sub(
        r" \1 ",
        name,
    )

    # Filename separators.
    name = name.replace(
        "_",
        " ",
    )

    name = name.replace(
        ".",
        " ",
    )

    # Remove release metadata containers.
    name = _BRACKET_RE.sub(
        " ",
        name,
    )

    name = _PAREN_RE.sub(
        " ",
        name,
    )

    name = _BRACE_RE.sub(
        " ",
        name,
    )

    name = _remove_filename_garbage(
        name
    )

    name = _SPACE_RE.sub(
        " ",
        name,
    ).strip()

    # ---------------------------------------------------------------
    # Year
    # ---------------------------------------------------------------

    year_match = _FILENAME_YEAR_RE.search(
        name
    )

    year = (
        year_match.group(1)
        if year_match
        else ""
    )

    if year_match:
        title_part = name[
            :year_match.start()
        ].strip(
            " -._"
        )

        title_part = _SPACE_RE.sub(
            " ",
            title_part,
        ).strip(
            " -._"
        )

        name = (
            "%s %s"
            % (
                title_part,
                year,
            )
        ).strip()

    # ---------------------------------------------------------------
    # Separator cleanup.
    #
    # Preserve numeric constructions such as 9-1-1.
    # ---------------------------------------------------------------

    name = re.sub(
        r"\s+-\s+",
        " ",
        name,
    )

    name = re.sub(
        r"(?<!\d)-(?!\d)",
        " ",
        name,
    )

    name = _SPACE_RE.sub(
        " ",
        name,
    ).strip(
        " -._"
    )

    clean_title = name

    # The year is deliberately retained in the separate return value,
    # but not in the local clean title. This is the historical API
    # behavior used by build_emc_candidates().
    if (
        year
        and name.endswith(year)
    ):
        clean_title = name[
            : -len(year)
        ].strip()

    clean_title = _normalize_title_text(
        clean_title
    )

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

    if (
        clean_title.casefold()
        in invalid
    ):
        return (
            "",
            "",
            is_ep,
            ep_marker,
        )

    return (
        clean_title,
        year,
        is_ep,
        ep_marker,
    )


def clean_filename(raw):
    if not raw:
        return (
            "",
            "",
            False,
            "",
        )

    raw = to_text(raw)

    with _filename_cache_lock:
        cached = _filename_cache.get(
            raw
        )

        if cached is not None:
            _filename_cache.move_to_end(
                raw
            )
            return cached

    try:
        result = _clean_filename_uncached(
            raw
        )

    except Exception as exc:
        warn(
            "iConverlibr",
            "filename-clean-EX",
            "%s: %s"
            % (
                type(exc).__name__,
                exc,
            ),
        )

        result = (
            "",
            "",
            False,
            "",
        )

    with _filename_cache_lock:
        _filename_cache[raw] = result

        _filename_cache.move_to_end(
            raw
        )

        while (
            len(_filename_cache)
            > _FILENAME_CACHE_MAX
        ):
            _filename_cache.popitem(
                last=False
            )

    return result


def build_emc_candidates(filename):
    clean, year, is_ep, _ = (
        clean_filename(filename)
    )

    if not clean:
        return []

    candidates = []

    # Non-episode movies benefit from year-first searching.
    if year and not is_ep:
        candidates.append(
            "%s %s"
            % (
                clean,
                year,
            )
        )

    candidates.append(
        clean
    )

    raw_name = normalize_unicode_text(
        os.path.splitext(
            os.path.basename(
                to_text(filename)
            )
        )[0]
    )

    raw_name = _normalize_digits(
        raw_name
    )

    raw_name = re.sub(
        r"[._]+",
        " ",
        raw_name,
    )

    raw_name = re.sub(
        r"(?<!\d)-(?!\d)",
        " ",
        raw_name,
    )

    raw_name = _SPACE_RE.sub(
        " ",
        raw_name,
    ).strip()

    if (
        raw_name
        and raw_name not in candidates
    ):
        candidates.append(
            raw_name
        )

    result = []

    seen = set()

    for candidate in candidates:
        candidate = _normalize_title_text(
            candidate
        )

        identity = candidate.casefold()

        if (
            candidate
            and identity not in seen
        ):
            seen.add(identity)
            result.append(candidate)

    return result


def get_sidecar_path(
    video_path,
    ext=".jpg",
):
    if not video_path:
        return None

    base, _ = os.path.splitext(
        video_path
    )

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
            _nxts_refcounts.get(
                nxts,
                0,
            )
            + 1
        )


def unregister_nxts_slot(nxts):
    try:
        nxts = int(nxts)
    except Exception:
        return

    with _widget_lock:
        if nxts not in _nxts_refcounts:
            return

        value = (
            _nxts_refcounts[nxts]
            - 1
        )

        if value <= 0:
            del _nxts_refcounts[nxts]
        else:
            _nxts_refcounts[nxts] = value


def register_widget_present(kind):
    if kind not in _widget_refcounts:
        return

    with _widget_lock:
        _widget_refcounts[kind] += 1


def unregister_widget_present(kind):
    if kind not in _widget_refcounts:
        return

    with _widget_lock:
        _widget_refcounts[kind] = max(
            0,
            _widget_refcounts[kind] - 1,
        )


def widget_present(kind):
    with _widget_lock:
        return (
            _widget_refcounts.get(
                kind,
                0,
            )
            > 0
        )


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
        if _fallback_loaded.is_set():
            return

        if _fallback_loading:
            return

        _fallback_loading = True

        def _load():
            global _fallback_loading

            try:
                try:
                    skin = str(
                        config.skin.primary_skin.value
                    ).replace(
                        "/skin.xml",
                        "",
                    )
                except Exception:
                    skin = "default"

                for name in (
                    "noposter.jpg",
                    "nobackdrop.jpg",
                ):
                    paths = (
                        "/usr/share/enigma2/%s/main/%s"
                        % (
                            skin,
                            name,
                        ),
                        "/usr/share/enigma2/skin_default/main/%s"
                        % name,
                        "/tmp/%s"
                        % name,
                    )

                    for path in paths:
                        if not os.path.isfile(
                            path
                        ):
                            continue

                        try:
                            pixmap = loadJPG(
                                path
                            )

                            if pixmap:
                                _fallback_pixmaps[
                                    name
                                ] = pixmap

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
                _fallback_loaded.set()


def get_fallback_pixmap(name):
    _ensure_fallbacks_loaded()

    if not _fallback_loaded.is_set():
        return None

    return _fallback_pixmaps.get(
        name
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
        "_requested_titles",
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
        self._ch_skip = bool(
            ch_skip
        )
        self.generation = generation

        self._slot_count = 0
        self._slots = {}

        self.missing = []
        self._missing_titles = set()
        self._requested_titles = set()

        self._lock = threading.RLock()
        self._analyzed_cache = {}

        self._events_raw = (
            list(events)
            if events
            else []
        )

        self._slot_0_built = False
        self._slots_built = set()

        try:
            self._build_slot(0)
        except Exception as exc:
            warn(
                "iConverlibr",
                "zap-slot0-EX",
                "%s: %s"
                % (
                    type(exc).__name__,
                    exc,
                ),
            )

    def schedule_retry(self):
        # Kept for API compatibility.
        return False

    def _request_missing(self, entries):
        """
        Request only newly discovered titles.

        This is intentionally outside the context lock because the
        batch requester may perform work or callbacks of its own.
        """

        if not entries:
            return

        request_fn = (
            _batch_request_fn[0]
        )

        if not request_fn:
            return

        new_entries = []

        with self._lock:
            for entry in entries:
                if not entry:
                    continue

                title = entry[0]

                if (
                    not title
                    or title
                    in self._requested_titles
                ):
                    continue

                try:
                    record = _epg_store.get(title)
                    if (
                        record
                        and record.get("status") == "failed"
                        and not _epg_store.should_search(title)
                    ):
                        continue
                except Exception:
                    pass

                self._requested_titles.add(
                    title
                )

                new_entries.append(
                    entry
                )

        if not new_entries:
            return

        try:
            request_fn(
                new_entries
            )
        except Exception as exc:
            err(
                "iConverlibr",
                "batch-request-EX",
                str(exc),
            )

    def _build_slot(self, nxts):
        with self._lock:
            if nxts in self._slots_built:
                return self._slots.get(
                    nxts
                )

        if (
            nxts < 0
            or nxts >= len(self._events_raw)
        ):
            return None

        evt = self._events_raw[nxts]

        if (
            not isinstance(
                evt,
                (tuple, list),
            )
            or len(evt) < 5
            or not evt[4]
        ):
            with self._lock:
                self._slots_built.add(
                    nxts
                )

            return None

        try:
            raw = clean_name(
                evt[4]
            )

            desc = (
                evt[5]
                if len(evt) > 5
                else ""
            )

            begin_time = (
                evt[1]
                if len(evt) > 1
                else 0
            )

            with self._lock:
                analyzed = (
                    self._analyzed_cache.get(
                        raw
                    )
                )

            if analyzed is None:
                analyzed = analyze_epg_title(
                    raw
                )

                with self._lock:
                    self._analyzed_cache[
                        raw
                    ] = analyzed

            skip, clean, candidates = (
                analyzed
            )
            profile = get_epg_title_profile(raw)
            season_hint = profile.get("season")
            part_hint = profile.get("part")
            episode_hint = profile.get("episode")
            secondary_title = (
                profile.get("secondary_title")
                or profile.get("episode_title")
                or ""
            )

            skip = bool(
                skip
                or self._ch_skip
            )

            rec = (
                _epg_store.get(clean)
                if clean
                else None
            )

            data = (
                rec["data"]
                if rec
                else {}
            )

            if clean:
                assets = resolve_asset_paths(
                    clean
                )
            else:
                assets = {
                    "local_path": None,
                    "backdrop_path": None,
                    "logo_path": None,
                }

            meta = (
                build_meta_dict(data)
                if (
                    clean
                    and has_useful_metadata(
                        data
                    )
                )
                else None
            )

            slot = {
                "clean_title": clean,
                "local_path": assets[
                    "local_path"
                ],
                "backdrop_path": assets[
                    "backdrop_path"
                ],
                "logo_path": assets[
                    "logo_path"
                ],
                "skip": skip,
                "search_candidates": candidates,
                "secondary_title": secondary_title,
                "season_hint": season_hint,
                "part_hint": part_hint,
                "episode_hint": episode_hint,
                "event_key": make_event_key(
                    begin_time,
                    raw,
                ),
                "raw_name": raw,
                "description": desc,
                "hint_year": (
                    extract_epg_hints(
                        desc
                    ).get("year")
                    if desc
                    else None
                ),
                "begin_time": begin_time,
                "slot_index": nxts,
            }

            slot.update(
                meta
                or _EMPTY_METADATA
            )

            missing_entry = None

            with self._lock:
                self._slots[nxts] = slot

                self._slot_count = max(
                    self._slot_count,
                    nxts + 1,
                )

                if nxts == 0:
                    self._slot_0_built = True

                self._slots_built.add(
                    nxts
                )

                if (
                    clean
                    and not skip
                    and (
                        not assets[
                            "local_path"
                        ]
                        or not assets[
                            "backdrop_path"
                        ]
                        or not assets[
                            "logo_path"
                        ]
                    )
                    and clean
                    not in self._missing_titles
                ):
                    self._missing_titles.add(
                        clean
                    )

                    missing_entry = (
                        clean,
                        raw,
                        candidates,
                        slot["hint_year"],
                        season_hint,
                        episode_hint,
                        secondary_title,
                        part_hint,
                    )

                    self.missing.append(
                        missing_entry
                    )

            if missing_entry:
                self._request_missing(
                    [missing_entry]
                )

            return slot

        except Exception as exc:
            warn(
                "iConverlibr",
                "zap-build-slot-EX",
                "%s: %s"
                % (
                    type(exc).__name__,
                    exc,
                ),
            )

            with self._lock:
                self._slots_built.add(
                    nxts
                )

            return None

    def get_slot(self, nxts):
        with self._lock:
            slot = self._slots.get(
                nxts
            )

            if slot is not None:
                return slot

        return self._build_slot(
            nxts
        )

    def update_slot_metadata(
        self,
        clean_title,
        meta_dict,
        event_key=None,
    ):
        if (
            not clean_title
            or not meta_dict
        ):
            return

        changed = False

        with self._lock:
            for slot in self._slots.values():
                if (
                    slot.get(
                        "clean_title"
                    )
                    != clean_title
                ):
                    continue

                if (
                    event_key
                    and slot.get(
                        "event_key"
                    )
                    != event_key
                ):
                    continue

                slot.update(
                    meta_dict
                )

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

        changed = False

        with self._lock:
            for slot in self._slots.values():
                if (
                    slot.get(
                        "clean_title"
                    )
                    != clean_title
                ):
                    continue

                if (
                    event_key
                    and slot.get(
                        "event_key"
                    )
                    != event_key
                ):
                    continue

                if slot.get(key) != path:
                    slot[key] = path
                    changed = True

            if changed or path:
                # Asset content may change while the filename stays identical
                # (most importantly when the detected season changes).
                self.generation += 1

        if path:
            folder_fn = {
                "poster": get_poster_folder,
                "backdrop": get_backdrop_folder,
                "logo": get_logo_folder,
            }.get(kind)

            if folder_fn:
                try:
                    mark_file_indexed(
                        folder_fn(),
                        os.path.basename(
                            path
                        ),
                    )
                except Exception:
                    pass

    def is_valid_for(self, ref_str):
        return (
            self._ref_str
            == ref_str
        )

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

        if not ref_str:
            return []

        now = time.monotonic()

        with self._lock:
            # IMPORTANT:
            # Cache validity is based on _last_fetch, not on
            # whether _data is truthy. An empty EPG result is
            # still a valid result for the cache interval.
            if (
                self._ref == ref_str
                and self._last_fetch
                and (
                    now
                    - self._last_fetch
                    < 2.0
                )
            ):
                return list(
                    self._data
                )

        events = []

        try:
            from enigma import eEPGCache

            epg = (
                eEPGCache.getInstance()
            )

            if epg:
                result = epg.lookupEvent(
                    [
                        "IBOCTESX",
                        (
                            ref_str,
                            0,
                            -1,
                            -1,
                        ),
                    ]
                )

                if result:
                    events = list(
                        result
                    )

        except Exception as exc:
            warn(
                "iConverlibr",
                "epg-cache-lookup-EX",
                str(exc),
            )

        now = time.monotonic()

        with self._lock:
            self._data = events
            self._ref = ref_str
            self._last_fetch = now

            return list(
                self._data
            )


_epg_cache = _EpgCache()


_zap_ctx = None
_zap_ctx_lock = threading.RLock()
_zap_ctx_build_lock = threading.Lock()


_current_ref = [None]
_batch_request_fn = [None]


def set_batch_request_fn(fn):
    _batch_request_fn[0] = (
        fn
        if callable(fn)
        else None
    )


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

        if (
            not current
            or not _zap_ctx.is_valid_for(
                current
            )
        ):
            _zap_ctx = None
            return

        if for_title:
            if any(
                slot.get(
                    "clean_title"
                )
                == for_title
                for slot in
                _zap_ctx._slots.values()
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

    if (
        not clean_title
        or kind
        not in (
            "poster",
            "backdrop",
            "logo",
        )
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


# ============================================================================
# EVENT SOURCE METADATA
# ============================================================================

@traced("iConverlibr")
def get_event_source_metadata(
    event_source
):
    try:
        evt = event_source.event

        if not evt:
            return None

        raw = clean_name(
            evt.getEventName()
        )

        if not raw:
            return None

        skip, clean, candidates = analyze_epg_title(raw)

        if skip or not clean:
            return None

        begin_time = (
            evt.getBeginTime()
            or 0
        )

        event_key = make_event_key(
            begin_time,
            raw,
        )

        assets = resolve_asset_paths(
            clean
        )

        rec = _epg_store.get(
            clean
        )

        data = (
            rec["data"]
            if rec
            else {}
        )

        try:
            desc = (
                evt.getExtendedDescription()
                or ""
            )
        except Exception:
            desc = ""

        slot = {
            "clean_title": clean,
            "local_path": assets[
                "local_path"
            ],
            "backdrop_path": assets[
                "backdrop_path"
            ],
            "logo_path": assets[
                "logo_path"
            ],
            "skip": False,
            "search_candidates": candidates,
            "secondary_title": profile.get("secondary_title") or profile.get("episode_title") or "",
            "season_hint": profile.get("season"),
            "part_hint": profile.get("part"),
            "episode_hint": profile.get("episode"),
            "event_key": event_key,
            "raw_name": raw,
            "description": desc,
            "hint_year": (
                extract_epg_hints(
                    desc
                ).get("year")
            ),
            "begin_time": begin_time,
        }

        slot.update(
            (
                build_meta_dict(data)
                if has_useful_metadata(
                    data
                )
                else _EMPTY_METADATA
            )
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

_zap_generation_lock = threading.Lock()
_zap_generation = 0


def _next_zap_generation():
    global _zap_generation

    with _zap_generation_lock:
        _zap_generation += 1

        if _zap_generation >= 2147483647:
            _zap_generation = 1

        return _zap_generation


@traced("iConverlibr")
def get_zap_context(
    service_ref
):
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

    if "FROM BOUQUET" in ref_str or "ORDER BY bouquet" in ref_str:
        return ZapContext("bouquet", [], True)

    with _zap_ctx_lock:
        if _zap_ctx is not None and _zap_ctx.is_valid_for(ref_str):
            return _zap_ctx

    # Only one widget builds a new context for a service. With 10+ renderers
    # this prevents duplicate EPG reads, title analysis and initial requests.
    with _zap_ctx_build_lock:
        with _zap_ctx_lock:
            if _zap_ctx is not None and _zap_ctx.is_valid_for(ref_str):
                return _zap_ctx

        ch_skip = False
        try:
            from ServiceReference import ServiceReference as SR
            ch_skip = is_sport_or_news_channel(SR(service_ref).getServiceName())
        except Exception:
            pass

        try:
            generation = _next_zap_generation()
            events = [] if ch_skip else _epg_cache.get(service_ref)
            new_ctx = ZapContext(ref_str, events or [], ch_skip, generation=generation)
        except Exception as exc:
            err("iConverlibr", "zap-context-EX", "%s: %s" % (type(exc).__name__, exc))
            return None

        with _zap_ctx_lock:
            if _zap_ctx is not None and _zap_ctx.is_valid_for(ref_str):
                return _zap_ctx
            _zap_ctx = new_ctx
        return new_ctx

# ============================================================================
# SEARCH CACHE
# ============================================================================

_SEARCH_TTL = 1800
_SEARCH_CACHE_MAX = 500

_search_cache = OrderedDict()
_search_lock = threading.RLock()


def get_cached_search(
    clean_title
):
    clean_title = to_text(
        clean_title
    ).strip()

    if not clean_title:
        return None

    now = time.monotonic()

    with _search_lock:
        entry = _search_cache.get(
            clean_title
        )

        if entry is None:
            return None

        timestamp, result = entry

        if (
            now - timestamp
            > _SEARCH_TTL
        ):
            del _search_cache[
                clean_title
            ]
            return None

        _search_cache.move_to_end(
            clean_title
        )

        return result


def set_cached_search(
    clean_title,
    result,
):
    clean_title = to_text(
        clean_title
    ).strip()

    if (
        not clean_title
        or not result
    ):
        return

    with _search_lock:
        _search_cache[
            clean_title
        ] = (
            time.monotonic(),
            result,
        )

        _search_cache.move_to_end(
            clean_title
        )

        while (
            len(_search_cache)
            > _SEARCH_CACHE_MAX
        ):
            _search_cache.popitem(
                last=False
            )


# ============================================================================
# CACHE RESET
# ============================================================================

def clear_runtime_caches():
    with _analyze_cache_lock:
        _analyze_cache.clear()
        _analyze_profile_cache.clear()

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

    invalidate_zap_context(
        force=True
    )


# ============================================================================
# HEALTH
# ============================================================================

def _health_probe():
    try:
        with _zap_ctx_lock:
            zap_valid = (
                _zap_ctx is not None
            )

        with _metadata_callback_lock:
            callback_keys = len(
                _metadata_callbacks
            )

        with _ready_queue_lock:
            queued = len(
                _ready_queue
            )

        with _analyze_cache_lock:
            analyzed = len(
                _analyze_cache
            )

        with _filename_cache_lock:
            filenames = len(
                _filename_cache
            )

        with _search_lock:
            searches = len(
                _search_cache
            )

        with _asset_exists_lock:
            asset_cache = len(
                _asset_exists_cache
            )

        return {
            "zap_context": zap_valid,
            "metadata_callback_keys": callback_keys,
            "gui_queue": queued,
            "analyze_cache": analyzed,
            "filename_cache": filenames,
            "search_cache": searches,
            "asset_cache": asset_cache,
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
# INITIAL STORAGE
# ============================================================================

_init_folders()


# ============================================================================
# END
# ============================================================================
