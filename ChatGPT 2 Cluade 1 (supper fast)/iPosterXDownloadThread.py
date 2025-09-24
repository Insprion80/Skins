#!/usr/bin/python
# -*- coding: utf-8 -*-

# iPosterX Download Thread — single source of truth:
# - ONE shared queue 'pdb' (imported by renderer)
# - Parallel provider search per event with early-cancel on first success
# - Safe JPG output (PIL convert), size/verify checks
# - Minimal changes to keep Enigma2 compatibility and behavior
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
import glob
import codecs

from PIL import Image
from enigma import getDesktop, eEPGCache
from requests import get, exceptions
from twisted.internet.reactor import callInThread
from ServiceReference import ServiceReference

# import index and conversion helpers
from .iConverlibr import quoteEventName, convtext, cutName, REGEX, init_poster_index, poster_index_add, poster_index_get_fullpath

PY3 = sys.version_info[0] >= 3
if PY3:
    import html
    from urllib.parse import quote as urlquote
    import queue
else:
    from HTMLParser import HTMLParser
    html = HTMLParser()
    from urllib import quote as urlquote
    import Queue as queue

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

# -------- Networking tuning --------
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/91.0',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) Chrome/36.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) Safari/534.57.2',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/99.0',
]

PROVIDER_CONNECT_TIMEOUT = 3.0             # faster connect cutoff
PROVIDER_READ_TIMEOUT    = 5.0             # don't wait long for slow providers
DOWNLOAD_CONNECT_TIMEOUT = 3.0             # poster image fetch must connect fast
DOWNLOAD_READ_TIMEOUT    = 8.0             # allow a bit more for image download
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
    """Compact logger with autotruncate."""
    try:
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
        pdb = queue.LifoQueue()
    else:
        pdb = queue.LifoQueue()
except Exception:
    # very defensive
    import collections
    pdb = collections.deque()

# -------- Bouquet Processing --------
apdb = dict()
epgcache = eEPGCache.getInstance()

