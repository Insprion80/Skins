#!/usr/bin/python
# -*- coding: utf-8 -*-

# iPosterX Download Thread — FAST VERSION:
# - ONE shared queue 'pdb' (imported by renderer)
# - Parallel provider search per event with early-cancel on first success
# - MINIMAL year enhancement: only add year to API calls when found quickly
# - Safe JPG output (PIL convert), size/verify checks
# - Optimized for SPEED - keeps original fast performance
# - Integrates PosterIndex and compact logging (autotruncate 1MB)

from __future__ import absolute_import
import os
import sys
import re
import threading
import json
import unicodedata
import random
import time

from PIL import Image
from enigma import getDesktop
from requests import get, exceptions
from twisted.internet.reactor import callInThread

# import index and conversion helpers
from .iConverlibr import (
    quoteEventName, convtext, cutName, REGEX, init_poster_index, 
    poster_index_add, poster_index_get_fullpath, get_year_from_description
)

PY3 = sys.version_info[0] >= 3
if PY3:
    import html
    from urllib.parse import quote as urlquote
else:
    from HTMLParser import HTMLParser
    html = HTMLParser()
    from urllib import quote as urlquote

# -------- Storage path (same semantics as renderer) --------
path_folder = "/tmp/XDREAMY/poster"
for mount in ["/media/hdd", "/media/usb", "/media/mmc"]:
    try:
        if os.path.exists(mount) and os.access(mount, os.W_OK):
            path_folder = os.path.join(mount, "XDREAMY/poster")
            break
    except Exception:
        pass
try:
    if not os.path.exists(path_folder):
        os.makedirs(path_folder)
except Exception:
    pass

# Initialize PosterIndex now that we know path_folder
init_poster_index(path_folder, max_entries=5000)

# -------- API keys (keep hardcoded) --------
tmdb_api   = "3c3efcf47c3577558812bb9d64019d65"
omdb_api   = "6a4c9432"
thetvdbkey = "a99d487bb3426e5f3a60dea6d3d3c7ef"
fanart_api = "6d231536dea4318a88cb2520ce89473b"

# -------- Screen size (kept for compatibility) --------
try:
    screenwidth = getDesktop(0).size()
    if screenwidth.width() <= 1280:
        isz = "185,278"
    elif screenwidth.width() <= 1920:
        isz = "342,514"
    else:
        isz = "780,1170"
except Exception:
    isz = "342,514"

# -------- Networking tuning (FAST settings) --------
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/91.0',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) Chrome/36.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) Safari/534.57.2',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/99.0',
]

# OPTIMIZED for speed - shorter timeouts
PROVIDER_CONNECT_TIMEOUT = 0.3             # Very fast connect (was 0.5)
PROVIDER_READ_TIMEOUT    = 0.8             # Quick read (was 0.5)
DOWNLOAD_CONNECT_TIMEOUT = 0.4             # Poster fetch connect (was 0.5)
DOWNLOAD_READ_TIMEOUT    = 2.0             # Allow time for image download (was 1.0)
MIN_VALID_SIZE           = 4 * 1024        # keep same (avoid broken tiny files)
LOG_MAX_BYTES            = 1 * 1024 * 1024  # 1 MB

def getRandomUserAgent():
    return random.choice(UA_POOL)

