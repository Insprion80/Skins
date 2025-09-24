#!/usr/bin/python
# -*- coding: utf-8 -*-

# iPosterX.py - Main renderer for Enigma2 poster display
# Works with iPosterXDownloadThread for downloads
# Keep original structure and function names for compatibility

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

# Import the shared queue and classes from download thread
from .iPosterXDownloadThread import (
    iPosterXDownloadThread,
    pdb,                  # shared LIFO queue
    path_folder,
    log,
    apdb,
    PosterAutoDB
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

# Get current skin for noposter image
try:
    cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')
    noposter = "/usr/share/enigma2/%s/main/noposter.jpg" % cur_skin
except Exception:
    noposter = "/usr/share/enigma2/default/main/noposter.jpg"

# Initialize poster index with same path
try:
    init_poster_index(path_folder, max_entries=5000)
except Exception:
    pass

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

# Keep PosterDB name for compatibility with external references
class PosterDB(iPosterXDownloadThread):
    """
    Compatibility wrapper - just inherits the download thread.
    """
    def __init__(self):
        iPosterXDownloadThread.__init__(self)

# Start the download threads
threadDB = PosterDB()
threadDB.setDaemon(True)
threadDB.start()

threadAutoDB = PosterAutoDB()
threadAutoDB.setDaemon(True)
threadAutoDB.start()

log("iPosterX threads started successfully")

class iPosterX(Renderer):
    def __init__(self):
        Renderer.__init__(self)
        self.adsl = intCheck()
        if not self.adsl:
            log("No internet connection detected")
        else:
            log("Internet connection available")
        
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
                events = epgcache.lookupEvent(['IBDCTESX', (service_str, 0, -1, -1)])
                service_name = ServiceReference(service).getServiceName().replace('\xc2\x86', '').replace('\xc2\x87', '')
                if not PY3:
                    service_name = service_name.encode('utf-8')
                self.canal[0] = service_name
                self.canal[1] = events[self.nxts][1]
                self.canal[2] = events[self.nxts][4]
                self.canal[3] = events[self.nxts][5]
                self.canal[4] = events[self.nxts][6]
                self.canal[5] = self.canal[2]
                
                # Add service to apdb if not found during startup
                if service_name not in apdb:
                    apdb[service_name] = service_str
                    
        except Exception as e:
            log("Error getting service info: %s" % str(e), "ERROR")
            if self.instance:
                self.instance.hide()
            return
        
        if not servicetype:
            log("Service type undefined", "ERROR")
            if self.instance:
                self.instance.hide()
            return
        
        try:
            curCanal = "%s-%s" % (self.canal[1], self.canal[2])
            if curCanal == self.oldCanal:
                return
            self.oldCanal = curCanal
            
            log("Event: %s [%s] : %s : %s" % (servicetype, self.nxts, self.canal[0], self.oldCanal))

            # Use convtext to get cleaned title for search
            self.pstcanal = convtext(self.canal[5])

            # Check if poster exists
            self.pstrNm = None
            try:
                if self.pstcanal:
                    # Check index first
                    mapped_path = poster_index_get_fullpath(self.pstcanal)
                    if mapped_path and os.path.exists(mapped_path):
                        self.pstrNm = mapped_path
                    else:
                        # Check direct path
                        self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg")
                else:
                    self.pstrNm = None
            except Exception:
                self.pstrNm = os.path.join(self.path, str(self.pstcanal) + ".jpg") if self.pstcanal else None

            if self.pstrNm and os.path.exists(self.pstrNm):
                log("Found existing poster: %s" % self.pstrNm)
                self.timer.start(10, True)
            else:
                # Show noposter immediately
                try:
                    if os.path.exists(noposter):
                        log("Showing noposter: %s" % noposter)
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        log("Noposter not found: %s" % noposter, "WARN")
                        self.instance.hide()
                except Exception as e:
                    log("Error setting noposter: %s" % str(e), "ERROR")
                
                # Queue download request
                canal = self.canal[:]
                try:
                    pdb.put(canal, block=False)
                    start_new_thread(self.waitPoster, ())
                except Exception as e:
                    log("Error queuing poster request: %s" % str(e), "ERROR")
                    
        except Exception as e:
            log("Error in changed(): %s" % str(e), "ERROR")
            if self.instance:
                self.instance.hide()
            return

    def generatePosterPath(self):
        if not self.canal[5]:
            return None
        pstcanal = convtext(self.canal[5])
        if not pstcanal:
            return None
        
        # Check index first
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
                log("Displaying poster: %s" % self.pstrNm)
                self.instance.setPixmap(loadJPG(self.pstrNm))
                self.instance.setScale(1)
                self.instance.show()
            except Exception as e:
                log("Error displaying poster: %s" % str(e), "ERROR")
                try:
                    if os.path.exists(noposter):
                        self.instance.setPixmap(loadJPG(noposter))
                        self.instance.setScale(1)
                        self.instance.show()
                    else:
                        self.instance.hide()
                except Exception as ee:
                    log("Error showing fallback noposter: %s" % str(ee), "ERROR")

    def waitPoster(self):
        self.pstrNm = self.generatePosterPath()
        if not self.pstrNm:
            log("waitPoster: No poster path generated", "WARN")
            return
            
        loop = 180
        found = False
        log("Waiting for poster: %s" % str(self.pstrNm))
        
        while loop > 0:
            try:
                if os.path.exists(self.pstrNm):
                    found = True
                    break
            except Exception as e:
                log("Error checking poster existence: %s" % str(e), "ERROR")
            time.sleep(0.5)
            loop -= 1
            
        if found:
            self.timer.start(10, True)
            log("Poster found, scheduling display: %s" % str(self.pstrNm))
        else:
            log("Poster not found after waiting: %s" % str(self.pstrNm), "WARN")

    def logPoster(self, logmsg):
        """Compatibility function - redirect to main log function."""
        log(logmsg)

# Keep original findPoster function for compatibility
def findPoster(eventName):
    cleanedName = cutName(eventName)
    if REGEX.search(cleanedName):
        pass
    else:
        log("No regex match for event name: %s" % cleanedName, "WARN")

log("iPosterX renderer module loaded successfully")