def process_autobouquet():
    """
    Build a dict of all service refs from all TV bouquets.
    """
    global apdb
    bouquet_files = glob.glob("/etc/enigma2/*.tv")

    if not bouquet_files:
        log("No bouquet files found in /etc/enigma2/", "WARN")
        return {}

    log("Scanning bouquets: %s" % str(bouquet_files))

    for bq in bouquet_files:
        try:
            with codecs.open(bq, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("#SERVICE"):
                        ref = line[9:].strip()
                        if ref and ref not in apdb:
                            apdb[ref] = ref
        except Exception as e:
            log("Error reading bouquet %s: %s" % (bq, e), "ERROR")

    log("Found %d valid services from bouquets" % len(apdb))
    return apdb

# build database immediately
apdb = process_autobouquet()

class iPosterXDownloadThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.adsl = intCheck()
        if self.adsl:
            log("Download thread: internet available")
        else:
            log("Download thread: offline (will only use cache)")

    # ---------- Helpers ----------
    def savePoster(self, url, callback, cleaned_title=None):
        """
        Download poster and ensure it is a JPG saved at 'callback' path.
        If remote is PNG or other, convert with PIL to JPEG (RGB).
        cleaned_title (optional) will be registered into the PosterIndex on success.
        """
        log("Downloading poster from: %s" % url)
        try:
            headers = {"User-Agent": getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT))
            resp.raise_for_status()

            tmp = callback + ".part"
            with open(tmp, "wb") as f:
                f.write(resp.content)

            if os.path.getsize(tmp) < MIN_VALID_SIZE:
                log("Download too small, removing: %s" % tmp, "WARN")
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
                    log("Failed to save poster: %s" % callback, "ERROR")
                    return callback

            ok = self.verifyPoster(callback)
            if ok:
                log("Successfully downloaded poster: %s" % callback)
                # Update index
                try:
                    if cleaned_title:
                        poster_index_add(cleaned_title, os.path.basename(callback))
                except Exception:
                    pass
            else:
                log("Poster verification failed: %s" % callback, "WARN")
            return callback

        except exceptions.RequestException as e:
            log("Download error: %s" % e, "ERROR")
            return callback
        except Exception as e:
            log("Unexpected error in savePoster: %s" % e, "ERROR")
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

    # ---------- Providers ----------
    def provider_tmdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, "[SKIP tmdb] empty title", None
            url = "https://api.themoviedb.org/3/search/multi?api_key={}&language=en&query={}".format(tmdb_api, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT), verify=False)
            if not resp.ok:
                return False, "[SKIP tmdb] http %s" % resp.status_code, None
            data = resp.json()
            for each in data.get('results', []):
                if each.get('media_type') in ('movie', 'tv') and each.get('poster_path'):
                    poster = "http://image.tmdb.org/t/p/w500" + each['poster_path']
                    return True, "[SUCCESS tmdb] %s => %s" % (title, poster), poster
            return False, "[SKIP tmdb] not found", None
        except Exception as e:
            return False, "[ERROR tmdb] %s" % e, None

    def provider_omdb(self, title, shortdesc, fulldesc):
        try:
            if not title:
                return False, "[SKIP omdb] empty title", None
            url = "http://www.omdbapi.com/?apikey={}&t={}".format(omdb_api, urlquote(title))
            headers = {'User-Agent': getRandomUserAgent()}
            resp = get(url, headers=headers, timeout=(PROVIDER_CONNECT_TIMEOUT, PROVIDER_READ_TIMEOUT))
            if not resp.ok:
                return False, "[SKIP omdb] http %s" % resp.status_code, None
            data = resp.json()
            poster = data.get('Poster')
            if poster and poster != 'N/A':
                return True, "[SUCCESS omdb] %s => %s" % (title, poster), poster
            return False, "[SKIP omdb] not found", None
        except Exception as e:
            return False, "[ERROR omdb] %s" % e, None

    # ---------- Parallel search controller ----------
    def parallel_search_and_save(self, dwn_poster, title, shortdesc, fulldesc):
        """
        Search providers for poster and download if found.
        Returns True if a poster download was successful or already exists.
        """
        if not self.adsl:
            log("No internet connection, skipping search for: %s" % title, "WARN")
            return False

        # Try TMDB first
        ok, logmsg, poster_url = self.provider_tmdb(title, shortdesc, fulldesc)
        log(logmsg)
        if ok and poster_url:
            callInThread(self.savePoster, poster_url, dwn_poster, title)
            return True

        # Try OMDB as fallback
        ok, logmsg, poster_url = self.provider_omdb(title, shortdesc, fulldesc)
        log(logmsg)
        if ok and poster_url:
            callInThread(self.savePoster, poster_url, dwn_poster, title)
            return True

        log("No poster found for: %s" % title, "WARN")
        return False

    # ---------- Queue worker ----------
    def run(self):
        log("iPosterX download thread started")
        while True:
            try:
                canal = pdb.get(timeout=1)
                try:
                    raw_event = canal[5] if canal and len(canal) > 5 else None
                    if not raw_event:
                        log("No event title found in queue item", "WARN")
                        try:
                            pdb.task_done()
                        except Exception:
                            pass
                        continue

                    # Clean the title
                    title_clean = convtext(raw_event)
                    if not title_clean:
                        log("convtext returned empty for: %s" % raw_event, "WARN")
                        try:
                            pdb.task_done()
                        except Exception:
                            pass
                        continue

                    dwn_poster = os.path.join(path_folder, title_clean + ".jpg")
                    shortdesc = canal[4] if canal and len(canal) > 4 else None
                    fulldesc = canal[3] if canal and len(canal) > 3 else None

                    log("Processing: '%s' -> '%s'" % (raw_event, title_clean))

                    # Check if poster already exists
                    if os.path.exists(dwn_poster):
                        try:
                            os.utime(dwn_poster, (time.time(), time.time()))
                        except Exception:
                            pass
                        log("Poster already exists: %s" % dwn_poster)
                    else:
                        # Check poster index for existing mapping
                        try:
                            indexed = poster_index_get_fullpath(title_clean)
                            if indexed and os.path.exists(indexed):
                                try:
                                    os.utime(indexed, (time.time(), time.time()))
                                except Exception:
                                    pass
                                log("Found indexed poster: %s" % indexed)
                            else:
                                # Search and download new poster
                                self.parallel_search_and_save(dwn_poster, title_clean, shortdesc, fulldesc)
                        except Exception as e:
                            log("Error checking index: %s" % e, "ERROR")

                    try:
                        pdb.task_done()
                    except Exception:
                        pass

                except Exception as e:
                    log("Error processing queue item: %s" % e, "ERROR")
                    try:
                        pdb.task_done()
                    except Exception:
                        pass

            except Exception:
                # Queue timeout, continue
                continue