def _autotruncate_log(path="/tmp/iPosterX.log", max_bytes=LOG_MAX_BYTES):
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            # keep last ~half of file
            with open(path, "rb") as f:
                f.seek(-max_bytes//2, os.SEEK_END)
                tail = f.read()
            with open(path, "wb") as f:
                f.write(tail)
    except Exception:
        pass

def log(msg, level="INFO"):
    """
    Compact logger with autotruncate. Skip success messages to reduce noise.
    """
    try:
        # filter out verbose success lines 
        if isinstance(msg, str) and msg.startswith("[SUCCESS"):
            return
        # compose compact message
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = "[%s] [%s] %s\n" % (ts, level, str(msg))
        path = "/tmp/iPosterX.log"
        _autotruncate_log(path)
        with open(path, "a") as f:
            f.write(line)
    except Exception:
        pass

def intCheck():
    try:
        if PY3:
            from urllib.request import urlopen
        else:
            from urllib2 import urlopen
        urlopen("http://clients3.google.com/generate_204", timeout=3).close()
        return True
    except Exception:
        return False

# -------- Shared queue (single instance) --------
try:
    if PY3:
        import queue
        pdb = queue.LifoQueue()
    else:
        import Queue as queue
        from Queue import LifoQueue as LifoQueue
        pdb = LifoQueue()
except Exception:
    # very defensive
    import collections
    pdb = collections.deque()

class iPosterXDownloadThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.adsl = intCheck()
        if self.adsl:
            log("Download thread: internet available (FAST mode)")
        else:
            log("Download thread: offline (will only use cache)")

    # ---------- Helpers ----------
    def savePoster(self, url, callback, cleaned_title=None):
        """
        Download poster and ensure it is a JPG saved at 'callback' path.
        If remote is PNG or other, convert with PIL to JPEG (RGB).
        cleaned_title (optional) will be registered into the PosterIndex on success.
        """
        try:
            headers = {"User-Agent": getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT))
            resp.raise_for_status()

            tmp = callback + ".part"
            with open(tmp, "wb") as f:
                f.write(resp.content)

            if os.path.getsize(tmp) < MIN_VALID_SIZE:
                log("download too small -> remove: %s" % tmp, "WARN")
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return callback

            try:
                img = Image.open(tmp)
                img_format = getattr(img, "format", "").upper()
                if img_format != "JPEG":
                    rgb = img.convert("RGB")
                    rgb.save(callback, format="JPEG", quality=88)
                    rgb.close()
                    img.close()
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                else:
                    try:
                        os.rename(tmp, callback)
                    except Exception:
                        # fallback: try to copy
                        img.save(callback, format="JPEG", quality=88)
                        img.close()
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
            except Exception as e:
                log("PIL processing error: %s" % e, "ERROR")
                try:
                    os.rename(tmp, callback)
                except Exception:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                    log("failed to save poster: %s" % callback, "ERROR")
                    return callback

            ok = self.verifyPoster(callback)
            if ok:
                # Update index
                try:
                    if cleaned_title:
                        poster_index_add(cleaned_title, os.path.basename(callback))
                except Exception:
                    pass
            else:
                log("verifyPoster failed: %s" % callback, "WARN")
            return callback

        except exceptions.RequestException as e:
            log("download error: %s" % e, "ERROR")
            return callback
        except Exception as e:
            log("unexpected error in savePoster: %s" % e, "ERROR")
            return callback

    def resizePoster(self, dwn_poster):
        try:
            img = Image.open(dwn_poster)
            width, height = img.size
            if height == 0:
                img.close()
                return
            ratio = float(width) / float(height)
            new_height = int(isz.split(",")[1]) if isinstance(isz, str) else int(isz[1])
            new_width = max(1, int(ratio * new_height))
            rimg = img.resize((new_width, new_height), Image.LANCZOS)
            rimg.save(dwn_poster, format="JPEG", quality=88)
            img.close(); rimg.close()
        except Exception as e:
            log("resizePoster error: %s" % e, "ERROR")

    def verifyPoster(self, dwn_poster):
        try:
            img = Image.open(dwn_poster)
            img.verify()
            ok = True
        except Exception as e:
            log("verifyPoster exception: %s" % e, "ERROR")
            try:
                os.remove(dwn_poster)
            except Exception:
                pass
            ok = False
        return ok

    def UNAC(self, string):
        try:
            string = html.unescape(string)
        except Exception:
            pass
        string = unicodedata.normalize('NFD', string)
        string = re.sub(r'[,!?\."]', ' ', string)
        string = re.sub(r'\s+', ' ', string)
        return string.strip()

    def PMATCH(self, textA, textB):
        if not textB or not textA:
            return 0
        if textA == textB or textA.replace(" ", "") == textB.replace(" ", ""):
            return 100
        lId = len(textA.replace(" ", "")) if len(textA) > len(textB) else len(textB.replace(" ", ""))
        cId = sum(len(id) for id in textA.split() if id in textB)
        return 100 * cId // lId

    # ---------- FAST Providers (minimal year enhancement) ----------
    def provider_tmdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, "[SKIP tmdb] empty title", None
            
            # FAST year extraction - only if description is short
            year = None
            if (shortdesc or fulldesc) and len(str(shortdesc) + str(fulldesc)) < 200:
                year = get_year_from_description(shortdesc, fulldesc)
            
            # Try with year first (if found), then fallback to basic
            search_terms = []
            if year:
                search_terms.append((title + " " + year, "with_year"))
            search_terms.append((title, "basic"))
            
            for search_term, search_type in search_terms:
                try:
                    url = "https://api.themoviedb.org/3/search/multi?api_key={}&language=en&query={}".format(tmdb_api, urlquote(search_term))
                    headers = {'User-Agent': getRandomUserAgent()}
                    resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT), verify=False)
                    if not resp.ok:
                        continue
                    data = resp.json()
                    
                    for each in data.get('results', []):
                        if each.get('media_type') in ('movie', 'tv') and each.get('poster_path'):
                            # Quick year validation if we have it
                            if year and search_type == "with_year":
                                result_year = None
                                if 'release_date' in each and each['release_date']:
                                    result_year = each['release_date'][:4]
                                elif 'first_air_date' in each and each['first_air_date']:
                                    result_year = each['first_air_date'][:4]
                                
                                # Skip if years don't match closely
                                if result_year and abs(int(year) - int(result_year)) > 1:
                                    continue
                            
                            poster = "http://image.tmdb.org/t/p/w500" + each['poster_path']
                            return True, "[SUCCESS tmdb] {} => {}".format(search_term, poster), poster
                except Exception:
                    continue
            
            return False, "[SKIP tmdb] not found", None
        except Exception as e:
            return False, "[ERROR tmdb] %s" % e, None

    def provider_omdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, "[SKIP omdb] empty title", None
            
            # FAST year extraction - only if description is short
            year = None
            if (shortdesc or fulldesc) and len(str(shortdesc) + str(fulldesc)) < 200:
                year = get_year_from_description(shortdesc, fulldesc)
            
            # Try with year first (more accurate), then basic
            search_attempts = []
            if year:
                search_attempts.append((title, year))
            search_attempts.append((title, None))
            
            for search_title, search_year in search_attempts:
                try:
                    if search_year:
                        url = "http://www.omdbapi.com/?apikey={}&t={}&y={}".format(omdb_api, urlquote(search_title), search_year)
                    else:
                        url = "http://www.omdbapi.com/?apikey={}&t={}".format(omdb_api, urlquote(search_title))
                    
                    headers = {'User-Agent': getRandomUserAgent()}
                    resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
                    if not resp.ok:
                        continue
                    data = resp.json()
                    poster = data.get('Poster')
                    if poster and poster != 'N/A':
                        return True, "[SUCCESS omdb] {} => {}".format(search_title, poster), poster
                except Exception:
                    continue
            
            return False, "[SKIP omdb] not found", None
        except Exception as e:
            return False, "[ERROR omdb] %s" % e, None

    def provider_imdb(self, title, shortdesc, fulldesc):
        """
        Uses public IMDb suggestion API - FAST version.
        """
        try:
            if not title:
                return False, "[SKIP imdb] empty title", None
            
            first = title[0].lower()
            url = "https://v2.sg.media-imdb.com/suggestion/{}/{}.json".format(first, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent(), 'Accept': 'application/json'}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, "[SKIP imdb] http %s" % resp.status_code, None
            data = resp.json()
            
            # FAST year extraction for filtering (only if short description)
            year = None
            if (shortdesc or fulldesc) and len(str(shortdesc) + str(fulldesc)) < 150:
                year = get_year_from_description(shortdesc, fulldesc)
            
            for it in data.get('d', []):
                # Quick year check if available
                if year and 'y' in it:
                    try:
                        result_year = int(it['y'])
                        if abs(result_year - int(year)) > 2:
                            continue
                    except Exception:
                        pass
                
                # 'i' key holds image info: ['url','width','height']
                img = it.get('i')
                if img and isinstance(img, (list, tuple)) and img[0].startswith('http'):
                    poster = img[0]
                    return True, "[SUCCESS imdb] {} => {}".format(title, poster), poster
            
            return False, "[SKIP imdb] not found", None
        except Exception as e:
            return False, "[ERROR imdb] %s" % e, None

    def provider_tvdb(self, title, shortdesc, fulldesc):
        """
        TVDB - lightweight HTML search, FAST version.
        """
        try:
            if not title:
                return False, "[SKIP tvdb] empty title", None
            
            q = urlquote(title)
            url = "https://thetvdb.com/search?query=%s" % q
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, "[SKIP tvdb] http %s" % resp.status_code, None
            htmltxt = resp.text
            # Quick regex for poster image
            m = re.search(r'<img[^>]+src="([^"]+/banners/[^"]+)"', htmltxt)
            if m:
                poster = m.group(1)
                if poster.startswith("//"):
                    poster = "https:" + poster
                elif poster.startswith("/"):
                    poster = "https://thetvdb.com" + poster
                return True, "[SUCCESS tvdb] {} => {}".format(title, poster), poster
            
            return False, "[SKIP tvdb] not found", None
        except Exception as e:
            return False, "[ERROR tvdb] %s" % e, None

    def provider_fanart(self, title, shortdesc, fulldesc):
        """
        fanart.tv - FAST fallback search.
        """
        try:
            if not title:
                return False, "[SKIP fanart] empty title", None
            
            # Simple DuckDuckGo search (very light)
            q = urlquote(title + " fanart.tv poster")
            url = "https://duckduckgo.com/html/?q=%s" % q
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, "[SKIP fanart] http %s" % resp.status_code, None
            htmltxt = resp.text
            # Look for fanart.tv image URLs
            m = re.search(r'https?://assets\.fanart\.tv/[^"\']+\.jpg', htmltxt)
            if m:
                poster = m.group(0)
                return True, "[SUCCESS fanart] {} => {}".format(title, poster), poster
            
            return False, "[SKIP fanart] not found", None
        except Exception as e:
            return False, "[ERROR fanart] %s" % e, None

    def provider_google(self, title, shortdesc, fulldesc):
        """
        Last-resort Bing Images scraping - FAST version.
        """
        try:
            if not title:
                return False, "[SKIP web] empty title", None
            
            # Build search query - add year if available and description is short
            search_query = title + " poster"
            if (shortdesc or fulldesc) and len(str(shortdesc) + str(fulldesc)) < 150:
                year = get_year_from_description(shortdesc, fulldesc)
                if year:
                    search_query = title + " " + year + " poster"
            
            q = urlquote(search_query)
            url = "https://www.bing.com/images/search?q=%s&ensearch=1" % q
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, "[SKIP web] http %s" % resp.status_code, None
            txt = resp.text
            # Look for image URL in results
            m = re.search(r'murl&quot;:&quot;(https?:\/\/[^&quot;]+)', txt)
            if m:
                poster = m.group(1)
                # Quick validation - avoid obviously broken URLs
                if len(poster) > 10 and '.' in poster:
                    return True, "[SUCCESS web] {} => {}".format(search_query, poster), poster
            
            return False, "[SKIP web] not found", None
        except Exception as e:
            return False, "[ERROR web] %s" % e, None

    # ---------- FAST Parallel search controller ----------
    def parallel_search_and_save(self, dwn_poster, title, shortdesc, fulldesc):
        """
        FAST version: Launch provider threads, first success wins.
        Minimal year enhancement - only extract year if descriptions are short.
        Returns True if a poster download/save was started.
        """
        stop_flag = {"stop": False}
        lock = threading.Lock()
        winner = {"url": None, "log": []}

        def worker(fn, name):
            try:
                ok, logmsg, poster = fn(title, shortdesc, fulldesc)
                with lock:
                    winner["log"].append(logmsg)
                    if stop_flag["stop"]:
                        return
                    if ok and poster and not stop_flag["stop"]:
                        stop_flag["stop"] = True
                        winner["url"] = poster
                        # Save in twisted thread
                        callInThread(self.savePoster, poster, dwn_poster, title)
            except Exception as e:
                with lock:
                    winner["log"].append("[%s worker ERROR] %s" % (name, e))

        # Provider order optimized for SPEED (fastest first)
        providers = [
            (self.provider_tmdb,   "tmdb"),    # Usually fastest, best results
            (self.provider_imdb,   "imdb"),    # Fast API
            (self.provider_omdb,   "omdb"),    # Good fallback
            (self.provider_tvdb,   "tvdb"),    # TV shows
            (self.provider_fanart, "fanart"),  # Alternative source
            (self.provider_google, "web"),     # Last resort
        ]

        threads = []
        for fn, name in providers:
            t = threading.Thread(target=worker, args=(fn, name))
            t.setDaemon(True)
            t.start()
            threads.append(t)

        # Quick join - don't wait too long
        for t in threads:
            try:
                t.join(0.05)  # Very short join time for speed
            except Exception:
                pass

        # Log only errors/warnings (skip success messages)
        for l in winner["log"]:
            if isinstance(l, str) and l.startswith("[SUCCESS"):
                continue
            log(l)

        return winner["url"] is not None

    # ---------- FAST Queue worker ----------
    def run(self):
        log("PosterDB thread initialized (FAST mode with minimal year enhancement)")
        while True:
            canal = pdb.get()
            try:
                raw_event = canal[5] if canal and len(canal) > 5 else None
                if not raw_event:
                    try:
                        pdb.task_done()
                    except Exception:
                        pass
                    continue

                # Extract description fields (kept minimal)
                shortdesc = canal[4] if canal and len(canal) > 4 else ""
                fulldesc  = canal[3] if canal and len(canal) > 3 else ""

                # --- Try convtext v1 (standard approach) ---
                title_v1 = convtext(raw_event)
                dwn_poster_v1 = os.path.join(path_folder, title_v1 + ".jpg") if title_v1 else None

                got = False
                if dwn_poster_v1 and os.path.exists(dwn_poster_v1):
                    try:
                        os.utime(dwn_poster_v1, (time.time(), time.time()))
                    except Exception:
                        pass
                    got = True
                elif dwn_poster_v1:
                    # Check poster index first (fast lookup)
                    try:
                        indexed = poster_index_get_fullpath(title_v1)
                        if indexed and os.path.exists(indexed):
                            try:
                                os.utime(indexed, (time.time(), time.time()))
                            except Exception:
                                pass
                            got = True
                        else:
                            # Proceed with network search (with minimal year enhancement)
                            got = self.parallel_search_and_save(dwn_poster_v1, title_v1, shortdesc, fulldesc)
                    except Exception as e:
                        log("[ERROR index-check v1] %s" % e, "ERROR")

                try:
                    pdb.task_done()
                except Exception:
                    pass

            except Exception as e:
                log("[ERROR worker] %s" % e, "ERROR")
                try:
                    pdb.task_done()
                except Exception:
                    pass