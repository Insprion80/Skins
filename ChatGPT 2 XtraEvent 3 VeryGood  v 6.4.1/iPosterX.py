#!/usr/bin/python
# -*- coding: utf-8 -*-

# iPosterX Renderer — display only, minimal UI work.
# It pushes poster fetch jobs to the shared pdb defined in iPosterXDownloadThread.

from __future__ import print_function
from Components.Renderer.Renderer import Renderer
from Components.Sources.CurrentService import CurrentService
from Components.Sources.Event import Event
from Components.Sources.EventInfo import EventInfo
from Components.Sources.ServiceEvent import ServiceEvent
from Components.config import config
from ServiceReference import ServiceReference
from enigma import ePixmap, loadJPG, eEPGCache, eTimer
import NavigationInstance, os, sys, time, traceback, datetime

from .iConverlibr import convtext, poster_index_get_fullpath, init_poster_index

# import shared queue and worker
from Components.Renderer.iPosterXDownloadThread import pdb, iPosterXDownloadThread, path_folder as dl_folder, log as dl_log

PY3 = sys.version_info[0] >= 3
if PY3:
    from _thread import start_new_thread
else:
    from thread import start_new_thread

epgcache = eEPGCache.getInstance()

# skin detection and noposter path
cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')
noposter = "/usr/share/enigma2/%s/main/noposter.jpg" % cur_skin
path_folder = dl_folder
if not os.path.exists(path_folder):
    try:
        os.makedirs(path_folder)
    except Exception:
        pass

# init poster index (safe)
try:
    init_poster_index(path_folder, max_entries=50000)
except Exception:
    pass

# small queued set to avoid duplicate queueing from UI quickly
_queued_titles = set()

# Start single worker thread (if not already started, instantiate)
try:
    # create if not started - creating another thread is safe (daemon)
    poster_worker = iPosterXDownloadThread()
    poster_worker.setDaemon(True)
    poster_worker.start()
except Exception:
    pass

