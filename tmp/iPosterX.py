#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
iPosterX.py — Renderer (display-only)
 - uses shared queue pdb from iPosterXDownloadThread
 - uses convtext from iConverlibr to compute cleaned title
 - uses poster_index_get_fullpath to attempt immediate cache hit
 - when miss: shows skin noposter and queue download (no download in renderer)
"""
from __future__ import print_function
import os, sys, time, traceback, datetime

from Components.Renderer.Renderer import Renderer
from Components.Sources.CurrentService import CurrentService
from Components.Sources.Event import Event
from Components.Sources.EventInfo import EventInfo
from Components.Sources.ServiceEvent import ServiceEvent
from Components.config import config
from ServiceReference import ServiceReference
from enigma import ePixmap, loadJPG, eEPGCache, eTimer
import NavigationInstance

from .iConverlibr import convtext, poster_index_get_fullpath, init_poster_index

# import shared structures from download thread
from Components.Renderer.iPosterXDownloadThread import pdb, dl_log, path_folder, intCheck

PY3 = sys.version_info[0] >= 3

epgcache = eEPGCache.getInstance()

# skin detection for noposter
cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')
noposter = "/usr/share/enigma2/%s/main/noposter.jpg" % cur_skin
# ensure poster index init
try:
    init_poster_index(path_folder, max_entries=50000)
except Exception:
    pass

class iPosterX(Renderer):
    GUI_WIDGET = ePixmap

    def __init__(self):
        Renderer.__init__(self)
        self.nxts = 0
        self.path = path_folder
        self.canal = [None] * 6
        self.oldKey = None
        self.pstcanal = None
        self.timer = eTimer()
        try:
            self.timer.timeout.connect(self.showPoster)
        except Exception:
            self.timer.callback.append(self.showPoster)
        # connection check via downloader's intCheck
        try:
            self.adsl = intCheck()
        except Exception:
            self.adsl = False

    def applySkin(self, desktop, parent):
        attribs = []
        for (attrib, value,) in self.skinAttributes:
            if attrib == "nexts":
                try:
                    self.nxts = int(value)
                except Exception:
                    self.nxts = 0
            if attrib == "path":
                self.path = str(value)
            attribs.append((attrib, value))
        self.skinAttributes = attribs
        return Renderer.applySkin(self, desktop, parent)

    def changed(self, what):
        if not self.instance:
            return
        if what[0] == self.CHANGED_CLEAR:
            self.instance.hide()
            return

        service = None
        service_type = None
        try:
            stype = type(self.source)
            if stype is ServiceEvent:
                service = self.source.getCurrentService()
                service_type = "ServiceEvent"
            elif stype is CurrentService:
                service = self.source.getCurrentServiceRef()
                service_type = "CurrentService"
            elif stype is EventInfo:
                service = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
                service_type = "EventInfo"
            elif stype is Event:
                # event carries data directly
                if self.nxts:
                    service = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
                else:
                    self.canal[0] = None
                    self.canal[1] = self.source.event.getBeginTime()
                    evname = self.source.event.getEventName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                    if not PY3:
                        evname = evname.encode('utf-8')
                    self.canal[2] = evname
                    self.canal[3] = self.source.event.getExtendedDescription()
                    self.canal[4] = self.source.event.getShortDescription()
                    self.canal[5] = evname
                    service_type = "Event"
            # service-based: use EPG lookup
            if service is not None:
                sref = service.toString()
                try:
                    events = epgcache.lookupEvent(['IDT', (sref, 0, -1, -1)])
                except Exception:
                    events = []
                svcname = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                if not PY3:
                    svcname = svcname.encode('utf-8')
                self.canal[0] = svcname
                try:
                    self.canal[1] = events[self.nxts][1]
                    self.canal[2] = events[self.nxts][4]
                    self.canal[3] = events[self.nxts][5]
                    self.canal[4] = events[self.nxts][6]
                    self.canal[5] = self.canal[2]
                except Exception:
                    # missing event -> hide
                    if self.instance:
                        self.instance.hide()
                    return
        except Exception as e:
            traceback.print_exc()
            if self.instance:
                self.instance.hide()
            return

        # build unique key
        try:
            curKey = "%s-%s" % (self.canal[1], self.canal[2])
            if curKey == self.oldKey:
                return
            self.oldKey = curKey
            # compute cleaned title
            self.pstcanal = convtext(self.canal[5]) if self.canal and self.canal[5] else None
            # if index maps to existing file -> show immediately
            if self.pstcanal:
                mapped = poster_index_get_fullpath(self.pstcanal)
                if mapped and os.path.exists(mapped):
                    self.pstrNm = mapped
                    # schedule show safely on GUI thread
                    try:
                        self.timer.start(10, True)
                    except Exception:
                        try:
                            self.showPoster()
                        except Exception:
                            pass
                    return
                # fallback to computed path
                self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg")
            else:
                self.pstrNm = None
        except Exception:
            self.pstrNm = None

        # If local file exists show it
        if self.pstrNm and os.path.exists(self.pstrNm):
            try:
                self.timer.start(10, True)
            except Exception:
                try:
                    self.showPoster()
                except Exception:
                    pass
            return

        # show skin noposter immediately (no download work here)
        try:
            if os.path.exists(noposter):
                try:
                    self.instance.setPixmap(loadJPG(noposter))
                    self.instance.setScale(1)
                    self.instance.show()
                except Exception:
                    self.instance.hide()
            else:
                # noposter missing -> hide
                self.instance.hide()
        except Exception:
            self.instance.hide()

        # enqueue for background retrieval if we have a usable cleaned title
        if self.pstcanal:
            try:
                # do not queue duplicates frequently
                try:
                    # if pdb has task_done and put - use it; else fallback to simple put/pop
                    pdb.put(self.canal[:])
                except Exception:
                    try:
                        pdb.append(self.canal[:])
                    except Exception:
                        pass
                # spawn a waiter thread to update display once saved
                try:
                    import _thread as _thread_mod
                    _thread_mod.start_new_thread(self._waitPoster, ())
                except Exception:
                    try:
                        from thread import start_new_thread
                        start_new_thread(self._waitPoster, ())
                    except Exception:
                        pass
            except Exception:
                pass

    def _waitPoster(self):
        # brief waiter that checks index/local file then triggers showPoster;
        # loops up to 45 seconds (90 * 0.5s)
        key = None
        try:
            key = convtext(self.canal[5]) if self.canal and self.canal[5] else None
        except Exception:
            key = None
        if not key:
            return
        expected = os.path.join(self.path, key + ".jpg")
        attempts = 90
        found = False
        while attempts > 0:
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
            attempts -= 1
        if found:
            # schedule GUI update
            try:
                self.timer.start(10, True)
            except Exception:
                try:
                    self.showPoster()
                except Exception:
                    pass
        else:
            # Nothing found: nothing to log here (download thread handles errors)
            pass

    def generatePosterPath(self):
        if not self.canal or not self.canal[5]:
            return None
        cleaned = convtext(self.canal[5])
        if not cleaned:
            return None
        mapped = poster_index_get_fullpath(cleaned)
        if mapped and os.path.exists(mapped):
            return mapped
        return os.path.join(self.path, cleaned + ".jpg")

    def showPoster(self):
        if not self.instance:
            return
        self.instance.hide()
        self.pstrNm = self.generatePosterPath()
        if self.pstrNm and os.path.exists(self.pstrNm):
            try:
                self.instance.setPixmap(loadJPG(self.pstrNm))
                self.instance.setScale(1)
                self.instance.show()
            except Exception:
                # fallback to noposter
                try:
                    if os.path.exists(noposter):
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        self.instance.hide()
                except Exception:
                    self.instance.hide()
        else:
            # nothing found - keep noposter already shown
            return

    def logPoster(self, msg):
        # compatibility wrapper (calls shared logger)
        try:
            dl_log(msg)
        except Exception:
            pass

# End of iPosterX.py
