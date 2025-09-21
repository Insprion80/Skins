#!/usr/bin/python
# -*- coding: utf-8 -*-

# by digiteng...07.2021,
# 08.2021(stb lang support),
# 09.2021 mini fixes
# edit by lululla 07.2022
# recode from lululla 2023
# small fixes for immediate noposter + logging by ChatGPT 2025
# Cleanup: remove duplicate PosterDB; use the single worker/queue from iPosterXDownloadThread
# Fix: guard against NoneType paths in waitPoster and generatePosterPath

from __future__ import print_function
from Components.Renderer.Renderer import Renderer
from Components.Sources.CurrentService import CurrentService
from Components.Sources.Event import Event
from Components.Sources.EventInfo import EventInfo
from Components.Sources.ServiceEvent import ServiceEvent
from Components.config import config
from ServiceReference import ServiceReference
from enigma import (
    ePixmap,
    loadJPG,
    eEPGCache,
    eTimer,
)
import NavigationInstance
import os
import socket
import sys
import time
import traceback
import datetime
from .iConverlibr import convtext, cutName, REGEX, poster_index_get_fullpath, init_poster_index

# ---- Import the ONE queue + worker base from download thread file
from Components.Renderer.iPosterXDownloadThread import (
    iPosterXDownloadThread,
    pdb,                  # shared LIFO queue
    path_folder as dl_folder,
    log as dl_log
)

PY3 = sys.version_info[0] >= 3
if PY3:
    from _thread import start_new_thread
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen
else:
    from thread import start_new_thread
    from urllib2 import HTTPError, URLError
    from urllib2 import urlopen

epgcache = eEPGCache.getInstance()

def isMountedInRW(mount_point):
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 1 and parts[1] == mount_point:
                    return True
    except Exception:
        pass
    return False

cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')

# skin noposter path (expected by your skins)
noposter = "/usr/share/enigma2/%s/main/noposter.jpg" % cur_skin

# poster folder: prefer the same as download thread's computed folder
path_folder = dl_folder
if not os.path.exists(path_folder):
    try:
        os.makedirs(path_folder)
    except Exception:
        pass

# Initialize poster index with same path (safe to call multiple times)
try:
    init_poster_index(path_folder, max_entries=50000)
except Exception:
    pass

# ------------------------------------------------------------------
# NOTE: keep the existing SearchBouquetTerrestrial helper in case other code references it.
# It returns the *file contents* in your original, so we leave it as-is (harmless),
# but the universal process_autobouquet() below will scan all *.tv files instead.
# ------------------------------------------------------------------
apdb = dict()

try:
    lng = config.osd.language.value
    lng = lng[:-3]
except Exception:
    lng = 'en'

def SearchBouquetTerrestrial():
    import glob
    import codecs
    file = '/etc/enigma2/userbouquet.favourites.tv'
    for file in sorted(glob.glob('/etc/enigma2/*.tv')):
        try:
            with codecs.open(file, "r", encoding="utf-8") as f:
                filec = f.read()
                x = filec.strip().lower()
                # this was original heuristic — keep unchanged
                if x.find('eeee') != -1:
                    if x.find('82000') == -1 and x.find('c0000') == -1:
                        return filec
                        break
        except Exception:
            pass
    return None

# keep global flag used elsewhere to indicate if we found bouquets at startup.
autobouquet_file = None
autobouquet_file_found = False

