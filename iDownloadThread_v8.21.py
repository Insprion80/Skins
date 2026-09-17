#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
iDownloadThread.py - XDREAMY V8.21
Compact Python 3+ downloader for XDREAMY Enigma2.

Search design:
    The EPG cleaner removes structural episode markers and keeps the event
    identity. TMDB receives that identity directly and is responsible for
    original, translated and alternative-title matching.

    Season / episode are context, not title text. An explicit episode or
    season routes the request to /search/tv; otherwise /search/multi is kept
    for ambiguous movie/TV events. The search query itself is not changed.

    TMDB ranking is authoritative. We do not locally score or re-rank search
    candidates. The system may try a small ordered set of query identities when
    the EPG event contains episode-title text, season suffixes, or Arabizi. Each
    query is handled independently and TMDB order remains authoritative.

    Detail requests include the existing metadata package and title aliases.

ElCinema remains a bounded fallback provider when TMDB cannot
produce a valid result. Asset download, cache, callbacks and worker logic
remain unchanged.

Python 3+ only.
"""

import os
import ssl
import json
import html
import time
import queue
import random
import logging
import threading
import urllib.parse
import urllib.request
import re
import unicodedata

from difflib import SequenceMatcher

try:
    from logging.handlers import RotatingFileHandler
except Exception:
    RotatingFileHandler = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import requests
    from requests.adapters import HTTPAdapter
    REQUESTS_OK = True
except Exception:
    requests = None
    HTTPAdapter = None
    REQUESTS_OK = False

from enigma import loadJPG, loadPNG

from .iConverlibr import (
    get_cfg,
    get_poster_folder,
    get_backdrop_folder,
    get_logo_folder,
    get_state_store,
    file_exists_indexed,
    get_cached_search,
    set_cached_search,
    queue_gui_callback,
    notify_metadata_ready,
    set_batch_request_fn,
    widget_present,
    is_arabic,
    get_epg_title_profile,
)

from .iDebugger import traced, warn, err

# ============================================================================
# CONFIG
# ============================================================================

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/"

TMDB_POSTER_SIZE = "w342"
TMDB_BACKDROP_SIZE = "w780"
TMDB_LOGO_SIZE = "w300"

POSTER_MAX_WIDTH = 400
BACKDROP_MAX_WIDTH = 960
LOGO_MAX_WIDTH = 400

T_CONN = 3.0
T_READ = 8.0
T_IMG_PIC = 12.0
T_IMG_LOGO = 8.0

# REVERTED: poster minimum back to 4096 bytes for quality
MIN_BYTES_POSTER = 4096
MIN_BYTES_BACKDROP = 4096
MIN_BYTES_LOGO = 512

MAX_IMAGE_BYTES = 12 * 1024 * 1024

MIN_WORKERS = 4
MAX_WORKERS = 8

MAX_PENDING = 200

ELCINEMA_AJAX = "https://elcinema.com/ajaxable/search_simple?q="
ELCINEMA_TVGUIDE_URL = "https://elcinema.com/en/tvguide/"

STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not_found"

ASSET_KINDS = ("poster", "backdrop", "logo")

_ARABIC_LATIN_HINTS = frozenset((
    "el", "al", "abu", "umm", "ibn", "bin", "wa", "bi", "bila",
    "ma", "hob", "masry", "hekaya", "ahlan", "sittat", "mintaqa",
    "taj", "amina", "fael", "motawahesh", "nowaylati", "shaaban",
    "sha", "shaq", "faisal", "amouna", "fateen", "sirr", "qalb",
    "kothr", "hobbi", "lak", "mawt", "wouroud", "thonoub",
))

LOG_FILE = "/tmp/XDREAMY_downloads.log"
LOG_MAX_BYTES = 1024 * 1024

GENRES_MAP = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Sci-Fi",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}

MAX_WIDTH = {
    "poster": POSTER_MAX_WIDTH,
    "backdrop": BACKDROP_MAX_WIDTH,
    "logo": LOGO_MAX_WIDTH,
}

ELCINEMA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/114 Safari/537.36"
)

TMDB_UA = "XDREAMY-Enigma2/8.0"

LOG_FOUND_EVENTS = bool(get_cfg("LOG_FOUND_EVENTS"))

# ============================================================================
# LOGGING
# ============================================================================

_logger = None
_logger_lock = threading.Lock()

def _setup_logger():
    global _logger
    if _logger is not None:
        return
    with _logger_lock:
        if _logger is not None:
            return
        try:
            logger = logging.getLogger("XDREAMY_downloads")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            if RotatingFileHandler is not None:
                handler = RotatingFileHandler(
                    LOG_FILE,
                    maxBytes=LOG_MAX_BYTES,
                    backupCount=1,
                )
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
            _logger = logger
        except Exception:
            _logger = False

def log_event(raw_name, clean_title, status, poster=False, backdrop=False, logo=False, meta=False, source="TMDB"):
    try:
        _setup_logger()
        if not _logger:
            return
        line = (
            "%s | %-10s | %-10s | %-40s | %-40s | "
            "P:%-3s B:%-3s L:%-3s M:%-3s"
        ) % (
            time.strftime("%Y-%m-%d %H:%M:%S"),
            status.upper(),
            (source or "TMDB")[:10],
            (raw_name or "-")[:40],
            (clean_title or "-")[:40],
            "yes" if poster else "-",
            "yes" if backdrop else "-",
            "yes" if logo else "-",
            "yes" if meta else "-",
        )
        _logger.info(line)
    except Exception:
        pass

# ============================================================================
# HTTP
# ============================================================================

_http_local = threading.local()

def _get_http_session():
    if not REQUESTS_OK:
        return None
    session = getattr(_http_local, "session", None)
    if session is not None:
        return session
    try:
        session = requests.Session()
        pool = max(2, _worker_count() * 2)
        adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": TMDB_UA,
            "Accept": "application/json,text/html,*/*",
        })
        _http_local.session = session
        return session
    except Exception:
        return None

def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def http_get_json(url, headers=None, timeout=(T_CONN, T_READ)):
    headers = headers or {}
    session = _get_http_session()
    if session is not None:
        response = None
        try:
            response = session.get(url, headers=headers, timeout=timeout, verify=False)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout[0], context=_ssl_context()) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return None

def http_get_text(url, headers=None, timeout=(T_CONN, T_READ)):
    headers = headers or {}
    session = _get_http_session()
    if session is not None:
        response = None
        try:
            response = session.get(url, headers=headers, timeout=timeout, verify=False)
            if response.status_code != 200:
                return None
            response.encoding = response.encoding or "utf-8"
            return response.text
        except Exception:
            return None
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout[0], context=_ssl_context()) as response:
            raw = response.read()
        return raw.decode("utf-8", "ignore")
    except Exception:
        return None

def http_get_binary(url, timeout=(T_CONN, T_IMG_PIC), retries=1):
    session = _get_http_session()
    if session is not None:
        for attempt in range(retries + 1):
            response = None
            try:
                response = session.get(url, timeout=timeout, stream=True, verify=False)
                if response.status_code != 200:
                    return None
                length = response.headers.get("Content-Length")
                if length:
                    try:
                        if int(length) > MAX_IMAGE_BYTES:
                            return None
                    except Exception:
                        pass
                data = bytearray()
                for chunk in response.iter_content(32768):
                    if not chunk:
                        continue
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        return None
                return bytes(data)
            except Exception:
                if attempt < retries:
                    time.sleep(0.25)
            finally:
                try:
                    if response is not None:
                        response.close()
                except Exception:
                    pass
        return None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": random.choice([ELCINEMA_UA, "Mozilla/5.0 Chrome/114"])})
            with urllib.request.urlopen(req, timeout=timeout[0], context=_ssl_context()) as response:
                data = bytearray()
                while True:
                    chunk = response.read(32768)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        return None
                return bytes(data)
        except Exception:
            if attempt < retries:
                time.sleep(0.25)
    return None

# ============================================================================
# SMALL HELPERS
# ============================================================================

def _unique(items):
    result = []
    seen = set()
    for value in items or []:
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

def _safe_makedirs(path):
    if not path:
        return
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    try:
        return str(value)
    except Exception:
        return ""

def _strip_html(value):
    text = _text(value)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def _norm_title(value):
    try:
        text = html.unescape(_text(value)).lower()
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
        replacements = (
            ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
            ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ة", "ه"),
        )
        for src, dst in replacements:
            text = text.replace(src, dst)
        text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text, flags=re.UNICODE)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return _text(value).lower().strip()

def _tmdb_url(path, params):
    return TMDB_API_BASE + path + "?" + urllib.parse.urlencode(params, doseq=True)

# ============================================================================
# ARABIZI
# ============================================================================

_ARABIZI_DIGITS = {
    "2": "ء", "3": "ع", "4": "ش", "5": "خ",
    "6": "ط", "7": "ح", "8": "غ", "9": "ص",
}
_ARABIZI_SEQUENCES = (
    ("sh", "ش"), ("kh", "خ"), ("gh", "غ"),
    ("th", "ث"), ("dh", "ذ"), ("aa", "ا"),
    ("ou", "و"), ("oo", "و"), ("ee", "ي"),
)

def _arabizi_candidates(value):
    """
    Convert a romanized Arabic string to possible Arabic script variants.
    """
    value = _text(value).lower()
    result = []
    # Replace digits with Arabic letters
    first = "".join(_ARABIZI_DIGITS.get(char, char) for char in value)
    result.append(first)
    # Apply multi-character substitutions
    second = value
    for src, dst in _ARABIZI_SEQUENCES:
        second = second.replace(src, dst)
    second = "".join(_ARABIZI_DIGITS.get(char, char) for char in second)
    result.append(second)
    # Remove common prefixes
    third = re.sub(r"\b(el|al)\s+", "", value, flags=re.I)
    if third != value:
        result.append(third)
    return _unique(result)

# ============================================================================
# TMDB SUPPORT
# ============================================================================

def _extract_season_hint(clean_title, candidates):
    if not clean_title:
        return None
    prefix = _text(clean_title).strip().casefold() + " "
    for candidate in candidates or ():
        candidate = _text(candidate).strip().casefold()
        if candidate.startswith(prefix):
            suffix = candidate[len(prefix):].strip()
            if suffix.isdigit() and not (len(suffix) == 4 and suffix[:2] in ("19", "20")):
                try:
                    season = int(suffix)
                    if 0 < season <= 99:
                        return season
                except Exception:
                    pass
    return None

def _looks_arabic_title(raw_title, clean_title):
    text = _text(raw_title or clean_title).strip().casefold()
    if re.search(r"[\u0600-\u06FF]", text):
        return True
    words = re.findall(r"[a-z]+", _text(clean_title or raw_title).casefold())
    if any(word in _ARABIC_LATIN_HINTS for word in words):
        return True
    # Generic Arabizi signal: require a digit to participate in a word rather
    # than treating any ordinary sequel number (e.g. "Star Trek 7") as Arabizi.
    if re.search(r"(?i)(?:^|\s)[23456789][a-z]{2,}|[a-z]{2,}[23456789][a-z]{1,}", text):
        return True
    return False

def _fetch_tmdb_season_poster(media_id, season_number, language):
    if not media_id or not season_number:
        return None
    params = {"api_key": get_cfg("TMDB_API_KEY"), "language": language or "en-US", "include_image_language": "ar,en,null"}
    data = http_get_json(_tmdb_url("/tv/%s/season/%s/images" % (media_id, season_number), params), headers={"User-Agent": TMDB_UA}, timeout=(T_CONN, T_READ))
    posters = (data or {}).get("posters") or []
    if not posters:
        return None
    def score(poster):
        lang = poster.get("iso_639_1")
        return (30 if lang in ("ar", "en") else 12 if lang is None else 0, _poster_orientation_score(poster), poster.get("vote_count") or 0)
    return max(posters, key=score).get("file_path") or None

def _tmdb_detail_aliases(item, detail):
    item, detail = item or {}, detail or {}
    aliases = [item.get("title"), item.get("name"), item.get("original_title"), item.get("original_name"), detail.get("title"), detail.get("name"), detail.get("original_title"), detail.get("original_name")]
    alt = detail.get("alternative_titles") or {}
    aliases.extend(t.get("title") for t in alt.get("titles") or [])
    for translation in (detail.get("translations") or {}).get("translations") or []:
        data = translation.get("data") or {}
        aliases.extend((data.get("title"), data.get("name")))
    return _unique(aliases)

def _tmdb_has_season(detail, season_hint):
    if not season_hint or not isinstance(detail, dict):
        return True
    try:
        wanted = int(season_hint)
    except Exception:
        return True
    for season in detail.get("seasons") or []:
        try:
            if int(season.get("season_number")) == wanted:
                return True
        except Exception:
            pass
    return False

def _tmdb_has_hard_title_collision(query, item, detail=None):
    q = _norm_title(query)
    if not q or len(q.split()) != 1:
        return False
    aliases = _tmdb_detail_aliases(item, detail or {})
    return not any(_norm_title(alias) == q for alias in aliases if alias)

# ============================================================================
# TMDB DETAIL
# ============================================================================

def _fetch_tmdb_detail(media_id, media_type, language, need_info=True, need_parental=False, need_images=True, include_titles=True):
    append = []
    if need_info:
        append.append("credits")
    if need_parental:
        append.append("release_dates" if media_type == "movie" else "content_ratings")
    if need_images:
        append.append("images")
    if include_titles:
        append.extend(("translations", "alternative_titles"))
    params = {
        "api_key": get_cfg("TMDB_API_KEY"),
        "language": language or "en-US",
    }
    if append:
        params["append_to_response"] = ",".join(_unique(append))
    if need_images:
        params["include_image_language"] = "ar,en,null"
    return http_get_json(
        _tmdb_url("/%s/%s" % (media_type, media_id), params),
        headers={"User-Agent": TMDB_UA},
        timeout=(T_CONN, T_READ),
    )

# ============================================================================
# TMDB IMAGE SELECTION
# ============================================================================

def _poster_orientation_score(poster):
    width = poster.get("width") or 0
    height = poster.get("height") or 0
    try:
        width = float(width); height = float(height)
    except Exception:
        return 0
    if width <= 0 or height <= 0:
        return 0
    ratio = height / width
    if ratio >= 1.30:
        return 20
    if ratio >= 1.15:
        return 8
    return -30

def _best_poster(detail, item, language):
    """Choose from TMDB image data first; use search poster only as fallback."""
    item = item or {}
    search_poster = item.get("poster_path") or ""
    images = (detail or {}).get("images") or {}
    posters = images.get("posters") or []
    if not posters:
        return search_poster
    language_is_ar = str(language or "").lower().startswith("ar")
    preferred = ("ar", "en", None) if language_is_ar else ("en", None, "ar")
    def score(poster):
        lang = poster.get("iso_639_1")
        lang_score = 30 if lang == preferred[0] else 20 if lang == preferred[1] else 10 if lang == preferred[2] else 0
        return (lang_score, _poster_orientation_score(poster), poster.get("vote_count") or 0)
    best = max(posters, key=score)
    return best.get("file_path") or ""

def _best_backdrop(detail, item):
    images = (detail or {}).get("images") or {}
    backdrops = images.get("backdrops") or []
    search_backdrop = item.get("backdrop_path")
    if not backdrops:
        return search_backdrop or ""
    candidates = []
    for backdrop in backdrops:
        path = backdrop.get("file_path")
        if not path:
            continue
        lang = backdrop.get("iso_639_1")
        lang_score = 40 if lang is None else 20 if lang == "en" else 10 if lang == "ar" else 0
        votes = backdrop.get("vote_count") or 0
        vote_score = min(int(votes), 100) / 10.0
        primary_bonus = 20 if search_backdrop and path == search_backdrop else 0
        candidates.append((path, lang_score + vote_score + primary_bonus))
    if not candidates:
        return search_backdrop or ""
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]

def _best_logo(detail):
    images = (detail or {}).get("images") or {}
    logos = images.get("logos") or []
    if not logos:
        return ""
    def score(logo):
        lang = logo.get("iso_639_1")
        lang_score = 30 if lang == "en" else 28 if lang == "ar" else 20 if lang is None else 0
        width = logo.get("width") or 0
        try:
            width_score = min(float(width) / 1000.0, 10)
        except Exception:
            width_score = 0
        return (lang_score, width_score, logo.get("vote_count") or 0)
    logo = max(logos, key=score)
    path = logo.get("file_path") or ""
    return _image_url(_logo_size(), path) if path else ""

# ============================================================================
# TMDB RESULT
# ============================================================================

def _extract_tmdb_parental_rating(detail, media_type):
    try:
        if media_type == "movie":
            results = (detail.get("release_dates") or {}).get("results") or []
            preferred = ("EG", "US", "GB")
            ordered = sorted(results, key=lambda x: 0 if x.get("iso_3166_1") in preferred else 1)
            for country in ordered:
                for release in country.get("release_dates") or []:
                    cert = (release.get("certification") or "").strip()
                    if cert:
                        return cert
        else:
            results = (detail.get("content_ratings") or {}).get("results") or []
            preferred = ("EG", "US", "GB")
            ordered = sorted(results, key=lambda x: 0 if x.get("iso_3166_1") in preferred else 1)
            for rating in ordered:
                val = (rating.get("rating") or "").strip()
                if val:
                    return val
    except Exception:
        pass
    return ""

def _build_tmdb_result(item, detail, media_type, language, season_hint=None):
    if not detail:
        return None
    poster_path = _best_poster(detail, item, language)

    # TMDB's show-level poster is usually just season 1's key art. When
    # we know which season this EPG event actually belongs to, prefer
    # that season's own poster if it has a distinct one.
    if media_type == "tv" and season_hint:
        season_poster = None
        for season in detail.get("seasons") or []:
            try:
                if int(season.get("season_number")) == int(season_hint):
                    season_poster = season.get("poster_path") or None
                    break
            except Exception:
                pass
        if not season_poster:
            season_poster = _fetch_tmdb_season_poster(item.get("id"), season_hint, language)
        if season_poster:
            poster_path = season_poster

    backdrop_path = _best_backdrop(detail, item)
    logo_url = _best_logo(detail)
    if not poster_path and not backdrop_path and not logo_url:
        return None
    credits = detail.get("credits") or {}
    director = ""
    for crew in credits.get("crew") or []:
        if crew.get("job") == "Director":
            director = crew.get("name") or ""
            break
    cast = ", ".join(m.get("name") or "" for m in (credits.get("cast") or [])[:10] if m.get("name"))
    countries = ", ".join(c.get("name") or "" for c in (detail.get("production_countries") or [])[:2] if c.get("name"))
    genres = [g.get("name") for g in (detail.get("genres") or []) if g.get("name")]
    if not genres:
        genres = [GENRES_MAP[g] for g in (item.get("genre_ids") or []) if g in GENRES_MAP]
    year = (item.get("release_date") or item.get("first_air_date") or detail.get("release_date") or detail.get("first_air_date") or "")[:4]
    title = item.get("title") or item.get("name") or detail.get("title") or detail.get("name") or ""
    return {
        "status": STATUS_FOUND,
        "poster_url": _image_url(_poster_size(), poster_path),
        "backdrop_url": _image_url(_backdrop_size(), backdrop_path),
        "logo_url": logo_url,
        "vote_average": item.get("vote_average", detail.get("vote_average", 0)),
        "parental_rating": _extract_tmdb_parental_rating(detail, media_type),
        "genres": ", ".join(genres),
        "year": year,
        "overview": detail.get("overview") or item.get("overview") or "",
        "director": director,
        "cast": cast,
        "country": countries,
        "title": title,
        "_media_id": item.get("id"),
        "_media_type": media_type,
        "_fallback_source": "TMDB",
        "_season_hint": season_hint or 0,
    }

# ============================================================================
# TMDB SEARCH
# ============================================================================

def _tmdb_direct_query(raw_title, clean_title, season_hint=None):
    """Return the cleaned EPG identity for TMDB search.

    The cleaner owns metadata removal.  Do not manufacture alternative title
    queries here.  clean_title is the preferred identity; raw_title is only a
    compatibility fallback for older callers.
    """
    query = _text(clean_title).strip()
    if query:
        return query

    raw = _text(raw_title).strip()
    if not raw:
        return ""

    raw = html.unescape(raw)
    raw = unicodedata.normalize("NFKC", raw)
    raw = re.sub(
        r"(?is)\s+(?<!\w)(?:episode|episod|epsiode|ep|odcinek|odc|folge|teil|episodio|capitulo|capítulo|chapitre|bölüm|bolum|puntata|part|parte|pt|p|حلقة|ح|جزء)\.?\s*#?\s*\d{1,4}.*$",
        "",
        raw,
    )
    return re.sub(r"\s+", " ", raw).strip(" .,:;/-–—")


def _tmdb_search_once(query, language, media_type="multi", hint_year=None):
    if not query:
        return None

    endpoint = "/search/%s" % (media_type or "multi")
    params = {
        "api_key": get_cfg("TMDB_API_KEY"),
        "language": language,
        "query": query,
        "include_adult": "false",
    }
    if hint_year:
        try:
            year = int(hint_year)
            if 1000 <= year <= 9999:
                if media_type == "movie":
                    params["primary_release_year"] = year
                elif media_type == "tv":
                    params["first_air_date_year"] = year
        except Exception:
            pass

    return http_get_json(
        _tmdb_url(endpoint, params),
        headers={"User-Agent": TMDB_UA},
        timeout=(T_CONN, T_READ),
    )


def _tmdb_ordered_usable(results, media_type="multi"):
    usable = []
    for item in results or []:
        if not item.get("id"):
            continue
        if media_type in ("tv", "movie"):
            if item.get("media_type") and item.get("media_type") != media_type:
                continue
            if not item.get("media_type"):
                item = dict(item)
                item["media_type"] = media_type
        elif item.get("media_type") not in ("movie", "tv"):
            continue
        usable.append(item)
    return usable


def _tmdb_result_title(item):
    return (
        item.get("title")
        or item.get("name")
        or item.get("original_title")
        or item.get("original_name")
        or ""
    )


def _tmdb_alias_match_kind(query, item, detail, allow_close=False):
    """Return the strength of TMDB's own title/alias relationship."""
    q = _norm_title(query)
    if not q:
        return 0
    aliases = [a for a in _tmdb_detail_aliases(item, detail) if a]
    for alias in aliases:
        if _norm_title(alias) == q:
            return 3

    q_tokens = q.split()
    if len(q_tokens) >= 2:
        qset = set(q_tokens)
        for alias in aliases:
            aset = set(_norm_title(alias).split())
            if qset and qset.issubset(aset):
                return 2
            # EPGs often add an episode subtitle after the real program title,
            # e.g. "Grand Hotel - All Secrets Stay Here".  When TMDB's full
            # alias is a multiword subset of the event query, accept it as the
            # same title. One-word generic aliases are intentionally excluded.
            if (len(aset) >= 2 and len(q_tokens) >= 3 and
                    aset.issubset(qset) and len(" ".join(aset)) >= 6):
                return 2
            # Localized titles sometimes add substantial wording around a
            # distinctive numbered franchise, e.g. "Squadra Speciale Cobra 11"
            # versus TMDB's "... Cobra 11 ...".  A shared numeric token plus
            # one shared word is a safe, narrow recovery signal.
            shared = qset & aset
            numeric_shared = any(token.isdigit() for token in shared)
            if numeric_shared and len(shared) >= 2:
                return 2

    # Very small typo tolerance is allowed only when the event already carries
    # explicit season/episode context. This is for cases such as "Casttle VI"
    # -> "Castle", not for generic one-word searches such as "Pagesa".
    if allow_close and len(q_tokens) == 1 and len(q) >= 5:
        for alias in aliases:
            for token in _norm_title(alias).split():
                if len(token) >= 5 and SequenceMatcher(None, q, token).ratio() >= 0.86:
                    return 1
    return 0

