#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
iPosterXDownloadThread.py

Poster manager (background):
 - single shared queue 'pdb' (Renderer imports this)
 - parallel provider search (fast first)
 - safe JPG save/verify/resize
 - PosterIndex integration
 - PosterAutoDB autoscan (moved here)
 - compact logging with rotation
"""

from __future__ import absolute_import
import os, sys, re, threading, json, unicodedata, random, time, traceback

from PIL import Image
try:
    from enigma import getDesktop
except Exception:
    getDesktop = None

# requests may not be available in test env; plugin should have it
try:
    from requests import get, exceptions
except Exception:
    def get(*a, **kw):
        raise Exception("requests required")
    class exceptions:
        RequestException = Exception

try:
    from twisted.internet.reactor import callInThread
except Exception:
    callInThread = None

from .iConverlibr import quoteEventName, convtext, cutName, REGEX, init_poster_index, poster_index_add, poster_index_get_fullpath

PY3 = sys.version_info[0] >= 3
if PY3:
    from urllib.parse import quote as urlquote
else:
    from urllib import quote as urlquote

# ---------------------------
# Storage path & index init
# ---------------------------
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

# init index
init_poster_index(path_folder, max_entries=50000)

# ---------------------------
# API keys (kept)
# ---------------------------
tmdb_api   = "3c3efcf47c3577558812bb9d64019d65"
omdb_api   = "6a4c9432"
thetvdbkey = "a99d487bb3426e5f3a60dea6d3d3c7ef"
fanart_api = "6d231536dea4318a88cb2520ce89473b"
# ---------------------------
# sizing and timeouts
# ---------------------------
try:
    if getDesktop:
        screenwidth = getDesktop(0).size()
        width_val = screenwidth.width()
    else:
        width_val = 1280
    if width_val <= 1280:
        isz = "185,278"
    elif width_val <= 1920:
        isz = "342,514"
    else:
        isz = "780,1170"
except Exception:
    isz = "342,514"

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/91.0',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) Chrome/36.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) Safari/534.57.2',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/99.0',
]

PROVIDER_CONNECT_TIMEOUT = 0.5
PROVIDER_READ_TIMEOUT    = 0.5
DOWNLOAD_CONNECT_TIMEOUT = 1.0
DOWNLOAD_READ_TIMEOUT    = 2.0
MIN_VALID_SIZE           = 4 * 1024

# ---------------------------
# Compact log with rotation
# ---------------------------
LOG_PATH = "/tmp/iPosterX.log"
LOG_MAX_LINES = 2000
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_LOCK = threading.Lock()

def _rotate_log(path=LOG_PATH):
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) > LOG_MAX_BYTES:
            with open(path, "rb") as f:
                f.seek(-LOG_MAX_BYTES//2, os.SEEK_END)
                tail = f.read()
            with open(path, "wb") as f:
                f.write(tail)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            tail = lines[-(LOG_MAX_LINES//2):]
            with open(path, "w", encoding="utf-8", errors="ignore") as f:
                f.writelines(tail)
    except Exception:
        pass

def log(message, kind="INFO", tag=None):
    try:
        with LOG_LOCK:
            _rotate_log(LOG_PATH)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            tagpart = "[%s] " % tag if tag else ""
            line = "[%s] [%s] %s%s\n" % (ts, kind, tagpart, str(message))
            with open(LOG_PATH, "a", encoding="utf-8", errors="ignore") as f:
                f.write(line)
    except Exception:
        pass

def getRandomUserAgent():
    try:
        return random.choice(UA_POOL)
    except Exception:
        return UA_POOL[0]

# ---------------------------
# Shared queue and inflight dedupe
# ---------------------------
try:
    if PY3:
        import queue
        pdb = queue.LifoQueue()
    else:
        import Queue as queue
        pdb = queue.LifoQueue()
except Exception:
    import collections
    pdb = collections.deque()

_inflight = set()
_inflight_lock = threading.Lock()

# ---------------------------
# Poster manager thread
# ---------------------------
class iPosterXDownloadThread(threading.Thread):
    def __init__(self, autoscan_interval=10):
        threading.Thread.__init__(self)
        self.daemon = True
        self.adsl = self._internet_check()
        self.autoscan_interval = int(autoscan_interval)
        log("Poster manager starting (internet=%s)" % str(self.adsl), "INFO", "Downloader")

    def _internet_check(self):
        try:
            if PY3:
                from urllib.request import urlopen
            else:
                from urllib2 import urlopen
            urlopen("http://clients3.google.com/generate_204", timeout=2).close()
            return True
        except Exception:
            return False

    # ---------- save pipeline ----------
    def savePoster(self, url, callback, cleaned_title=None, source=None):
        try:
            headers = {"User-Agent": getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT))
            resp.raise_for_status()
            tmp = callback + ".part"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            if os.path.getsize(tmp) < MIN_VALID_SIZE:
                try: os.remove(tmp)
                except Exception: pass
                log("download too small -> removed: %s" % tmp, "ERROR", "Downloader")
                return False
            try:
                img = Image.open(tmp)
                img_format = getattr(img, "format", "").upper()
                if img_format != "JPEG":
                    rgb = img.convert("RGB")
                    rgb.save(callback, format="JPEG", quality=88)
                    rgb.close()
                    img.close()
                    try: os.remove(tmp)
                    except Exception: pass
                else:
                    try:
                        os.replace(tmp, callback)
                    except Exception:
                        img.save(callback, format="JPEG", quality=88)
                        img.close()
                        try: os.remove(tmp)
                        except Exception: pass
            except Exception as e:
                try: os.replace(tmp, callback)
                except Exception:
                    try: os.remove(tmp)
                    except Exception: pass
                    log("PIL save error: %s" % e, "ERROR", "Downloader")
                    return False
            ok = self.verifyPoster(callback)
            if not ok:
                log("verifyPoster failed: %s" % callback, "ERROR", "Downloader")
                return False
            try:
                self.resizePoster(callback)
            except Exception:
                pass
            try:
                if cleaned_title:
                    poster_index_add(cleaned_title, source if source else "remote")
            except Exception:
                pass
            log("Saved poster: %s" % callback, "INFO", "Downloader")
            return True
        except exceptions.RequestException as e:
            log("Failed to fetch poster: %s" % str(e), "ERROR", "Downloader")
            return False
        except Exception as e:
            log("Unexpected savePoster error: %s" % str(e), "ERROR", "Downloader")
            return False

    def verifyPoster(self, dwn_poster):
        try:
            img = Image.open(dwn_poster)
            img.verify()
            return True
        except Exception:
            try: os.remove(dwn_poster)
            except Exception: pass
            return False

    def resizePoster(self, dwn_poster):
        try:
            img = Image.open(dwn_poster)
            width, height = img.size
            if height == 0:
                img.close()
                return
            new_height = int(isz.split(",")[1])
            ratio = float(width) / float(height)
            new_width = max(1, int(ratio * new_height))
            rimg = img.resize((new_width, new_height), Image.LANCZOS)
            rimg.save(dwn_poster, format="JPEG", quality=88)
            img.close(); rimg.close()
        except Exception:
            pass

    # ---------- providers ----------
    def provider_tmdb(self, title, shortdesc, fulldesc):
        try:
            if not title: return False, None
            url = "https://api.themoviedb.org/3/search/multi?api_key={}&language=en&query={}".format(tmdb_api, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT), verify=False)
            if not resp.ok: return False, None
            data = resp.json()
            for each in data.get('results', []):
                if each.get('poster_path'):
                    poster = "http://image.tmdb.org/t/p/w500" + each['poster_path']
                    return True, poster
            return False, None
        except Exception:
            return False, None

    def provider_imdb(self, title, shortdesc, fulldesc):
        try:
            if not title: return False, None
            first = title[0].lower()
            url = "https://v2.sg.media-imdb.com/suggestion/{}/{}.json".format(first, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok: return False, None
            data = resp.json()
            for it in data.get('d', []):
                img = it.get('i')
                if img and isinstance(img, (list, tuple)) and img[0].startswith('http'):
                    return True, img[0]
            return False, None
        except Exception:
            return False, None

    def provider_omdb(self, title, shortdesc, fulldesc):
        try:
            if not title: return False, None
            url = "http://www.omdbapi.com/?apikey={}&t={}".format(omdb_api, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok: return False, None
            data = resp.json()
            poster = data.get('Poster')
            if poster and poster != 'N/A':
                return True, poster
            return False, None
        except Exception:
            return False, None

    def provider_web(self, title, shortdesc, fulldesc):
        try:
            if not title: return False, None
            q = urlquote(title + " poster")
            url = "https://www.bing.com/images/search?q=%s&ensearch=1" % q
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok: return False, None
            txt = resp.text
            m = re.search(r'murl&quot;:&quot;(https?:\/\/[^&quot;]+)', txt)
            if m:
                return True, m.group(1)
            return False, None
        except Exception:
            return False, None

    # ---------- parallel search ----------
    def parallel_search_and_save(self, dwn_poster, title, shortdesc, fulldesc):
        stop_flag = {"stop": False}
        winner = {"url": None, "provider": None}
        lock = threading.Lock()
        def worker(fn, name):
            try:
                ok, poster = fn(title, shortdesc, fulldesc)
                if not ok or not poster: return
                with lock:
                    if stop_flag["stop"]: return
                    stop_flag["stop"] = True
                    winner["url"] = poster
                    winner["provider"] = name
                    if callInThread:
                        try:
                            callInThread(self.savePoster, poster, dwn_poster, title, name)
                        except Exception:
                            t = threading.Thread(target=self.savePoster, args=(poster, dwn_poster, title, name))
                            t.daemon = True; t.start()
                    else:
                        t = threading.Thread(target=self.savePoster, args=(poster, dwn_poster, title, name))
                        t.daemon = True; t.start()
            except Exception:
                pass

        providers = [
            (self.provider_tmdb, "tmdb"),
            (self.provider_imdb, "imdb"),
            (self.provider_omdb, "omdb"),
            (self.provider_web, "web"),
        ]

        threads = []
        for fn, name in providers:
            t = threading.Thread(target=worker, args=(fn, name))
            t.daemon = True
            t.start()
            threads.append(t)

        for t in threads:
            try: t.join(0.25)
            except Exception: pass

        return winner["url"] is not None

    # ---------- autoscan worker (scans bouquet files, similar to old behavior) ----------
    def autoscan_scan_bouquets(self):
        import glob
        apdb_local = {}
        bouquet_files = glob.glob("/etc/enigma2/*.tv")
        if not bouquet_files:
            return {}
        for bq in bouquet_files:
            try:
                with open(bq, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("#SERVICE"):
                            ref = line[9:].strip()
                            if ref and ref not in apdb_local:
                                apdb_local[ref] = ref
            except Exception:
                pass
        return apdb_local

    def run_autoscan(self):
        log("AutoDB starting", "INFO", "AutoDB")
        while True:
            try:
                apdb = self.autoscan_scan_bouquets()
                if not apdb:
                    log("AutoDB: no bouquet files found", "INFO", "AutoDB")
                for service in list(apdb.values()):
                    try:
                        # use 'IBDCTESX' first (works for some platforms), fallback to 'IDT'
                        try:
                            events = []
                            try:
                                from enigma import eEPGCache
                                events = eEPGCache.getInstance().lookupEvent(['IBDCTESX', (service, 0, -1, 1440)])
                            except Exception:
                                events = eEPGCache.getInstance().lookupEvent(['IDT', (service, 0, -1, 1440)])
                        except Exception:
                            events = []
                        newfd = 0
                        newcn = None
                        for evt in events:
                            try:
                                # guard against missing fields
                                if evt is None or len(evt) < 6:
                                    continue
                                # event fields: (eventid, begin, duration, ...)
                                # create canal similar to renderer expectations
                                canal = [None] * 6
                                try:
                                    from ServiceReference import ServiceReference
                                    canal[0] = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                                except Exception:
                                    canal[0] = service
                                canal[1:6] = [evt[1], evt[4], evt[5], evt[6], evt[4]]
                                cleaned = convtext(canal[5]) if canal[5] else None
                                if not cleaned:
                                    continue
                                dwn_poster = os.path.join(path_folder, cleaned + ".jpg")
                                if os.path.exists(dwn_poster):
                                    try: os.utime(dwn_poster, None)
                                    except Exception: pass
                                else:
                                    shortdesc = canal[4] if canal[4] else None
                                    fulldesc = canal[3] if canal[3] else None
                                    ok = self.parallel_search_and_save(dwn_poster, cleaned, shortdesc, fulldesc)
                                    if ok:
                                        newfd += 1
                                newcn = canal[0]
                            except Exception:
                                continue
                        if newfd > 0:
                            log("%d new file(s) added (%s)" % (newfd, newcn), "INFO", "AutoDB")
                    except Exception:
                        pass
                # Cleanup old/empty files to avoid disk growth
                now_tm = time.time()
                emptyfd = 0; oldfd = 0
                try:
                    for f in os.listdir(path_folder):
                        file_path = os.path.join(path_folder, f)
                        try:
                            diff_tm = now_tm - os.path.getmtime(file_path)
                        except Exception:
                            continue
                        if diff_tm > 120 and os.path.getsize(file_path) == 0:
                            try:
                                os.remove(file_path); emptyfd += 1
                            except Exception:
                                pass
                        elif diff_tm > 63072000:
                            try:
                                os.remove(file_path); oldfd += 1
                            except Exception:
                                pass
                except Exception:
                    pass
                # wait interval
                time.sleep(max(5, self.autoscan_interval))
            except Exception as e:
                log("AutoDB exception: %s" % str(e), "ERROR", "AutoDB")
                time.sleep(max(5, self.autoscan_interval))

    # ---------- main run loop (queue worker) ----------
    def run(self):
        # Start autoscan as background thread (daemon) from here to keep single worker file
        try:
            t_auto = threading.Thread(target=self.run_autoscan)
            t_auto.daemon = True
            t_auto.start()
        except Exception:
            pass

        log("Poster manager ready", "INFO", "Downloader")
        while True:
            canal = None
            try:
                canal = pdb.get()
            except Exception:
                try:
                    canal = pdb.pop()
                except Exception:
                    time.sleep(0.1)
                    continue

            try:
                raw_event = canal[5] if canal and len(canal) > 5 else None
                if not raw_event:
                    try:
                        pdb.task_done()
                    except Exception: pass
                    continue

                title_v1 = convtext(raw_event)
                if not title_v1:
                    try:
                        pdb.task_done()
                    except Exception: pass
                    continue

                dwn_poster_v1 = os.path.join(path_folder, title_v1 + ".jpg")

                # dedupe inflight saves
                with _inflight_lock:
                    if title_v1 in _inflight:
                        try:
                            pdb.task_done()
                        except Exception: pass
                        continue
                    _inflight.add(title_v1)

                # quick cache/index check
                got = False
                try:
                    mapped = poster_index_get_fullpath(title_v1)
                    if mapped and os.path.exists(mapped):
                        log("Cache hit: %s" % title_v1, "INFO", "Downloader")
                        try: os.utime(mapped, None)
                        except Exception: pass
                        got = True
                    elif os.path.exists(dwn_poster_v1):
                        log("File exists: %s" % title_v1, "INFO", "Downloader")
                        try: os.utime(dwn_poster_v1, None)
                        except Exception: pass
                        poster_index_add(title_v1, "local")
                        got = True
                except Exception:
                    got = False

                if not got:
                    try:
                        shortdesc = canal[4] if len(canal) > 4 else None
                        fulldesc = canal[3] if len(canal) > 3 else None
                        found = self.parallel_search_and_save(dwn_poster_v1, title_v1, shortdesc, fulldesc)
                        if not found:
                            log("Failed to fetch poster: %s" % title_v1, "ERROR", "AutoDB")
                    except Exception as e:
                        log("Provider search exception: %s" % str(e), "ERROR", "Downloader")

                with _inflight_lock:
                    try: _inflight.discard(title_v1)
                    except Exception: pass

                try: pdb.task_done()
                except Exception: pass

            except Exception as e:
                log("Worker exception: %s" % str(e), "ERROR", "Downloader")
                try: pdb.task_done()
                except Exception: pass