# Auto scanner for EPG events
class PosterAutoDB(iPosterXDownloadThread):
    def __init__(self):
        iPosterXDownloadThread.__init__(self)
        log("Auto scanner initialized")

    def run(self):
        log("Auto poster scanner started")
        time.sleep(10)  # Wait 1 minute before starting
        
        while True:
            try:
                log("Starting EPG scan for missing posters")
                events_processed = 0
                posters_queued = 0
                
                # Scan all services in bouquets
                for service in apdb.values():
                    try:
                        # Get events for next 24 hours
                        events = epgcache.lookupEvent(['IBDCTESX', (service, 0, -1, 1440)])
                        
                        for evt in events:
                            try:
                                if evt[4]:  # Has title
                                    events_processed += 1
                                    
                                    # Get service name
                                    try:
                                        canal_name = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                                        if not PY3:
                                            canal_name = canal_name.encode('utf-8')
                                    except Exception:
                                        canal_name = "Unknown"
                                    
                                    # Check if poster exists
                                    clean_title = convtext(evt[4])
                                    if clean_title:
                                        poster_path = os.path.join(path_folder, clean_title + ".jpg")
                                        indexed_path = poster_index_get_fullpath(clean_title)
                                        
                                        if not (indexed_path and os.path.exists(indexed_path)) and not os.path.exists(poster_path):
                                            # Queue for download
                                            canal_data = [
                                                canal_name,
                                                evt[1],  # start time
                                                evt[4],  # title
                                                evt[5],  # long desc
                                                evt[6],  # short desc
                                                evt[4]   # title again
                                            ]
                                            
                                            try:
                                                pdb.put(canal_data, block=False)
                                                posters_queued += 1
                                            except Exception:
                                                pass  # Queue full
                            except Exception as e:
                                log("Error processing event: %s" % e, "ERROR")
                    
                    except Exception as e:
                        log("Error processing service %s: %s" % (service, e), "ERROR")
                
                log("EPG scan complete: %d events, %d queued" % (events_processed, posters_queued))
                
                # Cleanup old posters
                self.cleanup_old_posters()
                
                # Wait 2 (7200)hours before next scan
                time.sleep(10)
                
            except Exception as e:
                log("Auto scanner error: %s" % e, "ERROR")
                time.sleep(300)  # Wait 5 minutes on error

    def cleanup_old_posters(self):
        """Remove old unused poster files."""
        if not os.path.exists(path_folder):
            return
        
        current_time = time.time()
        cleaned_count = 0
        
        try:
            for filename in os.listdir(path_folder):
                if not filename.endswith('.jpg'):
                    continue
                
                filepath = os.path.join(path_folder, filename)
                try:
                    # Remove files older than 30 days not accessed in 7 days if file_age > (30 * 24 * 3600) and access_age > (7 * 24 * 3600):)
                    file_age = current_time - os.path.getmtime(filepath)
                    access_age = current_time - os.path.getatime(filepath)
                    
                    if file_age > (30 * 24 * 3600) and access_age > (30 * 24 * 3600):
                        os.remove(filepath)
                        cleaned_count += 1
                    # Remove empty files
                    elif os.path.getsize(filepath) == 0:
                        os.remove(filepath)
                        cleaned_count += 1
                
                except Exception:
                    continue
        
        except Exception as e:
            log("Cleanup error: %s" % e, "ERROR")
        
        if cleaned_count > 0:
            log("Cleaned up %d old poster files" % cleaned_count)

# Module-level initialization
log("iPosterXDownloadThread module loaded, folder: %s" % path_folder)