def _tmdb_candidate_valid(item, detail, query, season_hint, require_exact=False):
    if not item or not detail:
        return False
    if item.get("media_type") not in ("movie", "tv") or not item.get("id"):
        return False

    # TMDB remains responsible for ranking, but the returned record must still
    # identify the requested program. The previous V8.16 version accepted any
    # top result for multi-word queries, which explains wrong posters such as
    # Familja Simpson -> American Symphony and Pagesa -> 18 Pages.
    match_kind = _tmdb_alias_match_kind(
        query, item, detail,
        allow_close=bool(season_hint),
    )
    if require_exact and match_kind < (1 if season_hint else 3):
        return False
    if match_kind <= 0:
        return False
    return True


def _trailing_season_fallback(query):
    """Return (base_title, season) for a conservative trailing-season retry.

    This is deliberately a fallback only.  The original natural query is always
    tried first, so titles such as ``Apollo 13`` or ``Alien 3`` remain intact
    when TMDB can identify them normally.  If the natural query produces no
    usable result, a trailing 1-2 digit number on a multi-word identity can be
    interpreted as season context and retried through /search/tv.  The normal
    season validation then rejects TV results that do not actually contain that
    season.
    """
    query = _text(query).strip()
    if not query or len(query.split()) < 2:
        return None, None

    match = re.match(r"^(?P<title>.+?)\s*(?:[-–—]\s*)?(?P<number>\d{1,2})$", query)
    if not match:
        return None, None

    base = match.group("title").strip(" -,:;.")
    try:
        season = int(match.group("number"))
    except Exception:
        return None, None

    if not base or season < 1 or season > 99:
        return None, None
    if re.search(r"(?:19|20)\d{2}$", query):
        return None, None
    return base, season