# ------------------------------------------------------------------
# Universal process_autobouquet: scans all /etc/enigma2/*.tv files and collects #SERVICE lines.
# ------------------------------------------------------------------
def process_autobouquet():
    """
    Build a dict of all service refs from all TV bouquets.
    """
    import glob
    import os
    global autobouquet_file_found

    apdb_local = {}
    bouquet_files = glob.glob("/etc/enigma2/*.tv")

    if not bouquet_files:
        print("[AutoBouquet] Nessun bouquet trovato in /etc/enigma2/")
        autobouquet_file_found = False
        return {}

    print("[AutoBouquet] Scanning bouquets:", bouquet_files)

    for bq in bouquet_files:
        try:
            with open(bq, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("#SERVICE"):
                        ref = line[9:].strip()
                        if ref and ref not in apdb_local:
                            apdb_local[ref] = ref
        except Exception as e:
            print("[AutoBouquet] Errore nella lettura %s: %s" % (bq, e))

    autobouquet_file_found = True if len(apdb_local) > 0 else False
    print("[AutoBouquet] Trovati", len(apdb_local), "servizi validi.")
    return apdb_local

# build database immediately
apdb = process_autobouquet()

# ------------------------------------------------------------------
# connectivity check
# ------------------------------------------------------------------
def intCheck():
    try:
        response = urlopen("http://google.com", None, 5)
        response.close()
    except HTTPError:
        return False
    except URLError:
        return False
    except socket.timeout:
        return False
    return True

# ------------------------------------------------------------------
# Thread and autoscan classes (unchanged structure, only small guards added)
# ------------------------------------------------------------------
class PosterDB(iPosterXDownloadThread):
    """
    NOTE: This is ONLY the thread *launcher* class name to keep your external references intact.
    It inherits iPosterXDownloadThread (where the real logic/queue lives) and does not duplicate any code.
    """
    def __init__(self):
        iPosterXDownloadThread.__init__(self)

# Start the single worker thread (using the non-duplicated class)
threadDB = PosterDB()
threadDB.setDaemon(True)
threadDB.start()

class PosterAutoDB(iPosterXDownloadThread):
    def __init__(self):
        iPosterXDownloadThread.__init__(self)
        self.logdbg = None
        self.pstcanal = None

    def run(self):
        self.logAutoDB("[AutoDB] *** Initialized ***")
        while True:
            # default behavior: every 10 (600) minutes for quicker testing (adjustable)
            time.sleep(10)
            self.logAutoDB("[AutoDB] *** Running ***")
            self.pstcanal = None
            # AUTO ADD NEW FILES - 1440 (24 hours ahead)
            for service in apdb.values():
                try:
                    events = epgcache.lookupEvent(['IDT', (service, 0, -1, 1440)])
                    newfd = 0
                    newcn = None
                    for evt in events:
                        try:
                            self.logAutoDB("[AutoDB] evt {} events ({})".format(evt, len(events)))
                        except Exception:
                            self.logAutoDB("[AutoDB] evt (unprintable) events ({})".format(len(events)))

                        canal = [None] * 6
                        try:
                            if PY3:
                                canal[0] = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                            else:
                                canal[0] = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '').encode('utf-8')
                        except Exception as e:
                            self.logAutoDB("[AutoDB] ServiceReference error for ref {}: {}".format(service, e))
                            continue

                        if evt[1] is None or evt[4] is None or evt[5] is None or evt[6] is None:
                            self.logAutoDB("[AutoDB] *** Missing EPG for {}".format(canal[0]))
                        else:
                            canal[1:6] = [evt[1], evt[4], evt[5], evt[6], evt[4]]
                            # we want to pass the original event name into convtext for search
                            self.pstcanal = convtext(canal[5]) if canal[5] else None

                            if self.pstcanal:
                                dwn_poster = os.path.join(path_folder, self.pstcanal + ".jpg")
                            else:
                                self.logAutoDB("[AutoDB] None type detected - poster name not derived")
                                continue

                            if os.path.exists(dwn_poster):
                                try:
                                    os.utime(dwn_poster, (time.time(), time.time()))
                                except Exception:
                                    pass

                            if not os.path.exists(dwn_poster):
                                ok = self.parallel_search_and_save(dwn_poster, self.pstcanal, canal[4], canal[3])
                                if ok:
                                    newfd += 1
                                else:
                                    self.logAutoDB("[AutoDB] Failed to find poster for event: {}".format(canal[5]))

                            newcn = canal[0]

                        self.logAutoDB("[AutoDB] {} new file(s) added ({})".format(newfd, newcn))
                except Exception as e:
                    self.logAutoDB("[AutoDB] *** Service error: {}".format(e))
                    traceback.print_exc()

            # AUTO REMOVE OLD FILES (cleanup)
            now_tm = time.time()
            emptyfd = 0
            oldfd = 0
            try:
                for f in os.listdir(path_folder):
                    file_path = os.path.join(path_folder, f)
                    diff_tm = now_tm - os.path.getmtime(file_path)
                    if diff_tm > 120 and os.path.getsize(file_path) == 0:
                        os.remove(file_path)
                        emptyfd += 1
                    elif diff_tm > 63072000:
                        os.remove(file_path)
                        oldfd += 1
            except Exception as e:
                self.logAutoDB("[AutoDB] cleanup error: {}".format(e))
            self.logAutoDB("[AutoDB] {} old file(s) removed".format(oldfd))
            self.logAutoDB("[AutoDB] {} empty file(s) removed".format(emptyfd))
            self.logAutoDB("[AutoDB] *** Stopping ***")

    def logAutoDB(self, logmsg):
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("/tmp/iPosterXAutoDB.log", "a") as w:
                w.write("[{}] {}\n".format(timestamp, logmsg))
        except Exception as e:
            print("logAutoDB error: {}".format(e))
            traceback.print_exc()

