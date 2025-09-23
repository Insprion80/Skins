#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
iConverlibr.py
Utility functions for cleaning/normalizing event names and a small PosterIndex (JSON LRU).
This file provides:
 - convtext(text)             : main cleaned key (used by renderer + downloader)
 - convtext_fallback(text)    : optional fallback cleaning (keeps compatibility)
 - cutName(text)              : lower-level trimming
 - init_poster_index(path, max_entries)
 - poster_index_add(cleaned_title, source)
 - poster_index_get_fullpath(cleaned_title)
"""

from __future__ import absolute_import
import os, sys, re, json, time
from unicodedata import normalize
from re import sub, compile, I

PY3 = sys.version_info[0] >= 3
if PY3:
    from urllib.parse import quote_plus
else:
    from urllib import quote_plus

# -------------------------------------------------------------------
# REGEX (kept conservative so we don't discard valid titles)
# -------------------------------------------------------------------
REGEX = compile(
    r'[\(\[].*?[\)\]]|'                    # Text in () or []
    r':?\s?odc\.\d+|'                      # "odc.12"
    r'\d+\s?:?\s?odc\.\d+|'                # "2 odc.12"
    r'[:!]|'                               # ":" or "!"
    r'\s-\s.*|'                            # " - Episode title"
    r',|'                                  # ","
    r'/.*|'                                # "Title/Subtitle"
    r'\|\s?\d+\+|'                         # "| 18+"
    r'\d+\+|'                              # "16+"
    r'\s\*\d{1,4}\Z|'                      # "*2022"
    r'\.\s.+)|'                            # ". Something"
    r'(?:\"[\.|\,]?\s.*|\"|'               # text in quotes
    r'\.\s.+)|'                            # ". Something"
    re.DOTALL
)

# -------------------------------------------------------------------
# PosterIndex: small JSON LRU mapping cleaned_title -> [timestamp, source]
# stores file as poster_index.json in the poster folder
# -------------------------------------------------------------------
class PosterIndex(object):
    _singleton = None

    def __init__(self, path_folder="/tmp/XDREAMY/poster", max_entries=5000):
        self.path_folder = path_folder
        self.index_file = os.path.join(self.path_folder, "poster_index.json")
        self.max_entries = int(max_entries)
        self.map = {}
        self.order = []
        if not os.path.exists(self.path_folder):
            try:
                os.makedirs(self.path_folder)
            except Exception:
                pass
        self._load()

    @classmethod
    def get_instance(cls, path_folder=None, max_entries=5000):
        if cls._singleton is None:
            cls._singleton = PosterIndex(path_folder=path_folder or "/tmp/XDREAMY/poster", max_entries=max_entries)
        else:
            if path_folder and cls._singleton.path_folder != path_folder:
                cls._singleton.path_folder = path_folder
                cls._singleton.index_file = os.path.join(path_folder, "poster_index.json")
                cls._singleton._load()
        return cls._singleton

    def _load(self):
        try:
            if os.path.exists(self.index_file):
                with open(self.index_file, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "map" in data:
                    self.map = data.get("map", {})
                    self.order = data.get("order", [])
                elif isinstance(data, dict):
                    self.map = data
                    self.order = list(self.map.keys())
            else:
                self.map = {}
                self.order = []
        except Exception:
            self.map = {}
            self.order = []

    def _save(self):
        try:
            payload = {"map": self.map, "order": self.order}
            tmp = self.index_file + ".part"
            with open(tmp, "w", encoding="utf-8", errors="ignore") as f:
                json.dump(payload, f, ensure_ascii=False)
            try:
                os.replace(tmp, self.index_file)
            except Exception:
                try:
                    os.remove(self.index_file)
                except Exception:
                    pass
                os.rename(tmp, self.index_file)
        except Exception:
            pass

    def add(self, cleaned_title, source="remote"):
        if not cleaned_title:
            return
        key = cleaned_title.strip()
        ts = int(time.time())
        self.map[key] = [ts, source or "remote"]
        # maintain LRU order
        try:
            if key in self.order:
                self.order.remove(key)
        except Exception:
            pass
        self.order.append(key)
        while len(self.order) > self.max_entries:
            old = self.order.pop(0)
            try:
                del self.map[old]
            except Exception:
                pass
        self._save()

    def get(self, cleaned_title):
        if not cleaned_title:
            return None
        return self.map.get(cleaned_title.strip())

    def get_fullpath(self, cleaned_title):
        if not cleaned_title:
            return None
        filename = cleaned_title.strip() + ".jpg"
        full = os.path.join(self.path_folder, filename)
        if os.path.exists(full):
            return full
        return None

# Convenience wrappers
_poster_index_singleton = None

def init_poster_index(path_folder=None, max_entries=5000):
    global _poster_index_singleton
    _poster_index_singleton = PosterIndex.get_instance(path_folder=path_folder, max_entries=max_entries)
    return _poster_index_singleton

def poster_index_add(cleaned_title, source="remote"):
    global _poster_index_singleton
    if _poster_index_singleton is None:
        init_poster_index()
    try:
        _poster_index_singleton.add(cleaned_title, source)
    except Exception:
        pass

def poster_index_get_fullpath(cleaned_title):
    global _poster_index_singleton
    if _poster_index_singleton is None:
        init_poster_index()
    try:
        return _poster_index_singleton.get_fullpath(cleaned_title)
    except Exception:
        return None

# -------------------------------------------------------------------
# Cleaning utilities
# -------------------------------------------------------------------
def cutName(eventName=""):
    if not eventName:
        return ""
    try:
        s = str(eventName)
    except Exception:
        s = eventName
    # quick clean markers
    s = s.replace('"', '').replace('\xc2\x86', '').replace('\xc2\x87', '')
    # remove common ratings
    for tag in ['(18+)', '18+', '(16+)', '16+', '(12+)', '12+', '(7+)', '7+', '(6+)', '6+', '(0+)', '0+']:
        s = s.replace(tag, '')
    # remove bracketed sequences and typical episode markers (simplified)
    s = re.sub(r'\bS\d{1,2}E?\d{0,2}\b', '', s, flags=re.I)
    s = re.sub(r'\bSeason\s*\d+\b', '', s, flags=re.I)
    s = re.sub(r'\bEp(isode)?\.?\s*\d+\b', '', s, flags=re.I)
    s = re.sub(r'\bodc\.?\s*\d+\b', '', s, flags=re.I)
    s = re.sub(r'\s+\d{4}\b', '', s)  # remove trailing years
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def remove_accents(string):
    if not isinstance(string, str):
        try:
            string = str(string)
        except Exception:
            return string
    try:
        nk = normalize('NFD', string)
        nk = ''.join([c for c in nk if not (0x300 <= ord(c) <= 0x36F)])
        return nk
    except Exception:
        return string

def getCleanTitle(eventitle=""):
    return eventitle.replace(' ^`^s', '').replace(' ^`^y', '')

def convtext(text=''):
    try:
        if text is None:
            return ""
        t = str(text).strip()
        # special case "2012" movie
        if t.lower().strip() == "2012":
            return "2012"
        # small substitutions
        subs = {
            'c.s.i.': 'csi',
            'ncis:': 'ncis',
            'superman & lois': 'superman e lois',
            '&': ' and ',
        }
        lower = t.lower()
        for k, v in subs.items():
            if k in lower:
                t = v if k == 'superman & lois' else re.sub(re.escape(k), v, lower, flags=re.I)
                break
        t = cutName(t)
        t = getCleanTitle(t)
        # remove junk words
        for junk in ['webhdtv', '1080i', 'dvdrip', 'webrip', 'bluray', 'hdtvrip', 'uncut', 'retail', '1080p', '720p', '4k', 'x264']:
            t = re.sub(re.escape(junk), '', t, flags=re.I)
        t = remove_accents(t)
        # remove years in parentheses
        t = re.sub(r'\(\s*(19|20)\d{2}\s*\)', '', t)
        t = re.sub(r'[^A-Za-z0-9\-\s\u0080-\uffff]', '', t)  # keep letter/digit/unicode and basic punctuation
        t = re.sub(r'\s+', ' ', t).strip()
        # Collapse to safe filename characters (but keep unicode)
        return t.strip()
    except Exception:
        return str(text).strip()

def convtext_fallback(text=''):
    # A simpler fallback: remove non-letters and numbers
    if not text:
        return ""
    t = str(text)
    t = re.sub(r'[^A-Za-z0-9\u0080-\uffff\s-]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# End of iConverlibr.py