def _finalize_tmdb_result(item, detail, query, language, season_hint, reason):
    result = _build_tmdb_result(
        item,
        detail,
        item.get("media_type"),
        language,
        season_hint,
    )
    if not result:
        return None
    result["_query_title"] = query
    result["_english_title"] = (
        detail.get("name")
        or detail.get("title")
        or detail.get("original_name")
        or detail.get("original_title")
        or _tmdb_result_title(item)
        or ""
    )
    result["_match_confidence"] = 100
    result["_match_primary"] = 100
    result["_match_secondary"] = 0
    result["_tmdb_rank"] = 1
    result["_search_reason"] = reason
    return result


def _build_search_identity(clean_title, secondary_title=None):
    """Build the single natural title sent to a provider.

    The event is deliberately treated as an identity plus optional secondary
    title. Season/episode numbers are context and are NOT appended to the
    search query. TMDB is very good at title/alias search; our job is to give
    it the cleanest identity and then use the returned metadata to interpret
    the context.
    """
    primary = re.sub(r"\s+", " ", _text(clean_title)).strip(" .,:;/-–—")
    secondary = re.sub(r"\s+", " ", _text(secondary_title)).strip(" .,:;/-–—")
    if not primary:
        return secondary
    if not secondary:
        return primary

    # Avoid sending the same text twice when the cleaner already kept the
    # secondary part inside the identity (for example "Title: Subtitle").
    pnorm = _norm_title(primary)
    snorm = _norm_title(secondary)
    if not snorm or snorm == pnorm or snorm in pnorm:
        return primary
    return "%s: %s" % (primary, secondary)