threadAutoDB = PosterAutoDB()
threadAutoDB.setDaemon(True)
threadAutoDB.start()

# ------------------------------------------------------------------
# Renderer class (unchanged logic, small guards)
# ------------------------------------------------------------------
class iPosterX(Renderer):
    def __init__(self):
        Renderer.__init__(self)
        self.adsl = intCheck()
        if not self.adsl:
            print("Connessione assente, modalità offline.")
        else:
            print("Connessione rilevata.")
        self.nxts = 0
        self.path = path_folder
        self.canal = [None, None, None, None, None, None]
        self.oldCanal = None
        self.logdbg = None
        self.pstcanal = None
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.showPoster)
        except Exception:
            self.timer.callback.append(self.showPoster)

    def applySkin(self, desktop, parent):
        attribs = []
        for (attrib, value,) in self.skinAttributes:
            if attrib == "nexts":
                self.nxts = int(value)
            if attrib == "path":
                self.path = str(value)
            attribs.append((attrib, value))
        self.skinAttributes = attribs
        return Renderer.applySkin(self, desktop, parent)

    GUI_WIDGET = ePixmap

    def changed(self, what):
        if not self.instance:
            return
        if what[0] == self.CHANGED_CLEAR:
            self.instance.hide()
            return
        servicetype = None
        try:
            service = None
            source_type = type(self.source)
            if source_type is ServiceEvent:
                service = self.source.getCurrentService()
                servicetype = "ServiceEvent"
            elif source_type is CurrentService:
                service = self.source.getCurrentServiceRef()
                servicetype = "CurrentService"
            elif source_type is EventInfo:
                service = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
                servicetype = "EventInfo"
            elif source_type is Event:
                if self.nxts:
                    service = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
                else:
                    self.canal[0] = None
                    self.canal[1] = self.source.event.getBeginTime()
                    event_name = self.source.event.getEventName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                    if not PY3:
                        event_name = event_name.encode('utf-8')
                    self.canal[2] = event_name
                    self.canal[3] = self.source.event.getExtendedDescription()
                    self.canal[4] = self.source.event.getShortDescription()
                    self.canal[5] = event_name
                servicetype = "Event"
            if service is not None:
                service_str = service.toString()
                events = epgcache.lookupEvent(['IDT', (service_str, 0, -1, -1)])
                service_name = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                if not PY3:
                    service_name = service_name.encode('utf-8')
                self.canal[0] = service_name
                self.canal[1] = events[self.nxts][1]
                self.canal[2] = events[self.nxts][4]
                self.canal[3] = events[self.nxts][5]
                self.canal[4] = events[self.nxts][6]
                self.canal[5] = self.canal[2]
                # If we did not find bouquets at startup, allow adding services discovered while zapping
                if not autobouquet_file_found and service_name not in apdb:
                    apdb[service_name] = service_str
        except Exception as e:
            print("Error (service):", str(e))
            if self.instance:
                self.instance.hide()
            return
        if not servicetype:
            print("Error: service type undefined")
            if self.instance:
                self.instance.hide()
            return
        try:
            curCanal = "{}-{}".format(self.canal[1], self.canal[2])
            if curCanal == self.oldCanal:
                return
            self.oldCanal = curCanal
            self.logPoster("Service: {} [{}] : {} : {}".format(servicetype, self.nxts, self.canal[0], self.oldCanal))

            # Use convtext (unchanged) to derive cleaned search title
            self.pstcanal = convtext(self.canal[5])

            # NEW: first check index for immediate mapping to poster file
            mapped_path = None
            try:
                if self.pstcanal:
                    mapped_path = poster_index_get_fullpath(self.pstcanal)
                    if mapped_path and os.path.exists(mapped_path):
                        self.pstrNm = mapped_path
                    else:
                        self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg") if self.pstcanal else None
                else:
                    self.pstrNm = None
            except Exception:
                self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg") if self.pstcanal else None

            if self.pstrNm and os.path.exists(self.pstrNm):
                self.logPoster("[FOUND] immediate poster: " + self.pstrNm)
                self.timer.start(10, True)
            else:
                try:
                    if os.path.exists(noposter):
                        self.logPoster("[NOP] Showing skin noposter: " + noposter)
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        self.logPoster("[WARN] noposter not found: " + noposter)
                        self.instance.hide()
                except Exception as e:
                    self.logPoster("[ERROR] setting noposter: " + str(e))
                canal = self.canal[:]
                try:
                    pdb.put(canal)
                    start_new_thread(self.waitPoster, ())
                except Exception as e:
                    self.logPoster("[ERROR] queue put/start wait: " + str(e))
        except Exception as e:
            print("Error (eFile):", str(e))
            if self.instance:
                self.instance.hide()
            return

    def generatePosterPath(self):
        if not self.canal[5]:
            return None
        pstcanal = convtext(self.canal[5])
        if not pstcanal:
            return None
        # check index first
        try:
            mapped = poster_index_get_fullpath(pstcanal)
            if mapped and os.path.exists(mapped):
                return mapped
        except Exception:
            pass
        return os.path.join(self.path, str(pstcanal) + ".jpg")

    def showPoster(self):
        if self.instance:
            self.instance.hide()
        self.pstrNm = self.generatePosterPath()
        if self.pstrNm and os.path.exists(self.pstrNm):
            try:
                self.logPoster("[LOAD : showPoster] " + self.pstrNm)
                self.instance.setPixmap(loadJPG(self.pstrNm))
                self.instance.setScale(1)
                self.instance.show()
            except Exception as e:
                self.logPoster("[ERROR] showPoster load failed: " + str(e))
                try:
                    if os.path.exists(noposter):
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        self.instance.hide()
                except Exception as ee:
                    self.logPoster("[ERROR] fallback noposter failed: " + str(ee))

    def waitPoster(self):
        self.pstrNm = self.generatePosterPath()
        if not self.pstrNm:
            self.logPoster("[ERROR] waitPoster got None path, skipping")
            return
        loop = 180
        found = False
        self.logPoster("[LOOP: waitPoster] " + str(self.pstrNm))
        while loop > 0:
            try:
                if os.path.exists(self.pstrNm):
                    found = True
                    break
            except Exception as e:
                self.logPoster("[ERROR] waitPoster os.path.exists: " + str(e))
            time.sleep(0.5)
            loop -= 1
        if found:
            self.timer.start(10, True)
            self.logPoster("[LOOP] poster found -> scheduling showPoster: " + str(self.pstrNm))
        else:
            self.logPoster("[LOOP] poster NOT found after wait: " + str(self.pstrNm))

    def logPoster(self, logmsg):
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # compact log format and autotruncate (reuse download thread's logging function)
            try:
                dl_log(logmsg)
            except Exception:
                with open("/tmp/iPosterX.log", "a") as w:
                    w.write("[%s] %s\n" % (timestamp, logmsg))
        except Exception as e:
            print('logPoster error:', str(e))
            traceback.print_exc()

def findPoster(eventName):
    cleanedName = cutName(eventName)
    if REGEX.search(cleanedName):
        pass
    else:
        print("No match found for event name: %s" % cleanedName)

# sample debug call (kept)
eventName = "1737847083-KARAMELLA"
findPoster(eventName)
