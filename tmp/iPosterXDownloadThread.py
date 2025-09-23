#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
iPosterXDownloadThread.py

Background poster downloader (single shared queue).
Behavior highlights:
 - Shared LIFO queue 'pdb' (Renderer imports it)
 - Provider order: TMDB, IMDB, TVDB, OMDB, FANART (parallel)
 - If parallel providers fail => single WEB fallback
 - Autoscan: implemented in PosterAutoDB (when used)
 - Minimal logging: only successful saves (INFO) and final failures (ERROR)
 - Autoscan sleep = 600 seconds (configurable below)
 - Each poster search retries up to 3 tries
"""

from __future__ import absolute_import
import os, sys, re, threading, time, random, traceback
from PIL import Image
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

from .iConverlibr import convtext, convtext_fallback, init_poster_index, poster_index_add, poster_index_get_fullpath

PY3 = sys.version_info[0] >= 3
if PY3:
    from urllib.parse import quote as urlquote
else:
    from urllib import quote as urlquote

# ---------------------------
# Storage path & index init
# ---------------------------
path_folder = "/tmp/XDREAMY/poster"
for mount in ("/media/hdd", "/media/usb", "/media/mmc"):
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

init_poster_index(path_folder, max_entries=50000)

# ---------------------------
# API keys (unchanged)
# ---------------------------
tmdb_api   = "3c3efcf47c3577558812bb9d64019d65"
omdb_api   = "6a4c9432"
# fanart key not required for lightweight web probing

# ---------------------------
# Sizes & timeouts
# ---------------------------
PROVIDER_CONNECT_TIMEOUT = 0.5
PROVIDER_READ_TIMEOUT    = 0.6
DOWNLOAD_CONNECT_TIMEOUT = 1.0
DOWNLOAD_READ_TIMEOUT    = 2.0
MIN_VALID_SIZE           = 4 * 1024

# autoscan sleep (seconds)
AUTOSCAN_SLEEP = 10

# logging primitives (minimal)
LOG_PATH = "/tmp/iPosterX.log"
LOG_LOCK = threading.Lock()
LOG_MAX_LINES = 2000
LOG_MAX_BYTES = 10 * 1024 * 1024

def _rotate_log():
    try:
        if not os.path.exists(LOG_PATH):
            return
        if os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            with open(LOG_PATH, "rb") as f:
                f.seek(-LOG_MAX_BYTES // 2, os.SEEK_END)
                tail = f.read()
            with open(LOG_PATH, "wb") as f:
                f.write(tail)
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            tail = lines[-(LOG_MAX_LINES // 2):]
            with open(LOG_PATH, "w", encoding="utf-8", errors="ignore") as f:
                f.writelines(tail)
    except Exception:
        pass

def log(message, level="INFO", tag=None):
    # minimal single-line logging
    try:
        with LOG_LOCK:
            _rotate_log()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            tagpart = "[%s] " % tag if tag else ""
            with open(LOG_PATH, "a", encoding="utf-8", errors="ignore") as f:
                f.write("[%s] [%s] %s%s\n" % (ts, level, tagpart, str(message)))
    except Exception:
        pass

def intCheck():
    # exported for renderer to check connectivity if needed
    try:
        if PY3:
            from urllib.request import urlopen
        else:
            from urllib2 import urlopen
        urlopen("http://clients3.google.com/generate_204", timeout=2).close()
        return True
    except Exception:
        return False

# ---------------------------
# Shared queue
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

# inflight set to avoid duplicated saves for same cleaned title
_inflight = set()
_inflight_lock = threading.Lock()

# ---------------------------
# Download thread
# ---------------------------
class iPosterXDownloadThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.internet = intCheck()
        log("Poster manager starting (internet=%s)" % str(self.internet), "INFO", "Downloader")

    # ----------------- save poster with retries -----------------
    def savePoster(self, url, callback, cleaned_title=None, source=None):
        # retry loop (3 tries)
        tries = 3
        last_exc = None
        for attempt in range(tries):
            try:
                headers = {"User-Agent": self._user_agent()}
                resp = get(url, headers=headers, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT))
                resp.raise_for_status()
                tmp = callback + ".part"
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                if os.path.getsize(tmp) < MIN_VALID_SIZE:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                    last_exc = "too small"
                    continue
                # ensure JPEG via PIL
                try:
                    img = Image.open(tmp)
                    fmt = getattr(img, "format", "").upper()
                    if fmt != "JPEG":
                        rgb = img.convert("RGB")
                        rgb.save(callback, "JPEG", quality=88)
                        rgb.close()
                        img.close()
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                    else:
                        try:
                            os.replace(tmp, callback)
                        except Exception:
                            img.save(callback, "JPEG", quality=88)
                            img.close()
                            try:
                                os.remove(tmp)
                            except Exception:
                                pass
                except Exception:
                    # fallback try rename
                    try:
                        os.replace(tmp, callback)
                    except Exception:
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                        last_exc = "PIL save error"
                        continue
                # verify
                if not self._verify(callback):
                    last_exc = "verify failed"
                    try:
                        os.remove(callback)
                    except Exception:
                        pass
                    continue
                # resized
                try:
                    self._resize(callback)
                except Exception:
                    pass
                # index update
                try:
                    if cleaned_title:
                        poster_index_add(cleaned_title, source or "remote")
                except Exception:
                    pass
                # success log (minimal)
                log("Saved poster: %s" % callback, "INFO", "Downloader")
                return True
            except exceptions.RequestException as e:
                last_exc = e
                # do not spam low-level errors; try again
                time.sleep(0.15)
                continue
            except Exception as e:
                last_exc = e
                time.sleep(0.15)
                continue
        # final failure logged once
        log("Failed to fetch poster: %s" % str(cleaned_title or callback), "ERROR", "Downloader")
        return False

    def _user_agent(self):
        UA_POOL = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/91.0',
            'Mozilla/5.0 (Windows NT 6.1; WOW64) Chrome/36.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) Safari/534.57.2',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/99.0',
        ]
        try:
            return random.choice(UA_POOL)
        except Exception:
            return UA_POOL[0]

    def _verify(self, path):
        try:
            img = Image.open(path)
            img.verify()
            return True
        except Exception:
            try:
                os.remove(path)
            except Exception:
                pass
            return False

    def _resize(self, path):
        try:
            img = Image.open(path)
            w, h = img.size
            if h == 0:
                img.close()
                return
            # choose target height conservatively
            target_h = 278
            ratio = float(w) / float(h)
            new_w = max(1, int(ratio * target_h))
            r = img.resize((new_w, target_h), Image.LANCZOS)
            r.save(path, "JPEG", quality=88)
            img.close(); r.close()
        except Exception:
            pass

    # ----------------- providers -----------------
    def provider_tmdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, None
            q = urlquote(title)
            url = "https://api.themoviedb.org/3/search/multi?api_key={}&language=en&query={}".format(tmdb_api, q)
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT), verify=False)
            if not resp.ok:
                return False, None
            data = resp.json()
            for it in data.get('results', []):
                if it.get('poster_path'):
                    return True, "http://image.tmdb.org/t/p/w500" + it['poster_path']
            return False, None
        except Exception:
            return False, None

    def provider_imdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, None
            first = title[0].lower()
            url = "https://v2.sg.media-imdb.com/suggestion/{}/{}.json".format(first, urlquote(title))
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, None
            data = resp.json()
            for it in data.get('d', []):
                img = it.get('i')
                if img and isinstance(img, (list, tuple)) and img[0].startswith('http'):
                    return True, img[0]
            return False, None
        except Exception:
            return False, None

    def provider_tvdb(self, title, shortdesc, fulldesc):
        # lightweight HTML probe for poster image in TVDB search page
        try:
            if not title:
                return False, None
            q = urlquote(title)
            url = "https://thetvdb.com/search?query=%s" % q
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, None
            txt = resp.text
            m = re.search(r'<img[^>]+src="([^"]+/banners/[^"]+)"', txt)
            if m:
                p = m.group(1)
                if p.startswith("//"):
                    p = "https:" + p
                elif p.startswith("/"):
                    p = "https://thetvdb.com" + p
                return True, p
            return False, None
        except Exception:
            return False, None

    def provider_omdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, None
            url = "http://www.omdbapi.com/?apikey={}&t={}".format(omdb_api, urlquote(title))
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, None
            data = resp.json()
            poster = data.get('Poster')
            if poster and poster != 'N/A':
                return True, poster
            return False, None
        except Exception:
            return False, None

    def provider_fanart(self, title, shortdesc, fulldesc):
        # quick web probe (duckduckgo) for fanart assets
        try:
            if not title:
                return False, None
            q = urlquote(title + " fanart.tv poster")
            url = "https://duckduckgo.com/html/?q=%s" % q
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, None
            txt = resp.text
            m = re.search(r'https?://assets\.fanart\.tv/[^"\']+\.jpg', txt)
            if m:
                return True, m.group(0)
            return False, None
        except Exception:
            return False, None

    def provider_web(self, title, shortdesc, fulldesc):
        # single fallback web probe (bing images)
        try:
            if not title:
                return False, None
            q = urlquote(title + " poster")
            url = "https://www.bing.com/images/search?q=%s&ensearch=1" % q
            resp = get(url, headers={"User-Agent": self._user_agent()}, timeout=(1.2, 1.0))
            if not resp.ok:
                return False, None
            txt = resp.text
            m = re.search(r'murl&quot;:&quot;(https?:\/\/[^&quot;]+)', txt)
            if m:
                return True, m.group(1)
            return False, None
        except Exception:
            return False, None

    # parallel search (TMDB,IMDB,TVDB,OMDB,FANART). web is NOT part of this parallel set.
    def parallel_search_and_save(self, dwn_poster, title, shortdesc, fulldesc):
        stop = {"flag": False}
        lock = threading.Lock()
        result = {"url": None, "provider": None}

        def worker(fn, name):
            try:
                ok, poster = fn(title, shortdesc, fulldesc)
                if not ok or not poster:
                    return
                with lock:
                    if stop["flag"]:
                        return
                    stop["flag"] = True
                    result["url"] = poster
                    result["provider"] = name
                    # call save asynchronously
                    if callInThread:
                        callInThread(self.savePoster, poster, dwn_poster, title, name)
                    else:
                        t = threading.Thread(target=self.savePoster, args=(poster, dwn_poster, title, name))
                        t.daemon = True
                        t.start()
            except Exception:
                pass

        providers = [
            (self.provider_tmdb, "tmdb"),
            (self.provider_imdb, "imdb"),
            (self.provider_tvdb, "tvdb"),
            (self.provider_omdb, "omdb"),
            (self.provider_fanart, "fanart"),
        ]
        threads = []
        for fn, name in providers:
            t = threading.Thread(target=worker, args=(fn, name))
            t.daemon = True
            t.start()
            threads.append(t)

        # wait briefly to let fast providers return
        for t in threads:
            try:
                t.join(0.25)
            except Exception:
                pass

        return result["url"] is not None

    # ----------------- main loop -----------------
    def run(self):
        log("Poster manager ready", "INFO", "Downloader")
        while True:
            item = None
            try:
                item = pdb.get()
            except Exception:
                try:
                    item = pdb.pop()
                except Exception:
                    time.sleep(0.1)
                    continue

            try:
                raw_event = item[5] if item and len(item) > 5 else None
                if not raw_event:
                    # nothing to do
                    try:
                        pdb.task_done()
                    except Exception:
                        pass
                    continue

                # derive cleaned title
                title_v1 = convtext(raw_event)
                if not title_v1:
                    # try fallback
                    title_v1 = convtext_fallback(raw_event)
                    if not title_v1:
                        try:
                            pdb.task_done()
                        except Exception:
                            pass
                        continue

                dwn_path = os.path.join(path_folder, title_v1 + ".jpg")

                # inflight dedupe
                with _inflight_lock:
                    if title_v1 in _inflight:
                        try:
                            pdb.task_done()
                        except Exception:
                            pass
                        continue
                    _inflight.add(title_v1)

                # quick check: index or local file
                got = False
                try:
                    mapped = poster_index_get_fullpath(title_v1)
                    if mapped and os.path.exists(mapped):
                        try:
                            os.utime(mapped, None)
                        except Exception:
                            pass
                        got = True
                    elif os.path.exists(dwn_path):
                        try:
                            os.utime(dwn_path, None)
                        except Exception:
                            pass
                        poster_index_add(title_v1, "local")
                        got = True
                except Exception:
                    got = False

                # try up to 3 attempts (as requested)
                if not got:
                    tries = 3
                    found_any = False
                    for attempt in range(tries):
                        # parallel providers
                        found = self.parallel_search_and_save(dwn_path, title_v1,
                                                              item[4] if len(item) > 4 else None,
                                                              item[3] if len(item) > 3 else None)
                        if found:
                            found_any = True
                            break
                        # if parallel failed, do web fallback ONCE per attempt (lightweight)
                        web_ok, web_url = self.provider_web(title_v1, item[4] if len(item) > 4 else None, item[3] if len(item) > 3 else None)
                        if web_ok and web_url:
                            # schedule save
                            if callInThread:
                                callInThread(self.savePoster, web_url, dwn_path, title_v1, "web")
                            else:
                                t = threading.Thread(target=self.savePoster, args=(web_url, dwn_path, title_v1, "web"))
                                t.daemon = True
                                t.start()
                            found_any = True
                            break
                        # small wait before next attempt
                        time.sleep(0.5)
                    if not found_any:
                        log("Failed to fetch poster: %s" % title_v1, "ERROR", "AutoDB")

                # done with this job
                with _inflight_lock:
                    try:
                        _inflight.discard(title_v1)
                    except Exception:
                        pass
                try:
                    pdb.task_done()
                except Exception:
                    pass

            except Exception as e:
                log("Worker exception: %s" % str(e), "ERROR", "Downloader")
                try:
                    pdb.task_done()
                except Exception:
                    pass

# AutoDB worker (optional). When instantiated it will periodically scan bouquets/services.
class PosterAutoDB(threading.Thread):
    def __init__(self, scan_interval=AUTOSCAN_SLEEP):
        threading.Thread.__init__(self)
        self.daemon = True
        self.scan_interval = int(scan_interval)
        self.running = True
        log("AutoDB starting", "INFO", "AutoDB")

    def run(self):
        # The higher-level scanning logic belongs in the renderer (or system) which knows the services.
        # This simple auto-scan loop sleeps between cycles to avoid consuming box resources.
        while self.running:
            try:
                # Placeholder: actual scan logic (populating pdb) should be called from outside
                time.sleep(self.scan_interval)
            except Exception:
                time.sleep(self.scan_interval)

# Exported helpers for other modules (renderer)
dl_log = log
# Expose queue and intCheck
# (renderer imports pdb and dl_log and can call intCheck())
# End of iPosterXDownloadThread.py