def _tmdb_part_matches(item, detail, part_hint):
    """Soft context check for explicit Part N wording.

    Part is not a media-type signal. When TMDB exposes the same part number in
    the title/alias, prefer that result; when it does not, the normal TMDB
    title match remains acceptable.
    """
    if not part_hint:
        return False
    try:
        number = int(part_hint)
    except Exception:
        return False
    texts = [
        _tmdb_result_title(item),
        detail.get("title") or detail.get("name") or "",
        detail.get("original_title") or detail.get("original_name") or "",
    ]
    aliases = _tmdb_detail_aliases(item, detail)
    texts.extend(aliases)
    for value in texts:
        norm = _norm_title(value)
        if not norm:
            continue
        if re.search(r"\bpart\s*%d\b" % number, norm, re.I):
            return True
        if re.search(r"\bparte\s*%d\b" % number, norm, re.I):
            return True
        if re.search(r"\b(?:جزء)\s*%d\b" % number, norm, re.I):
            return True
    return False

def _tmdb_query_variants(clean_title, raw_title=None, secondary_title=None):
    """Return a very small ordered set of useful search identities.

    V8.18 was too strict in one direction: it sent only one compound identity.
    That is good for precision, but EPG titles often append an episode name,
    subtitle, country-language title or a trailing broadcast number that TMDB
    does not store as part of the series/movie title.

    Keep the current identity as the first query.  Only when it fails do we
    try deterministic reductions of that same identity.  No popularity or
    random local ranking is introduced.
    """
    result = []
    seen = set()

    def add(value):
        value = re.sub(r"\s+", " ", _text(value)).strip(" .,:;/-–—")
        if not value:
            return
        norm = _norm_title(value)
        if not norm or norm in seen:
            return
        seen.add(norm)
        result.append(value)

    primary = _build_search_identity(clean_title, secondary_title)
    base = re.sub(r"\s+", " ", _text(clean_title)).strip(" .,:;/-–—")
    add(primary)
    if base and _norm_title(base) != _norm_title(primary):
        add(base)

    # A colon/dash secondary block is frequently an episode/program subtitle.
    # Search the title head after the natural query has failed.
    for value in (primary, base):
        if not value:
            continue
        head = re.split(r"\s*[-–—:]\s*", value, maxsplit=1)[0].strip()
        if len(_norm_title(head).split()) >= 2:
            add(head)

    # Controlled recovery for feeds such as "The Irrational - 11" or
    # "Hotel Costiera - 1".  The numbered title itself remains the first query;
    # this base query is only a fallback and is still validated by TMDB.
    for value in (base, _text(raw_title).strip()):
        if not value:
            continue
        m = re.match(r"^(.*?)(?:\s*[-–—]\s*|\s+)(\d{1,3})$", value)
        if m and len(_norm_title(m.group(1)).split()) >= 2:
            add(m.group(1))

    # One controlled Arabizi recovery.  It is useful for Arabic titles written
    # in Latin characters and does not rewrite the user's original identity.
    if _looks_arabic_title(raw_title, base):
        for variant in _arabizi_candidates(base)[:2]:
            add(variant)

    return result[:5]


def _tmdb_quick_match_kind(query, item):
    """Cheap search-result check before making a detail request."""
    q = _norm_title(query)
    if not q or not item:
        return 0
    aliases = _unique((item.get("title"), item.get("name"),
                       item.get("original_title"), item.get("original_name")))
    q_tokens = q.split()
    qset = set(q_tokens)
    best = 0
    for alias in aliases:
        a = _norm_title(alias)
        if not a:
            continue
        if a == q:
            best = max(best, 3)
            continue
        aset = set(a.split())
        if len(q_tokens) >= 2 and qset.issubset(aset):
            best = max(best, 2)
        if len(aset) >= 2 and len(q_tokens) >= 3 and aset.issubset(qset):
            best = max(best, 2)
        if len(q_tokens) >= 2 and SequenceMatcher(None, q, a).ratio() >= 0.90:
            best = max(best, 1)
    return best


def _tmdb_search_title(clean_title, candidates, hint_year=None, season_hint=None,
                       raw_title=None, secondary_title=None, episode_hint=None,
                       part_hint=None):
    """Search TMDB with fast staged validation.

    Primary policy is unchanged:
      * episode context -> TV first, then multi
      * no episode context -> movie first, then multi
      * season/part remain soft context

    Improvements:
      * keep the natural compound query first
      * only use deterministic fallback identities after a miss
      * avoid detail requests for obviously unrelated search results
      * inspect at most 2 strong/likely candidates per search
      * use a TV endpoint as a final season-aware fallback
    """
    if not get_cfg("TMDB_API_KEY"):
        return None, True, "TMDB_NO_KEY"

    language = get_cfg("TMDB_LANGUAGE") or "en-US"
    queries = _tmdb_query_variants(clean_title, raw_title, secondary_title)
    if not queries:
        return None, False, "TMDB_NO_MATCH"

    # A trailing number is ambiguous by itself, so the primary search remains
    # movie-first when there is no explicit episode marker. Once that exact
    # identity fails, a deterministic base-title retry can treat the number as
    # likely EPG episode context. Multi-search remains available immediately
    # afterward, so movie sequels are not excluded.
    trailing_episode_fallback = bool(
        re.search(r"(?:^|\s)-\s+\d{1,3}$", _text(clean_title).strip())
    )

    preferred = "tv" if episode_hint else "movie"
    endpoint_sets = [(preferred, "multi")]
    if season_hint and not episode_hint:
        endpoint_sets.append(("tv",))

    saw_network_error = False

    _debug_log("SEARCH", "queries=%s season=%s part=%s episode=%s" % (queries, season_hint, part_hint, episode_hint), clean_title=clean_title)

    for query_index, query in enumerate(queries):
        # The first identity gets the normal endpoint pair. Reduced queries are
        # cheaper recovery paths: keep the first endpoint first, but stop early
        # as soon as a validated candidate is obtained.
        if query_index == 0:
            endpoints = endpoint_sets[0]
        elif query_index == 1 and trailing_episode_fallback and not episode_hint:
            endpoints = ("tv", "multi")
        elif season_hint or episode_hint:
            # Reduced identities are mainly recovery searches. Prefer the TV
            # namespace when structured episode/season context exists, then let
            # one generic search recover movies or unusual provider mappings.
            endpoints = ("tv", "multi") if query_index == 1 else ("multi",)
        else:
            # For ambiguous movie/TV titles the original movie+multi pair has
            # already been exhausted. Further identities use only multi-search.
            endpoints = ("multi",)

        for endpoint_index, media_type in enumerate(endpoints):
            _debug_log("SEARCH", "TMDB %s: %s" % (media_type, query), clean_title=clean_title)
            data = _tmdb_search_once(query, language, media_type, hint_year)
            if data is None:
                saw_network_error = True
                continue

            results = _tmdb_ordered_usable(data.get("results") or [], media_type)
            if not results:
                continue

            # Search results are already relevance-ordered. We merely select
            # which of the first few deserve an expensive detail request.
            detail_candidates = []
            for rank, item in enumerate(results[:8], 1):
                quick = _tmdb_quick_match_kind(query, item)
                if quick > 0:
                    detail_candidates.append((rank, item))

            # TMDB result order stays authoritative. The lexical check is only
            # a cheap gate to avoid detail requests for clearly unrelated rows.
            # Localized titles may have no cheap lexical clue, so preserve the
            # first TMDB result in that case.
            if not detail_candidates and results:
                detail_candidates = [(1, results[0])]

            first_valid = None
            for rank, item in detail_candidates[:2]:
                item_type = item.get("media_type") or media_type
                if item_type not in ("movie", "tv"):
                    continue

                # Full detail is now reserved for likely candidates instead of
                # all five results, cutting the normal network workload sharply.
                detail = _fetch_tmdb_detail(
                    item.get("id"), item_type, language,
                    need_info=True, need_parental=True, need_images=True,
                    include_titles=True,
                )
                if not detail:
                    continue

                allow_close = bool(
                    episode_hint or season_hint or len(_norm_title(query).split()) >= 3
                )
                match_kind = _tmdb_alias_match_kind(
                    query, item, detail, allow_close=allow_close
                )
                if match_kind <= 0:
                    continue

                season_matched = None
                if season_hint and item_type == "tv":
                    season_matched = _tmdb_has_season(detail, season_hint)
                part_matched = _tmdb_part_matches(item, detail, part_hint)
                effective_season = season_hint if season_matched else 0

                result = _finalize_tmdb_result(
                    item, detail, query, language, effective_season,
                    "TMDB_%s_Q%d_RANK_%d" % (media_type.upper(), query_index + 1, rank),
                )
                if not result:
                    continue

                result["_query_index"] = query_index + 1
                result["_tmdb_rank"] = rank
                result["_query_title"] = query
                result["_match_kind"] = match_kind
                result["_preferred_endpoint"] = preferred
                result["_season_requested"] = season_hint or 0
                result["_season_matched"] = season_matched
                result["_part_hint"] = part_hint or 0
                result["_part_matched"] = part_matched
                result["_episode_hint"] = episode_hint or 0

                if first_valid is None:
                    first_valid = result

                # TMDB already ordered the candidates. An exact alias match is
                # strong enough to stop immediately unless season/part context
                # is present and this result does not satisfy it. This removes
                # the common second detail request without changing provider ranking.
                if match_kind >= 3 and not (season_hint or part_hint):
                    return result, False, result.get("_search_reason", "TMDB_FOUND")
                if (season_matched or part_matched):
                    return result, False, result.get("_search_reason", "TMDB_FOUND")

            if first_valid is not None:
                return first_valid, False, first_valid.get("_search_reason", "TMDB_FOUND")

    if saw_network_error:
        return None, True, "TMDB_ERROR"
    return None, False, "TMDB_NO_MATCH"

