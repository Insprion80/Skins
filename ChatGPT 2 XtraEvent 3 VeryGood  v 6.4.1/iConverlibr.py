#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
iConverlibr.py
Utility functions for poster name cleaning + PosterIndex (JSON LRU).
Kept compact and compatible with older API names used by iPosterX.
"""

from re import sub, I, compile
from six import text_type
from unicodedata import normalize
import sys, re, os, json, time

# Py2/3 compatibility
try:
    unicode
except NameError:
    unicode = str

PY3 = sys.version_info[0] >= 3
if PY3:
    import html
    from urllib.parse import quote_plus
else:
    from urllib import quote_plus
    from HTMLParser import HTMLParser
    html = HTMLParser()

# Basic regex used across the project (kept compatible)
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
    r'[\(\[\|].*?[\)\]\|]|'                # any bracketed text
    r'(?:\"[\.|\,]?\s.*|\"|'               # text in quotes
    r'\.\s.+)|'                            # ". Something"
    r'Премьера\.\s|'                       # Russian "Premiere."
    r'[хмтдХМТД]/[фс]\s|'                  # Russian markers
    r'\s[сС](?:езон|ерия|-н|-я)\s.*|'      # Season/Episode in Russian
    r'\s\d{1,3}\s[чсЧС]\.?\s.*|'           # " 12 ч"
    r'\.\s\d{1,3}\s[чсЧС]\.?\s.*|'         # ". 12 ч"
    r'\s[чсЧС]\.?\s\d{1,3}.*|'             # "ч 12"
    r'\d{1,3}-(?:я|й)\s?с-н.*',            # Russian suffix
    re.DOTALL
)

# -------------------------------------------------------------------
# Poster Index (simple JSON LRU)
# -------------------------------------------------------------------
class PosterIndex(object):
    _instance = None

    def __init__(self, path_folder=None, max_entries=5000):
        self.max_entries = int(max_entries)
        self.path_folder = path_folder if path_folder else "/tmp/XDREAMY/poster"
        if not os.path.exists(self.path_folder):
            try:
                os.makedirs(self.path_folder)
            except Exception:
                pass
        self.index_file = os.path.join(self.path_folder, "poster_index.json")
        self.map = {}
        self.order = []
        self._loaded = False
        self.load()

    @classmethod
    def get_instance(cls, path_folder=None, max_entries=5000):
        if cls._instance is None:
            cls._instance = PosterIndex(path_folder=path_folder, max_entries=max_entries)
        else:
            if path_folder and cls._instance.path_folder != path_folder:
                cls._instance.set_path(path_folder)
        return cls._instance

    def set_path(self, path_folder):
        if not path_folder:
            return
        if not os.path.exists(path_folder):
            try:
                os.makedirs(path_folder)
            except Exception:
                pass
        if self.path_folder != path_folder:
            self.path_folder = path_folder
            self.index_file = os.path.join(self.path_folder, "poster_index.json")
            self.load()

    def load(self):
        try:
            if os.path.exists(self.index_file):
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.map = data.get("map", {})
                        self.order = data.get("order", [])
                    else:
                        self.map = data
                        self.order = list(self.map.keys())
            else:
                self.map = {}
                self.order = []
            self._loaded = True
        except Exception:
            self.map = {}
            self.order = []
            self._loaded = True

    def save(self):
        try:
            payload = {"map": self.map, "order": self.order}
            tmp = self.index_file + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
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
        val = [ts, source if source else "remote"]
        if key in self.map:
            try:
                self.order.remove(key)
            except Exception:
                pass
        self.map[key] = val
        self.order.append(key)
        while len(self.order) > self.max_entries:
            oldest = self.order.pop(0)
            try:
                del self.map[oldest]
            except Exception:
                pass
        self.save()

    def get(self, cleaned_title):
        if not cleaned_title:
            return None
        key = cleaned_title.strip()
        return self.map.get(key)

    def get_fullpath(self, cleaned_title):
        if not cleaned_title:
            return None
        filename = cleaned_title.strip() + ".jpg"
        full = os.path.join(self.path_folder, filename)
        if os.path.exists(full):
            return full
        return None

# module-level singleton helpers
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
# Cleaning Functions
# -------------------------------------------------------------------
def cutName(eventName=""):
    if not eventName:
        return ""
    eventName = eventName.replace('"', '').replace('Х/Ф', '').replace('М/Ф', '').replace('Х/ф', '')
    for tag in ['(18+)', '18+', '(16+)', '16+', '(12+)', '12+', '(7+)', '7+', '(6+)', '6+', '(0+)', '0+', '+']:
        eventName = eventName.replace(tag, '')
    for word in ['المسلسل العربي', 'مسلسل', 'برنامج', 'فيلم وثائقى', 'حفل']:
        eventName = eventName.replace(word, '')
    eventName = re.sub(r'\bSeason\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'\bS\d{1,2}\b', '', eventName, flags=I)
    eventName = re.sub(r'\bS\d{1,2}\s*-\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'-?\s*Ep(isode)?\.?\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'[\s_\-]*ح\.?\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*حل(?:قة|قه)?\.?\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*ج\.?\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*جزء\.?\s*\d+', '', eventName)
    eventName = re.sub(r'الحزء\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*م\.?\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*موسم\.?\s*\d+', '', eventName)
    eventName = re.sub(r'[\s_\-]*س\.?\s*\d+', '', eventName)
    eventName = re.sub(r'\bodc\.?\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'\s+\d+:', '', eventName)
    eventName = re.sub(r'[-:]\s*\d+\s*$', '', eventName)
    eventName = re.sub(r'\s+', ' ', eventName).strip()
    return eventName

def getCleanTitle(eventitle=""):
    return eventitle.replace(' ^`^s', '').replace(' ^`^y', '')

def remove_accents(string):
    if not isinstance(string, text_type):
        string = text_type(string, 'utf-8')
    string = sub(u"[àáâãäå]", 'a', string)
    string = sub(u"[èéêë]", 'e', string)
    string = sub(u"[ìíîï]", 'i', string)
    string = sub(u"[òóôõö]", 'o', string)
    string = sub(u"[ùúûü]", 'u', string)
    string = sub(u"[ýÿ]", 'y', string)
    return string

def sanitize_filename(filename):
    sanitized = sub(r'[^\w\s-]', '', filename)
    return sanitized.strip()

def convtext(text=''):
    try:
        if str(text).strip().lower() == "2012":
            return text.strip()
        if not text:
            return ""
        text = str(text).rstrip().strip()
        # a few replacements kept for compatibility
        sostituzioni = [
            ('c.s.i.', 'csi', 'replace'),
            ('ncis:', 'ncis', 'replace'),
            ('superman & lois', 'superman e lois', 'set'),
        ]
        for parola, sostituto, metodo in sostituzioni:
            if parola in text.lower():
                if metodo == 'set':
                    text = sostituto
                    break
                elif metodo == 'replace':
                    text = text.replace(parola, sostituto)
        text = cutName(text)
        text = getCleanTitle(text)
        for junk in ['webhdtv', '1080i', 'dvdrip', 'webrip', 'bluray', 'hdtvrip', 'uncut', 'retail']:
            text = text.replace(junk, '')
        text = remove_accents(text)
        regex = compile(r'^(.*?)([ ._-]*(ep|episodio|st|stag|odc|parte|serie|s[0-9]{1,2}e[0-9]{1,2}|[0-9]{1,2}x[0-9]{1,2}).*)$')
        text = sub(regex, r'\1', text).strip()
        bad_strings = ["1080p", "4k", "720p", "hdrip", "x264"]
        years_to_remove = [str(year) for year in range(1900, 2030)]
        bad_strings.extend(years_to_remove)
        bad_strings_pattern = compile('|'.join(map(re.escape, bad_strings)))
        text = bad_strings_pattern.sub('', text)
        text = re.sub(r'\(\s*(19|20)\d{2}\s*\)', '', text).strip()
        text = sub(r'[^\w\s]+$', '', text)
        text = text.strip(' -')
        text = text.replace('johnq', 'john q')
        text = re.sub(r'\s+', ' ', text).strip()
        return text.capitalize() if text else ""
    except Exception:
        return text

def convtext_display(text=''):
    if not text:
        return ""
    text = cutName(text)
    text = getCleanTitle(text)
    text = remove_accents(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.strip().capitalize()

# quick helper for URL quoting events
def quoteEventName(eventName):
    try:
        text = eventName
        if not PY3:
            text = eventName.decode('utf8').replace(u'\x86', u'').replace(u'\x87', u'').encode('utf8')
    except Exception:
        text = eventName
    try:
        return quote_plus(text, safe="+")
    except Exception:
        return quote_plus(str(text), safe="+")
