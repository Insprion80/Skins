#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
iConverlibr.py
--------------
Utility functions to clean, normalize and sanitize event names
for use in poster search, safe filenames, and title display.

All original functions are preserved to maintain iPosterX compatibility.
Arabic, English, Polish and general episode/season markers are handled.

Added:
 - PosterIndex class: simple JSON-backed index stored in poster folder
   (maps cleaned_title -> poster_filename). LRU capped at 5000 entries.
 - Compact helper methods for index usage.
"""

from re import sub, I, compile
from six import text_type
from unicodedata import normalize
import sys, re, os, json, time

# -------------------------------------------------------------------
# Python 2/3 Compatibility
# -------------------------------------------------------------------
try:
    unicode
except NameError:
    unicode = str

PY3 = False
if sys.version_info[0] >= 3:
    PY3 = True
    import html
    html_parser = html
    from urllib.parse import quote_plus
else:
    from urllib import quote_plus
    from HTMLParser import HTMLParser
    html_parser = HTMLParser()

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def quoteEventName(eventName):
    """
    URL-quote an event name, keeping "+" safe.
    Example:
        "The Big Bang Theory" → "The+Big+Bang+Theory"
    """
    try:
        text = eventName.decode('utf8').replace(u'\x86', u'').replace(u'\x87', u'').encode('utf8')
    except Exception:
        text = eventName
    return quote_plus(text, safe="+")

# -------------------------------------------------------------------
# REGEX - Keep original for compatibility
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
    r'[\(\[\|].*?[\)\]\|]|'                # any bracketed text
    r'(?:\"[\.|\,]?\s.*|\"|'               # text in quotes
    r'\.\s.+)|'                            # ". Something"
    r'Премьера\.\s|'                       # Russian "Premiere."
    r'[хмтдХМТД]/[фf]\s|'                  # Russian markers
    r'\s[СC](?:езон|ериÑ|-н|-Ñ)\s.*|'      # Season/Episode in Russian
    r'\s\d{1,3}\s[чсЧС]\.?\s.*|'           # " 12 ч"
    r'\.\s\d{1,3}\s[чсЧС]\.?\s.*|'         # ". 12 ч"
    r'\s[чсЧС]\.?\s\d{1,3}.*|'             # "ч 12"
    r'\d{1,3}-(?:я|й)\s?с-н.*',            # Russian suffix
    re.DOTALL
)

# -------------------------------------------------------------------
# Unicode Helpers - Keep original
# -------------------------------------------------------------------
def remove_accents(string):
    """
    Remove accents from characters.
    Example:
        "Pokémon" → "Pokemon"
    """
    if not isinstance(string, text_type):
        string = text_type(string, 'utf-8')
    string = sub(u"[àáâãäå]", 'a', string)
    string = sub(u"[èéêë]", 'e', string)
    string = sub(u"[ìíîï]", 'i', string)
    string = sub(u"[òóôõö]", 'o', string)
    string = sub(u"[ùúûü]", 'u', string)
    string = sub(u"[ýÿ]", 'y', string)
    return string

def unicodify(s, encoding='utf-8', norm=None):
    """
    Ensure text is unicode and optionally normalize.
    """
    if not isinstance(s, text_type):
        s = text_type(s, encoding)
    if norm:
        s = normalize(norm, s)
    return s

def str_encode(text, encoding="utf8"):
    """
    Encode text safely if running under Python 2.
    """
    if not PY3:
        if isinstance(text, text_type):
            return text.encode(encoding)
    return text

# -------------------------------------------------------------------
# Poster Index (simple JSON LRU)
# -------------------------------------------------------------------
class PosterIndex(object):
    """
    Keep a small JSON index mapping cleaned_title -> poster_filename.
    Stored inside poster folder (poster_index.json). LRU with size cap.
    Methods:
      - set_path(poster_folder): set where index file lives (default /tmp/XDREAMY/poster)
      - add(clean_title, poster_filename)
      - get_path(clean_title) -> poster_filename or None
      - save(), load()
    """

    _instance = None

    def __init__(self, path_folder=None, max_entries=5000):
        self.max_entries = int(max_entries)
        # default folder
        self.path_folder = path_folder if path_folder else "/tmp/XDREAMY/poster"
        if not os.path.exists(self.path_folder):
            try:
                os.makedirs(self.path_folder)
            except Exception:
                pass
        self.index_file = os.path.join(self.path_folder, "poster_index.json")
        # internal structures: dict + order list for LRU
        self.map = {}        # cleaned_title -> poster_filename
        self.order = []      # oldest -> newest cleaned_title
        self._loaded = False
        self.load()

    @classmethod
    def get_instance(cls, path_folder=None, max_entries=5000):
        if cls._instance is None:
            cls._instance = PosterIndex(path_folder=path_folder, max_entries=max_entries)
        else:
            # if path_folder provided and different, update
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
            # reload from new location
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
                        # backward compatibility: assume dict of map only
                        self.map = data
                        self.order = list(self.map.keys())
            else:
                self.map = {}
                self.order = []
            self._loaded = True
        except Exception:
            # Corrupt index -> recreate
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
            # best-effort, ignore errors
            pass

    def add(self, cleaned_title, poster_filename):
        """
        Add mapping cleaned_title -> poster_filename (filename only, not full path).
        Move to most-recent if exists. Enforce max_entries.
        """
        if not cleaned_title or not poster_filename:
            return
        key = cleaned_title.strip()
        filename = poster_filename.strip()
        # update map and order
        if key in self.map:
            # move to end
            try:
                self.order.remove(key)
            except Exception:
                pass
        self.map[key] = filename
        self.order.append(key)
        # enforce max size
        while len(self.order) > self.max_entries:
            oldest = self.order.pop(0)
            try:
                del self.map[oldest]
            except Exception:
                pass
        # persist
        self.save()

    def get(self, cleaned_title):
        """
        Return filename (not full path) or None.
        """
        if not cleaned_title:
            return None
        key = cleaned_title.strip()
        return self.map.get(key)

    def get_fullpath(self, cleaned_title):
        filename = self.get(cleaned_title)
        if not filename:
            return None
        return os.path.join(self.path_folder, filename)

# Convenience module-level singleton
_poster_index_singleton = None

def init_poster_index(path_folder=None, max_entries=5000):
    global _poster_index_singleton
    _poster_index_singleton = PosterIndex.get_instance(path_folder=path_folder, max_entries=max_entries)
    return _poster_index_singleton

def poster_index_add(cleaned_title, poster_filename):
    global _poster_index_singleton
    if _poster_index_singleton is None:
        init_poster_index()
    _poster_index_singleton.add(cleaned_title, poster_filename)

def poster_index_get_fullpath(cleaned_title):
    global _poster_index_singleton
    if _poster_index_singleton is None:
        init_poster_index()
    return _poster_index_singleton.get_fullpath(cleaned_title)

# -------------------------------------------------------------------
# Cleaning Functions - Keep original names for compatibility
# -------------------------------------------------------------------
def cutName(eventName=""):
    """
    Strip generic labels, ratings, Arabic/English/European episode tags.
    """
    if not eventName:
        return ""

    # Remove quotes and junk markers
    eventName = eventName.replace('"', '').replace('Х/Ф', '').replace('М/Ф', '').replace('Х/ф', '')

    # Ratings
    for tag in ['(18+)', '18+', '(16+)', '16+', '(12+)', '12+', '(7+)', '7+', '(6+)', '6+', '(0+)', '0+', '+']:
        eventName = eventName.replace(tag, '')

    # Common Arabic words
    for word in ['المسلسل العربي', 'مسلسل', 'برنامج', 'فيلم وثائقى', 'حفل']:
        eventName = eventName.replace(word, '')

    # --- Universal episode/season cleanup ---
    # English
    eventName = re.sub(r'\bSeason\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'\bS\d{1,2}\b', '', eventName, flags=I)
    eventName = re.sub(r'\bS\d{1,2}\s*-\s*\d+\b', '', eventName, flags=I)
    eventName = re.sub(r'-?\s*Ep(isode)?\.?\s*\d+\b', '', eventName, flags=I)

    # --- Arabic markers cleanup ---
    # Episodes (ح, حلقة, حلقه, حل)
    eventName = re.sub(r'[\s_\-]*ح\.?\s*\d+', '', eventName)             # ح23 / ح-23 / ح_23
    eventName = re.sub(r'[\s_\-]*حل(?:قة|قه)?\.?\s*\d+', '', eventName)  # حلقة 23 / حلقه 23 / حل 23

    # Parts (ج, جزء)
    eventName = re.sub(r'[\s_\-]*ج\.?\s*\d+', '', eventName)             # ج2 / ج-2 / ج_2
    eventName = re.sub(r'[\s_\-]*جزء\.?\s*\d+', '', eventName)          # جزء 2
    eventName = re.sub(r'الحزء\s*\d+', '', eventName)                   # common typo "الحزء 2"

    # Seasons (م, موسم, س)
    eventName = re.sub(r'[\s_\-]*م\.?\s*\d+', '', eventName)            # م3 / م-3 / م_3
    eventName = re.sub(r'[\s_\-]*موسم\.?\s*\d+', '', eventName)         # موسم 3
    eventName = re.sub(r'[\s_\-]*س\.?\s*\d+', '', eventName)            # س2 / س-2

    # Polish/European "odc."
    eventName = re.sub(r'\bodc\.?\s*\d+\b', '', eventName, flags=I)

    # Cases like "Title 5: odc.2"
    eventName = re.sub(r'\s+\d+:', '', eventName)

    # General trailing numbers
    eventName = re.sub(r'[-:]\s*\d+\s*$', '', eventName)

    # Cleanup spaces
    eventName = re.sub(r'\s+', ' ', eventName).strip()

    return eventName

def getCleanTitle(eventitle=""):
    """
    Final polish of cleaned event title.
    """
    return eventitle.replace(' ^`^s', '').replace(' ^`^y', '')

def sanitize_filename(filename):
    """
    Make safe filename from title.
    """
    sanitized = sub(r'[^\w\s-]', '', filename)
    return sanitized.strip()

# -------------------------------------------------------------------
# Main Converter - Keep EXACT original logic for compatibility
# -------------------------------------------------------------------
def convtext(text=''):
    """
    Clean and normalize EPG text for poster search.
    Kept simple and consistent with the original working version.
    Behavior:
       - If title exactly "2012" (movie) -> return it unchanged
       - Remove season/episode markers, quality junk, years (except "2012" special-case)
       - Remove year in parentheses (e.g. "Troy (2004)" -> "Troy")
       - Preserve basic skeleton and function names for compatibility
    """
    try:
        # special-case: movie called "2012" should be preserved
        if str(text).strip().lower() == "2012":
            return text.strip()
        if not text:
            return ""

        text = str(text).rstrip().strip()

        # Substitutions (common)
        sostituzioni = [
            ('1/2', 'mezzo', 'replace'),
            ('c.s.i.', 'csi', 'replace'),
            ('n.c.i.s.:', 'ncis', 'replace'),
            ('ncis:', 'ncis', 'replace'),
            ('ritorno al futuro:', 'ritorno al futuro', 'replace'),
            ('superman & lois', 'superman e lois', 'set'),
            ('lois & clark', 'superman e lois', 'set'),
            ('una 44 magnum per', 'magnumxx', 'set'),
            ('john q', 'johnq', 'set'),
            ('il ritorno di colombo', 'colombo', 'set'),
            ('lingo: parole', 'lingo', 'set'),
            ('io & marilyn', 'io e marilyn', 'set'),
            ('giochi olimpici parigi', 'olimpiadi di parigi', 'set'),
        ]

        for parola, sostituto, metodo in sostituzioni:
            if parola in text.lower():
                if metodo == 'set':
                    text = sostituto
                    break
                elif metodo == 'replace':
                    text = text.replace(parola, sostituto)

        # Core cleaning
        text = cutName(text)
        text = getCleanTitle(text)

        # Remove common junk
        for junk in ['webhdtv', '1080i', 'dvdrip', 'webrip', 'bluray', 'hdtvrip', 'uncut', 'retail']:
            text = text.replace(junk, '')

        text = remove_accents(text)

        # Strip episode markers (English/European style)
        regex = compile(r'^(.*?)([ ._-]*(ep|episodio|st|stag|odc|parte|serie|s[0-9]{1,2}e[0-9]{1,2}|[0-9]{1,2}x[0-9]{1,2}).*)$')
        text = sub(regex, r'\1', text).strip()

        # Remove bad strings and years (bare years)
        bad_strings = ["1080p", "4k", "720p", "hdrip", "x264"]
        years_to_remove = [str(year) for year in range(1900, 2030)]
        bad_strings.extend(years_to_remove)
        bad_strings_pattern = compile('|'.join(map(re.escape, bad_strings)))
        text = bad_strings_pattern.sub('', text)

        # --- NEW: Remove year in parentheses e.g. "Troy (2004)" -> "Troy" ---
        # This specifically strips (YYYY) groups.
        text = re.sub(r'\(\s*(19|20)\d{2}\s*\)', '', text).strip()

        # Strip punctuation at end
        text = sub(r'[^\w\s]+$', '', text)
        text = text.strip(' -')

        # Final replacements
        text = text.replace('magnumxx', "una 44 magnum per l ispettore")
        text = text.replace('johnq', 'john q')

        # Ensure no leading/trailing spaces and capitalized first letter
        text = re.sub(r'\s+', ' ', text).strip()
        return text.capitalize() if text else ""
    except Exception as e:
        print('convtext error:', e)
        return text

# -------------------------------------------------------------------
# Display-friendly converter
# -------------------------------------------------------------------
def convtext_display(text=''):
    """
    Clean the title for display purposes ONLY, keeping original poster search intact.
    """
    if not text:
        return ""
    text = cutName(text)
    text = getCleanTitle(text)
    text = remove_accents(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.strip().capitalize()

# -------------------------------------------------------------------
# Test block
# -------------------------------------------------------------------
if __name__ == "__main__":
    # Initialize index for local testing
    init_poster_index()
    samples = [
        "Troy (2004)",
        "Firebuds: Season 1 - 15",
        "Puppy Dog Pals S1 - 16",
        "Sanjay And Craig Short - Ep. 14",
        "Fairly Odd Parents-Season 10 - Ep. 154",
        "Wszyscy kochają Raymonda 8: odc.20",
        "Zbrodnia po angielsku: odc.2",
        "Dragonball Z Kai: odc.71",
        "الحقيقة والسراب _ح28",
        "2012",
    ]
    for s in samples:
        print("RAW: %s  -->  CLEAN: %s  DISPLAY: %s" % (s, convtext(s), convtext_display(s)))