def _poster_size():
    return get_cfg("POSTER_SIZE") or TMDB_POSTER_SIZE
def _backdrop_size():
    return get_cfg("BACKDROP_SIZE") or TMDB_BACKDROP_SIZE
def _logo_size():
    return get_cfg("LOGO_SIZE") or TMDB_LOGO_SIZE

def _image_url(size, path):
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return TMDB_IMG_BASE + size + path

# ============================================================================
# ELCINEMA
# ============================================================================

def _elcinema_fetch(url, headers=None):
    headers = headers or {}
    session = _get_http_session()
    if session is not None:
        response = None
        try:
            response = session.get(url, headers=headers, timeout=(T_CONN, T_READ), verify=False)
            if response.status_code != 200:
                return None
            response.encoding = response.encoding or "utf-8"
            return response.text
        except Exception:
            return None
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=T_READ, context=_ssl_context()) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception:
        return None

def _elcinema_page_search(title):
    url = "https://elcinema.com/en/search/?q=" + urllib.parse.quote(title)
    page = _elcinema_fetch(
        url,
        {"User-Agent": ELCINEMA_UA, "Accept-Language": "en,ar;q=0.8"},
    )
    if not page:
        return None
    query_norm = _norm_title(title)
    best = None
    best_score = 0.0
    for href, text in re.findall(
        r'<a[^>]+href="((?:https://elcinema\.com)?/(?:en/)?work/\d+/)[^>]*>(.*?)</a>',
        page, re.I | re.S,
    ):
        found = _strip_html(text)
        if not found:
            continue
        found_norm = _norm_title(found)
        ratio = SequenceMatcher(None, query_norm, found_norm).ratio() * 100
        tokens = set(query_norm.split())
        found_tokens = set(found_norm.split())
        token_ratio = len(tokens & found_tokens) / float(len(tokens) or 1)
        score = ratio + token_ratio * 10
        if score > best_score:
            work_id = re.search(r'/work/(\d+)/', href)
            if work_id:
                best_score = score
                best = (work_id.group(1), found, "")
    if not best or best_score < 62:
        return None
    found_norm = _norm_title(best[1])
    if found_norm == query_norm:
        return best
    q_tokens = set(query_norm.split())
    f_tokens = set(found_norm.split())
    coverage = len(q_tokens & f_tokens) / float(len(q_tokens) or 1)
    return best if len(q_tokens) >= 2 and coverage >= 0.80 and best_score >= 82 else None