class iPosterX(Renderer):
    GUI_WIDGET = ePixmap

    def __init__(self):
        Renderer.__init__(self)
        self.nxts = 0
        self.path = path_folder
        self.canal = [None]*6
        self.oldCanal = None
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
                try: self.nxts = int(value)
                except Exception: self.nxts = 0
            if attrib == "path":
                try: self.path = str(value)
                except Exception: pass
            attribs.append((attrib, value))
        self.skinAttributes = attribs
        return Renderer.applySkin(self, desktop, parent)

    def changed(self, what):
        if not self.instance: return
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
                    event_name = self.source.event.getEventName().replace('\xc2\x86','').replace('\xc2\x87','')
                    if not PY3:
                        event_name = event_name.encode('utf-8')
                    self.canal[2] = event_name
                    self.canal[3] = self.source.event.getExtendedDescription()
                    self.canal[4] = self.source.event.getShortDescription()
                    self.canal[5] = event_name
                servicetype = "Event"

            if service is not None:
                service_str = service.toString()
                # prefer IBDCTESX then fallback IDT
                try:
                    events = epgcache.lookupEvent(['IBDCTESX', (service_str, 0, -1, -1)])
                except Exception:
                    try:
                        events = epgcache.lookupEvent(['IDT', (service_str, 0, -1, -1)])
                    except Exception:
                        events = []
                try:
                    service_name = ServiceReference(service).getServiceName().replace('\xc2\x86','').replace('\xc2\x87','')
                except Exception:
                    service_name = service_str
                if not PY3:
                    service_name = service_name.encode('utf-8')
                self.canal[0] = service_name
                try:
                    self.canal[1] = events[self.nxts][1]
                    self.canal[2] = events[self.nxts][4]
                    self.canal[3] = events[self.nxts][5]
                    self.canal[4] = events[self.nxts][6]
                    self.canal[5] = self.canal[2]
                except Exception:
                    if self.instance:
                        self.instance.hide()
                    return
        except Exception as e:
            dl_log("[ERROR] service read error: %s" % e)
            traceback.print_exc()
            if self.instance:
                self.instance.hide()
            return

        # build unique key
        try:
            curCanal = "{}-{}".format(self.canal[1], self.canal[2])
            if curCanal == self.oldCanal:
                return
            self.oldCanal = curCanal

            # derive cleaned title
            self.pstcanal = convtext(self.canal[5]) if self.canal and self.canal[5] else None

            # choose mapped path if exists
            mapped_path = None
            try:
                if self.pstcanal:
                    mapped_path = poster_index_get_fullpath(self.pstcanal)
                    if mapped_path and os.path.exists(mapped_path):
                        self.pstrNm = mapped_path
                        dl_log("[CACHE] %s" % (self.pstcanal))
                        self.timer.start(10, True)
                        return
                    else:
                        self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg") if self.pstcanal else None
                else:
                    self.pstrNm = None
            except Exception:
                self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg") if self.pstcanal else None

            if self.pstrNm and os.path.exists(self.pstrNm):
                dl_log("[CACHE] %s" % (self.pstcanal if self.pstcanal else os.path.basename(self.pstrNm)))
                self.timer.start(10, True)
                return

            # show noposter to avoid blank UI
            try:
                if os.path.exists(noposter):
                    try:
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    except Exception:
                        self.instance.hide()
                else:
                    dl_log("[WARN] noposter missing: %s" % noposter)
                    self.instance.hide()
            except Exception as e:
                dl_log("[ERROR] set noposter: %s" % e)

            # enqueue background retrieval if we have a cleaned title and not queued
            if self.pstcanal:
                key = str(self.pstcanal)
                queued = False
                try:
                    if key not in _queued_titles:
                        _queued_titles.add(key)
                        # push a full canal copy to downloader to enable context if needed
                        pdb.put(self.canal[:])
                        queued = True
                except Exception as e:
                    dl_log("[ERROR] queue put failed: %s" % e)

                if queued:
                    try:
                        start_new_thread(self.waitPoster, ())
                    except Exception as e:
                        dl_log("[ERROR] start wait thread failed: %s" % e)
        except Exception as e:
            dl_log("[ERROR] processing error: %s" % e)
            traceback.print_exc()
            if self.instance:
                self.instance.hide()
            return

    def generatePosterPath(self):
        if not self.canal or not self.canal[5]:
            return None
        pstcanal = convtext(self.canal[5])
        if not pstcanal:
            return None
        try:
            mapped = poster_index_get_fullpath(pstcanal)
            if mapped and os.path.exists(mapped):
                return mapped
        except Exception:
            pass
        return os.path.join(self.path, str(pstcanal) + ".jpg")

    def showPoster(self):
        if not self.instance:
            return
        self.instance.hide()
        self.pstrNm = self.generatePosterPath()
        if self.pstrNm and os.path.exists(self.pstrNm):
            try:
                info_src = "unknown"
                try:
                    idx = poster_index_get_fullpath(self.pstcanal)
                    # poster_index_get_fullpath doesn't carry source currently; skip
                except Exception:
                    pass
                dl_log("[FOUND] title=%s poster=%s source=%s" % (
                    (self.pstcanal if self.pstcanal else os.path.basename(self.pstrNm)),
                    os.path.basename(self.pstrNm),
                    info_src
                ))
            except Exception:
                pass
            try:
                self.instance.setPixmap(loadJPG(self.pstrNm))
                self.instance.setScale(1)
                self.instance.show()
            except Exception as e:
                dl_log("[ERROR] showPoster load failed: %s" % e)
                try:
                    if os.path.exists(noposter):
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        self.instance.hide()
                except Exception as ee:
                    dl_log("[ERROR] fallback noposter failed: %s" % ee)
        else:
            return

    def waitPoster(self):
        key = None
        try:
            key = convtext(self.canal[5]) if self.canal and self.canal[5] else None
        except Exception:
            key = None
        if not key:
            dl_log("[WARN] waitPoster got None key, skipping")
            return
        expected = os.path.join(self.path, key + ".jpg")
        loop = 90
        found = False
        while loop > 0:
            try:
                mapped = poster_index_get_fullpath(key)
                if mapped and os.path.exists(mapped):
                    expected = mapped
                    found = True
                    break
                if os.path.exists(expected):
                    found = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
            loop -= 1
        try:
            if key in _queued_titles:
                _queued_titles.discard(key)
        except Exception:
            pass
        if found:
            try:
                dl_log("[FOUND] title=%s poster=%s" % (key, os.path.basename(expected)))
            except Exception:
                pass
            try:
                self.timer.start(10, True)
            except Exception:
                try:
                    self.showPoster()
                except Exception:
                    pass
        else:
            dl_log("[WARN] poster NOT found after wait: %s" % key)

    def logPoster(self, logmsg):
        try:
            dl_log(logmsg)
        except Exception:
            try:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open("/tmp/iPosterX.log", "a") as w:
                    w.write("[%s] %s\n" % (timestamp, str(logmsg)))
            except Exception:
                pass