def _elcinema_ajax_search(title):
    """Search ElCinema AJAX; return work id, title and thumbnail."""
    try:
        url = ELCINEMA_AJAX + urllib.parse.quote(title)
        data = http_get_json(
            url,
            headers={
                "User-Agent": ELCINEMA_UA,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        if not data:
            return None

        query_norm = _norm_title(title)
        best = None
        best_score = 0

        for fragment in data:
            if 'data-entity="Work"' not in fragment:
                continue
            ids = re.findall(r'data-id="(\d+)"', fragment)
            if not ids:
                continue
            work_id = ids[0]

            # Extract all text hints
            texts = []
            for attr in ("data-text", "data-title", "title"):
                matches = re.findall(r'%s="([^"]+)"' % attr, fragment, re.I)
                texts.extend(matches)
            # Visible text
            visible = _strip_html(fragment)
            if visible:
                texts.append(visible)

            # Also try to get the title from the class="left" or class="right"
            for pattern in (
                r'class="left"[^>]*>([^<]+)<',
                r'class="right"[^>]*>([^<]+)<',
            ):
                for match in re.findall(pattern, fragment, re.I | re.S):
                    text = _strip_html(match)
                    if text:
                        texts.append(text)

            poster_match = re.search(r'<img[^>]+src="([^"]+)"', fragment, re.I)
            poster = poster_match.group(1) if poster_match else ""

            # Score each text – FULL SIMILARITY ONLY, no substring boost
            local_best = 0
            local_title = ""
            for found in texts:
                found = _strip_html(found)
                if not found:
                    continue
                found_norm = _norm_title(found)
                if not found_norm:
                    continue
                # Use full SequenceMatcher ratio (no substring bonus)
                ratio = SequenceMatcher(None, query_norm, found_norm).ratio() * 100
                # Penalize very long texts
                if len(found) > 200:
                    ratio -= 10
                if ratio > local_best:
                    local_best = ratio
                    local_title = found

            if local_best > best_score:
                best_score = local_best
                best = (work_id, local_title, poster)

        if best and best_score >= 75:
            # Never accept a merely similar ElCinema work for a multi-word title.
            # Exact normalized titles are preferred; otherwise require strong
            # token coverage as well as the similarity threshold.
            found_norm = _norm_title(best[1])
            exact = found_norm == query_norm
            q_tokens = set(query_norm.split())
            f_tokens = set(found_norm.split())
            coverage = len(q_tokens & f_tokens) / float(len(q_tokens) or 1)
            if exact or (len(q_tokens) >= 2 and coverage >= 0.80 and best_score >= 82):
                return best

    except Exception as e:
        warn("iDownloadThread", "elcinema-ajax-EX", str(e))
    return None

def _normalize_external_image_url(url):
    url = _text(url).strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://elcinema.com" + url
    return url

def _is_likely_poster_url(url):
    low = _text(url).lower()
    if not low:
        return False
    bad = ("blank", "placeholder", "default", "avatar", "logo", "icon", "banner")
    return not any(w in low for w in bad)

def _extract_elcinema_poster(page):
    if not page:
        return ""
    # 1. og:image
    match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page, re.I | re.S)
    if not match:
        match = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', page, re.I | re.S)
    if match:
        url = _normalize_external_image_url(match.group(1))
        if url and _is_likely_poster_url(url):
            return url
    # 2. Images with poster class
    for pattern in (
        r'<img[^>]+class="[^"]*(?:poster|work-image|photo)[^"]*"[^>]+src="([^"]+)"',
        r'<img[^>]+src="([^"]+)"[^>]+class="[^"]*(?:poster|work-image|photo)[^"]*"',
    ):
        for url in re.findall(pattern, page, re.I | re.S):
            url = _normalize_external_image_url(url)
            if url and _is_likely_poster_url(url):
                return url
    # 3. Any image that is not a thumbnail
    for src in re.findall(r'<img[^>]+src="([^"]+)"', page, re.I | re.S):
        url = _normalize_external_image_url(src)
        if url and _is_likely_poster_url(url):
            return url
    return ""

def _elcinema_work(work_id, need_backdrop=True):
    result = {
        "poster_url": "", "backdrop_url": "", "overview": "",
        "director": "", "cast": "", "year": "", "genres": "",
        "country": "", "category": "",
    }
    try:
        base = "https://elcinema.com/en/work/%s/" % work_id
        headers = {
            "User-Agent": ELCINEMA_UA,
            "Accept-Language": "ar,en;q=0.8",
        }
        page = _elcinema_fetch(base, headers)
        if not page:
            return result
        result["poster_url"] = _extract_elcinema_poster(page)
        if need_backdrop:
            gallery = _elcinema_fetch(base + "gallery/", headers)
            if gallery:
                for url in re.findall(r'<img[^>]+(?:src|data-src)="([^"]+)"', gallery, re.I):
                    url = _normalize_external_image_url(url)
                    low = url.lower()
                    if url and not any(w in low for w in ("blank", "placeholder", "/small/", "poster", "logo", "icon")):
                        result["backdrop_url"] = url
                        break
        match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', page, re.I)
        if match:
            result["overview"] = _strip_html(match.group(1))
        match = re.search(r'Director:\s*(?:</[a-z]+>\s*)?<a[^>]+href="[^"]*/person/\d+/"[^>]*>([^<]+)</a>', page, re.I | re.S)
        if match:
            result["director"] = _strip_html(match.group(1))
        cast = re.findall(r'<a[^>]+href="/[a-z]{2}/person/\d+/"[^>]*>([^<]+)</a>', page, re.I)
        names, seen = [], set()
        for name in cast:
            name = _strip_html(name)
            if name and name not in seen and name != result["director"]:
                seen.add(name)
                names.append(name)
        result["cast"] = ", ".join(names[:8])
        match = re.search(r'/release_year/(\d{4})/', page)
        if match:
            result["year"] = match.group(1)
        genres = re.findall(r'<a[^>]+href="[^"]*/genre/\d+"[^>]*>([^<]+)</a>', page, re.I)
        result["genres"] = " - ".join(g for g in (_strip_html(x) for x in genres) if g)[:500]
        match = re.search(r'Country:\s*(?:</[a-z]+>\s*)?<a[^>]+href="[^"]*/country/[a-z]+"[^>]*>([^<]+)</a>', page, re.I | re.S)
        if match:
            result["country"] = _strip_html(match.group(1))
        match = re.search(r'Category:\s*(?:</[a-z]+>\s*)?([A-Za-z]+)', page, re.I)
        if match:
            cat = match.group(1).lower()
            result["category"] = "tv" if cat.startswith("series") else "movie"
    except Exception as exc:
        warn("iDownloadThread", "elcinema-work-EX", str(exc))
    return result

def _elcinema_search(title, season_hint=None, need_backdrop=False):
    title = _text(title).strip()
    if not title:
        return None, "ELCIN_NO_QUERY"
    ajax = _elcinema_ajax_search(title)
    if not ajax:
        ajax = _elcinema_page_search(title)
    if not ajax:
        return None, "ELCIN_NO_MATCH"
    work_id, found_title, ajax_poster = ajax
    data = _elcinema_work(work_id, need_backdrop=need_backdrop)
    if not data["poster_url"] and ajax_poster and _is_likely_poster_url(ajax_poster):
        data["poster_url"] = _normalize_external_image_url(ajax_poster)
    if not data["poster_url"] and not data["overview"]:
        return None, "ELCIN_BAD_WORK"
    return {
        "status": "found",
        "poster_url": data["poster_url"],
        "backdrop_url": data["backdrop_url"],
        "logo_url": "",
        "vote_average": 0,
        "parental_rating": "",
        "genres": data["genres"],
        "year": data["year"],
        "overview": data["overview"],
        "director": data["director"],
        "cast": data["cast"],
        "country": data["country"],
        "title": found_title or title,
        "_media_id": work_id,
        "_media_type": data["category"] or "movie",
        "_fallback_source": "elcinema",
        "_season_hint": season_hint or 0,
    }, "ELCIN_FOUND"

def _elcinema_fallback(clean_title, raw_title, candidates, season_hint=None,
                       need_backdrop=False, secondary_title=None, episode_hint=None):
    # Keep ElCinema on the same identity policy as TMDB: one natural title
    # query first, with season/episode treated as context rather than title
    # text. A raw-title retry is retained only as a very small compatibility
    # fallback for feeds whose cleaner removed useful punctuation/wording.
    query = _build_search_identity(clean_title, secondary_title)
    queries = [query] if query else []
    base = re.sub(r"\s+", " ", _text(clean_title)).strip(" .,:;/-–—")
    if base and _norm_title(base) != _norm_title(query):
        queries.append(base)
    else:
        # Controlled fallback for common trailing-number/episode-title forms.
        m = re.match(r"^(.*?)(?:\s*[-–—]\s*|\s+)(\d{1,3})$", base)
        if m and len(_norm_title(m.group(1)).split()) >= 2:
            queries.append(m.group(1))

    last_reason = "ELCIN_NO_MATCH"
    for value in _unique(queries)[:3]:
        result, reason = _elcinema_search(
            value, season_hint=season_hint, need_backdrop=need_backdrop
        )
        if result:
            return result, "ELCIN_FOUND"
        last_reason = reason
    return None, last_reason

# ============================================================================
# CACHE / SEARCH
# ============================================================================

def _refresh_tmdb_season(data, season_hint):
    if not season_hint or not isinstance(data, dict):
        return data
    if data.get("_media_type") != "tv" or not data.get("_media_id"):
        return None
    poster = _fetch_tmdb_season_poster(
        data.get("_media_id"), season_hint, get_cfg("TMDB_LANGUAGE") or "en-US"
    )
    if not poster:
        return data
    updated = dict(data)
    updated["poster_url"] = _image_url(_poster_size(), poster)
    updated["_season_hint"] = season_hint
    return updated

def _find_metadata(clean_title, candidates, hint_year, emc_mode, raw_title=None, needed=None, secondary_title=None, season_hint=None, episode_hint=None, part_hint=None):
    store = get_state_store(emc_mode)
    needed = set(needed or ())
    season_hint = season_hint or _extract_season_hint(clean_title, candidates)

    cached = get_cached_search(clean_title)
    if isinstance(cached, dict):
        same_season = not season_hint or cached.get("_season_hint") == season_hint
        same_part = not part_hint or cached.get("_part_hint") == part_hint
        enough = not needed or all(cached.get("%s_url" % kind) for kind in needed)
        if same_season and same_part and enough:
            return cached, "CACHE_RAM"
        if season_hint and "poster" in needed and cached.get("_fallback_source") == "TMDB":
            refreshed = _refresh_tmdb_season(cached, season_hint)
            if refreshed is not None and refreshed.get("_season_hint") == season_hint:
                store.set_record(clean_title, "ok", refreshed)
                set_cached_search(clean_title, refreshed)
                return refreshed, "CACHE_REFRESH"
    # Do not let a 30-minute RAM negative result suppress a real retry.

    record = store.get(clean_title)
    if record:
        status = record.get("status")
        data = record.get("data") or {}
        if status == "ok":
            same_season = not season_hint or data.get("_season_hint") == season_hint
            same_part = not part_hint or data.get("_part_hint") == part_hint
            enough = not needed or all(data.get("%s_url" % kind) for kind in needed)
            if same_season and same_part and enough:
                set_cached_search(clean_title, data)
                return data, "CACHE_DB"
            if season_hint and "poster" in needed and data.get("_fallback_source") == "TMDB":
                refreshed = _refresh_tmdb_season(data, season_hint)
                if refreshed is not None and refreshed.get("_season_hint") == season_hint:
                    store.set_record(clean_title, "ok", refreshed)
                    set_cached_search(clean_title, refreshed)
                    return refreshed, "CACHE_DB_REFRESH"
            # ElCinema must be searched again when the requested season changed.
        elif status == "failed" and not (season_hint or part_hint) and not store.should_search(clean_title, still_needed=needed):
            _debug_log("CACHE", "negative-cache hit", clean_title=clean_title)
            return None, "CACHE_NEGATIVE"

    result, network_error, tmdb_reason = _tmdb_search_title(
        clean_title, candidates, hint_year, season_hint,
        raw_title=raw_title, secondary_title=secondary_title,
        episode_hint=episode_hint,
        part_hint=part_hint,
    )
    if result:
        store.set_record(clean_title, "ok", result)
        set_cached_search(clean_title, result)
        return result, tmdb_reason

    # ElCinema is a real fallback provider after a TMDB no-match. The fallback
    # is query-dynamic and bounded; it is not limited to Arabic-script events.
    # This catches Latin transliterations that exist on ElCinema but not TMDB.
    if not network_error:
        result, elcin_reason = _elcinema_fallback(
            clean_title, raw_title or clean_title, candidates, season_hint,
            need_backdrop=("backdrop" in needed),
            secondary_title=secondary_title, episode_hint=episode_hint,
        )
        if result:
            store.set_record(clean_title, "ok", result)
            set_cached_search(clean_title, result)
            return result, elcin_reason
        reason = elcin_reason
    else:
        reason = tmdb_reason

    if not network_error and not (season_hint or part_hint):
        store.mark_not_found(clean_title)
        # Negative RAM results should never mask a future real search for long.
        set_cached_search(clean_title, "NOT_FOUND")
    return None, reason

# ============================================================================
# IMAGE SAVE
# ============================================================================

def _resize_image(path, kind):
    if Image is None:
        return
    max_width = MAX_WIDTH.get(kind, 0)
    if not max_width:
        return
    image = None
    resized = None
    try:
        image = Image.open(path)
        width, height = image.size
        if width <= max_width:
            return
        new_height = max(1, int(height * max_width / float(width)))
        resized = image.resize((max_width, new_height), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
        if kind == "logo":
            if resized.mode not in ("RGBA", "LA"):
                resized = resized.convert("RGBA")
            resized.save(path, "PNG", optimize=True)
        else:
            if resized.mode not in ("RGB", "L"):
                resized = resized.convert("RGB")
            resized.save(path, "JPEG", quality=88, optimize=True)
    except Exception:
        pass
    finally:
        try:
            if resized is not None:
                resized.close()
        except Exception:
            pass
        try:
            if image is not None:
                image.close()
        except Exception:
            pass

def _valid_image(path):
    if not path:
        return False
    try:
        folder, filename = os.path.split(path)
        if not file_exists_indexed(folder, filename):
            return False
        return os.path.getsize(path) >= 256
    except Exception:
        return False

def _save_image(url, destination, kind):
    if not url or not destination:
        return "fail"
    data = http_get_binary(url, timeout=(T_CONN, T_IMG_LOGO if kind == "logo" else T_IMG_PIC), retries=1)
    if data is None:
        return "network"
    minimum = MIN_BYTES_LOGO if kind == "logo" else (MIN_BYTES_BACKDROP if kind == "backdrop" else MIN_BYTES_POSTER)
    if len(data) < minimum:
        return "fail"
    folder = os.path.dirname(destination)
    _safe_makedirs(folder)
    temp = destination + ".tmp.%s" % threading.get_ident()
    try:
        if Image is not None:
            import io
            image = None
            output_image = None
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
                width, height = image.size
                max_width = MAX_WIDTH.get(kind, 0)
                if max_width and width > max_width:
                    new_height = max(1, int(height * max_width / float(width)))
                    output_image = image.resize((max_width, new_height), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
                else:
                    output_image = image.copy()
                if kind == "logo":
                    if output_image.mode not in ("RGBA", "LA"):
                        output_image = output_image.convert("RGBA")
                    output_image.save(temp, "PNG", optimize=True)
                else:
                    if output_image.mode not in ("RGB", "L"):
                        output_image = output_image.convert("RGB")
                    output_image.save(temp, "JPEG", quality=88, optimize=True)
            finally:
                try:
                    if output_image is not None and output_image is not image:
                        output_image.close()
                except Exception:
                    pass
                try:
                    if image is not None:
                        image.close()
                except Exception:
                    pass
        else:
            with open(temp, "wb") as f:
                f.write(data)
                f.flush()
        if not _valid_image(temp):
            try:
                os.unlink(temp)
            except Exception:
                pass
            return "fail"
        os.replace(temp, destination)
        return "ok"
    except Exception:
        try:
            if os.path.exists(temp):
                os.unlink(temp)
        except Exception:
            pass
        return "fail"

# ============================================================================
# CALLBACKS / QUEUE
# ============================================================================

class PriorityJob:
    __slots__ = ("job", "priority")
    def __init__(self, job, priority):
        self.job = job
        self.priority = priority
    def __lt__(self, other):
        return self.priority < other.priority

work_queue = queue.PriorityQueue()
_pending = {}
_pending_lock = threading.Lock()
_callbacks = {}
_callback_lock = threading.Lock()
_download_stats = {"ok": 0, "fail": 0, "network": 0}
_download_notify_callbacks = []
_download_notify_lock = threading.Lock()

def register_asset_callback(kind, clean_title, renderer_obj):
    if kind not in ASSET_KINDS or not clean_title or renderer_obj is None:
        return
    key = (kind, clean_title)
    with _callback_lock:
        bucket = _callbacks.setdefault(key, [])
        if renderer_obj not in bucket:
            bucket.append(renderer_obj)

def unregister_asset_callback(kind, clean_title, renderer_obj):
    key = (kind, clean_title)
    with _callback_lock:
        bucket = _callbacks.get(key)
        if not bucket:
            return
        try:
            bucket.remove(renderer_obj)
        except ValueError:
            pass
        if not bucket:
            _callbacks.pop(key, None)

def _asset_ready(kind, clean_title, path):
    if not clean_title or not path or not os.path.exists(path):
        return
    key = (kind, clean_title)
    with _callback_lock:
        renderers = _callbacks.pop(key, None)
    if not renderers:
        return
    for renderer in renderers:
        try:
            queue_gui_callback(renderer.on_asset_ready, kind, clean_title, path)
        except Exception:
            pass

def _asset_unavailable(kind, clean_title):
    key = (kind, clean_title)
    with _callback_lock:
        renderers = _callbacks.pop(key, None)
    if not renderers:
        return
    for renderer in renderers:
        try:
            queue_gui_callback(renderer.on_asset_unavailable, kind, clean_title)
        except Exception:
            pass

def register_download_notify(callback):
    with _download_notify_lock:
        if callback not in _download_notify_callbacks:
            _download_notify_callbacks.append(callback)

def unregister_download_notify(callback):
    with _download_notify_lock:
        try:
            _download_notify_callbacks.remove(callback)
        except Exception:
            pass

def _download_result(kind, clean_title, status):
    with _download_notify_lock:
        _download_stats[status] = _download_stats.get(status, 0) + 1
        stats = dict(_download_stats)
        callbacks = list(_download_notify_callbacks)
    for cb in callbacks:
        try:
            queue_gui_callback(cb, kind, clean_title, status, stats)
        except Exception:
            pass

# ============================================================================
# PROCESS ONE TITLE
# ============================================================================

@traced("iDownloadThread")
def _process(job):
    clean_title = job["title"]
    raw_title = job.get("raw", clean_title)
    candidates = job.get("candidates", [clean_title])
    emc_mode = job.get("emc_mode", False)
    pending_key = job.get("_pending_key", (bool(emc_mode), clean_title, int(job.get("season_hint") or 0), int(job.get("part_hint") or 0)))
    requested = set(job.get("kinds", ASSET_KINDS))
    store = get_state_store(emc_mode)
    season_hint = job.get("season_hint") or _extract_season_hint(clean_title, candidates)
    episode_hint = job.get("episode_hint")
    part_hint = job.get("part_hint")
    secondary_title = job.get("secondary_title") or ""
    if not secondary_title and raw_title:
        try:
            profile = get_epg_title_profile(raw_title)
            secondary_title = (profile.get("secondary_title") or "")
            episode_hint = episode_hint or profile.get("episode")
            season_hint = season_hint or profile.get("season")
            part_hint = part_hint or profile.get("part")
        except Exception:
            pass

    folders = {
        "poster": get_poster_folder(),
        "backdrop": get_backdrop_folder(),
        "logo": get_logo_folder(),
    }
    extensions = {"poster": ".jpg", "backdrop": ".jpg", "logo": ".png"}
    paths = {}
    for kind in requested:
        paths[kind] = os.path.join(folders[kind], clean_title + extensions[kind])

    existing = {}
    for kind, path in paths.items():
        existing[kind] = _valid_image(path)
    if (season_hint or part_hint) and "poster" in requested:
        record = store.get(clean_title)
        data = record.get("data") if record and record.get("status") == "ok" else None
        if not isinstance(data, dict):
            existing["poster"] = False
        else:
            if season_hint and data.get("_season_hint") != season_hint:
                existing["poster"] = False
            if part_hint and data.get("_part_hint") != part_hint:
                existing["poster"] = False
    missing = {kind for kind in requested if not existing.get(kind)}
    if not missing:
        try:
            notify_metadata_ready(clean_title)
        except Exception:
            pass
        _release_pending(pending_key, job)
        return

    try:
        result, reason = _find_metadata(
            clean_title, candidates, job.get("hint_year"), emc_mode,
            raw_title=raw_title, needed=missing,
            secondary_title=secondary_title, season_hint=season_hint,
            episode_hint=episode_hint, part_hint=part_hint,
        )
        if not result:
            for kind in missing:
                _asset_unavailable(kind, clean_title)
            log_event(raw_title, clean_title, "not_found", source=reason)
            return

        downloaded = {"poster": False, "backdrop": False, "logo": False}

        # Poster
        if "poster" in missing and not existing.get("poster", False):
            url = result.get("poster_url")
            if url:
                status = _save_image(url, paths["poster"], "poster")
                _download_result("poster", clean_title, status)
                if status == "ok":
                    downloaded["poster"] = True
                    _asset_ready("poster", clean_title, paths["poster"])
                else:
                    _asset_unavailable("poster", clean_title)
            else:
                _asset_unavailable("poster", clean_title)

        # Backdrop
        if "backdrop" in missing and not existing.get("backdrop", False):
            url = result.get("backdrop_url")
            if url:
                status = _save_image(url, paths["backdrop"], "backdrop")
                _download_result("backdrop", clean_title, status)
                if status == "ok":
                    downloaded["backdrop"] = True
                    _asset_ready("backdrop", clean_title, paths["backdrop"])
                else:
                    _asset_unavailable("backdrop", clean_title)
            else:
                _asset_unavailable("backdrop", clean_title)

        # Logo
        if "logo" in missing and not existing.get("logo", False):
            url = result.get("logo_url")
            if url:
                status = _save_image(url, paths["logo"], "logo")
                _download_result("logo", clean_title, status)
                if status == "ok":
                    downloaded["logo"] = True
                    _asset_ready("logo", clean_title, paths["logo"])
                else:
                    _asset_unavailable("logo", clean_title)
            else:
                _asset_unavailable("logo", clean_title)

        try:
            notify_metadata_ready(clean_title)
        except Exception:
            pass

        source = result.get("_fallback_source", "TMDB")
        if get_cfg("LOG_FOUND_EVENTS"):
            log_event(
                raw_title, clean_title, "found",
                poster=existing.get("poster", False) or downloaded["poster"],
                backdrop=existing.get("backdrop", False) or downloaded["backdrop"],
                logo=existing.get("logo", False) or downloaded["logo"],
                meta=True,
                source="elcinema" if str(source).startswith("elcinema") else "TMDB",
            )

    except Exception as exc:
        err("iDownloadThread", "process-EX", "%s: %s" % (clean_title, exc))
        for kind in missing:
            _asset_unavailable(kind, clean_title)
    finally:
        _release_pending(pending_key, job)

def _release_pending(pending_key, job):
    with _pending_lock:
        if _pending.get(pending_key) is job:
            _pending.pop(pending_key, None)

# ============================================================================
# WORKER
# ============================================================================

def _worker():
    while True:
        item = None
        try:
            item = work_queue.get(timeout=1.0)
            if item is None:
                continue
            _process(item.job)
        except queue.Empty:
            continue
        except Exception as exc:
            err("iDownloadThread", "worker-EX", str(exc))
        finally:
            if item is not None:
                try:
                    work_queue.task_done()
                except Exception:
                    pass

def _worker_count():
    try:
        value = int(get_cfg("WORKER_THREADS") or MIN_WORKERS)
    except Exception:
        value = MIN_WORKERS
    return max(1, min(MAX_WORKERS, value))

def _init_workers():
    for i in range(_worker_count()):
        t = threading.Thread(target=_worker, name="XDREAMY-DL-%d" % (i+1))
        t.daemon = True
        t.start()

# ============================================================================
# QUEUE API
# ============================================================================

def _enabled_batch_kinds():
    kinds = set()
    if widget_present("poster") and get_cfg("POSTERX_ENABLED"):
        kinds.add("poster")
    if widget_present("backdrop") and get_cfg("BACKDROPX_ENABLED"):
        kinds.add("backdrop")
    if widget_present("logo") and get_cfg("LOGOX_ENABLED"):
        kinds.add("logo")
    return kinds

def _enqueue(clean_title, raw_name, candidates, emc_mode, priority=5, hint_year=None, kinds=None, season_hint=None, episode_hint=None, secondary_title=None, part_hint=None):
    if not clean_title:
        return False
    kinds = _enabled_batch_kinds() if kinds is None else set(kinds)
    kinds.intersection_update(ASSET_KINDS)
    if not kinds:
        return False
    candidate_list = _unique(candidates or [clean_title]) or [clean_title]
    pending_key = (
        bool(emc_mode),
        clean_title,
        int(season_hint or 0),
        int(part_hint or 0),
    )
    with _pending_lock:
        existing = _pending.get(pending_key)
        if existing is not None:
            existing["kinds"].update(kinds)
            if hint_year and not existing.get("hint_year"):
                existing["hint_year"] = hint_year
            if season_hint and not existing.get("season_hint"):
                existing["season_hint"] = season_hint
            if episode_hint and not existing.get("episode_hint"):
                existing["episode_hint"] = episode_hint
            if part_hint and not existing.get("part_hint"):
                existing["part_hint"] = part_hint
            if secondary_title and not existing.get("secondary_title"):
                existing["secondary_title"] = secondary_title
            existing["candidates"] = _unique(existing.get("candidates", []) + candidate_list)[:8]
            return True
        if len(_pending) >= MAX_PENDING:
            return False
        job = {
            "title": clean_title,
            "raw": raw_name or clean_title,
            "candidates": candidate_list,
            "emc_mode": bool(emc_mode),
            "kinds": set(kinds),
            "hint_year": hint_year,
            "season_hint": season_hint,
            "episode_hint": episode_hint,
            "part_hint": part_hint,
            "secondary_title": secondary_title or "",
            "_pending_key": pending_key,
        }
        _pending[pending_key] = job
        _debug_log("QUEUE", "enqueue key=%s kinds=%s" % (pending_key, sorted(kinds)), clean_title=clean_title)
        work_queue.put_nowait(PriorityJob(job, priority))
    return True

# ============================================================================
# PUBLIC API
# ============================================================================

def request_asset(clean_title, kind, raw_name=None, candidates=None, emc_mode=False, priority=5, hint_year=None):
    if not clean_title or kind not in ASSET_KINDS:
        return False
    secondary_title = None
    season_hint = None
    episode_hint = None
    part_hint = None
    if raw_name:
        try:
            profile = get_epg_title_profile(raw_name)
            secondary_title = profile.get("secondary_title") or ""
            season_hint = profile.get("season")
            episode_hint = profile.get("episode")
            part_hint = profile.get("part")
        except Exception:
            pass
    return _enqueue(
        clean_title, raw_name, candidates, emc_mode, priority, hint_year,
        kinds=(kind,), season_hint=season_hint, episode_hint=episode_hint,
        secondary_title=secondary_title, part_hint=part_hint,
    )

def request_batch(items, kinds=None, emc_mode=False, priority=5):
    kinds = _enabled_batch_kinds() if kinds is None else set(kinds)
    kinds.intersection_update(ASSET_KINDS)
    if not kinds:
        return
    for item in items:
        if len(item) >= 8:
            clean, raw, candidates, year, season, episode, secondary, part = item[:8]
        elif len(item) >= 7:
            clean, raw, candidates, year, season, episode, secondary = item[:7]
            part = None
        elif len(item) >= 4:
            clean, raw, candidates, year = item[:4]
            season, episode, secondary, part = None, None, "", None
        else:
            clean, raw, candidates = item[:3]
            year = None
            season, episode, secondary, part = None, None, "", None
        _enqueue(
            clean, raw, candidates, emc_mode, priority, year, kinds=kinds,
            season_hint=season, episode_hint=episode, secondary_title=secondary,
            part_hint=part,
        )

# ============================================================================
# iConverlibr CALLBACK
# ============================================================================

set_batch_request_fn(lambda missing: request_batch(missing, emc_mode=False))

# ============================================================================
# START WORKERS
# ============================================================================

_init_workers()