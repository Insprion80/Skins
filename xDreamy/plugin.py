# -*- coding: utf-8 -*-
# mod by Lululla
# mod by M.Hussein using AI

import os
import random
import sys
import time
import shutil
import glob
import re
import gettext
import locale
import requests
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen
from . import _
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.config import (
    configfile,
    ConfigOnOff,
    NoSave,
    ConfigText,
    ConfigSelection,
    ConfigSubsection,
    ConfigYesNo,
    config,
    getConfigListEntry,
    ConfigNothing,
)
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.Sources.Progress import Progress
from Components.Sources.StaticText import StaticText
from enigma import eTimer, loadPic
try:
    from PIL import Image
except ImportError:
    from Image import Image
from Plugins.Plugin import PluginDescriptor
from Screens.Console import Console
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Tools.Directories import fileExists, SCOPE_PLUGINS, resolveFilename
from Tools.Downloader import downloadWithProgress
from Screens.ChoiceBox import ChoiceBox
from Screens.LocationBox import LocationBox
from enigma import gFont
import logging
from logging.handlers import RotatingFileHandler

# Set up logging
log_file = '/tmp/XDREAMY_Plugin.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5),  # 1MB per file, max 5 files
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)                                   

# Update the localization setup
plugin_name = "xDreamy"
locale_path = resolveFilename(SCOPE_PLUGINS, f"Extensions/{plugin_name}/locale")
gettext.bindtextdomain(plugin_name, locale_path)
gettext.textdomain(plugin_name)
_ = gettext.gettext

# Check if running on Python 3
PY3 = sys.version_info.major >= 3

# Plugin version
version = "5.9.9" # New Merge
my_cur_skin = False
cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')

# Paths for weather plugins and boot logos
OAWeather = resolveFilename(SCOPE_PLUGINS, "Extensions/OAWeather")
weatherz = resolveFilename(SCOPE_PLUGINS, "Extensions/WeatherPlugin")
mvi = '/usr/share/'
bootlog = '/usr/lib/enigma2/python/Plugins/Extensions/xDreamy/bootlogos/'
logopath = '/etc/enigma2/'

# Paths for API keys
tmdb_skin = f"{mvi}enigma2/{cur_skin}/apikey"
tmdb_api = "3c3efcf47c3577558812bb9d64019d65"
omdb_skin = f"{mvi}enigma2/{cur_skin}/omdbkey"
omdb_api = "cb1d9f55"
thetvdb_skin = f"{mvi}enigma2/{cur_skin}/thetvdbkey"
thetvdb_api = "a99d487bb3426e5f3a60dea6d3d3c7ef"
fanart_skin = f"{mvi}enigma2/{cur_skin}/fanartkey"
fanart_api = "6d231536dea4318a88cb2520ce89473b"

# Load API keys from skin paths if available
try:
    if not my_cur_skin:
        skin_paths = {
            "tmdb_api": f"/usr/share/enigma2/{cur_skin}/apikey",
            "omdb_api": f"/usr/share/enigma2/{cur_skin}/omdbkey",
            "thetvdb_api": f"/usr/share/enigma2/{cur_skin}/thetvdbkey",
            "fanart_api": f"/usr/share/enigma2/{cur_skin}/fanartkey",
        }
        for key, path in skin_paths.items():
            if fileExists(path):
                with open(path, "r") as f:
                    value = f.read().strip()
                    if key == "tmdb_api":
                        tmdb_api = value
                        config.plugins.xDreamy.api.setValue(True)
                    elif key == "omdb_api":
                        omdb_api = value
                        config.plugins.xDreamy.api2.setValue(True)
                    elif key == "thetvdb_api":
                        thetvdb_api = value
                        config.plugins.xDreamy.api3.setValue(True)
                    elif key == "fanart_api":
                        fanart_api = value
                        config.plugins.xDreamy.api4.setValue(True)
                my_cur_skin = True
except Exception as e:
    logger.error(_("Error loading API keys: {error}").format(error=e))
    my_cur_skin = False

def isMountedInRW(path):
    """Check if the given path is mounted in read-write mode."""
    testfile = os.path.join(path, 'tmp-rw-test')
    try:
        with open(testfile, 'w') as f:
            f.write('test')
        os.remove(testfile)
        return True
    except Exception as e:
        logger.error(_("Error checking RW mount for {path}: {error}").format(path=path, error=e))
        return False

# Paths for poster and backdrop images
path_poster = "/tmp/poster"
patch_backdrop = "/tmp/backdrop"
if os.path.exists("/media/hdd") and isMountedInRW("/media/hdd"):
    path_poster = "/media/hdd/poster"
    patch_backdrop = "/media/hdd/backdrop"
elif os.path.exists("/media/usb") and isMountedInRW("/media/usb"):
    path_poster = "/media/usb/poster"
    patch_backdrop = "/media/usb/backdrop"
elif os.path.exists("/media/mmc") and isMountedInRW("/media/mmc"):
    path_poster = "/media/mmc/poster"
    patch_backdrop = "/media/mmc/backdrop"

def removePng():
    """Remove all PNG and JPG files from the poster and backdrop directories."""
    logger.info(_('Removing PNG and JPG files...'))
    for folder in [path_poster, patch_backdrop]:
        if os.path.exists(folder):
            for ext in ["*.png", "*.jpg"]:
                files = glob.glob(os.path.join(folder, ext))
                for file in files:
                    try:
                        os.remove(file)
                        logger.info(_("Removed: {file}").format(file=file))
                    except Exception as e:
                        logger.error(_("Error removing {file}: {error}").format(file=file, error=e))
        else:
            logger.warning(_("Folder {folder} does not exist.").format(folder=folder))

# Configuration settings for the plugin
config.plugins.xDreamy = ConfigSubsection()
config.plugins.xDreamy.ShowInExtensions = ConfigYesNo(default=False)
config.plugins.xDreamy.png = NoSave(ConfigYesNo(default=False))
config.plugins.xDreamy.header = NoSave(ConfigNothing())
config.plugins.xDreamy.weather = NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.oaweather = NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.city = ConfigText(default='', visible_width=50, fixed_size=False)
config.plugins.xDreamy.actapi = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.data = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api = ConfigYesNo(default=False)
config.plugins.xDreamy.txtapi = ConfigText(default=tmdb_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.data2 = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api2 = ConfigYesNo(default=False)
config.plugins.xDreamy.txtapi2 = ConfigText(default=omdb_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.data3 = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api3 = ConfigYesNo(default=False)
config.plugins.xDreamy.txtapi3 = ConfigText(default=thetvdb_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.data4 = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api4 = ConfigYesNo(default=False)
config.plugins.xDreamy.txtapi4 = ConfigText(default=fanart_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.bootlogos = ConfigOnOff(default=False)
config.plugins.xDreamy.enablePosterX = ConfigYesNo(default=True)
#config.plugins.xDreamy.posterLocation = ConfigText(default="/tmp", visible_width=50, fixed_size=False)

# Add new config entries for plugin installations
plugin_names = [
    "ajpanel", "linuxsatpanel", "CiefpPlugins", "smartpanel", "elisatpanel", "magicpanel",
    "msnweather", "oaweather", "multicammanager", "NCam", "keyadder",
    "xklass", "youtube", "e2iplayer", "ipaudiopro", "transmission",
    "multistalkerpro", "EPGGrabber", "subssupport", "historyzapselector",
    "newvirtualkeyboard", "raedquicksignal"
]
for plugin in plugin_names:
    setattr(config.plugins.xDreamy, f"install_{plugin}", NoSave(ConfigYesNo(default=False)))

# Light Color(ltbluette), Standard Color (bluette), Background Color (header)
TEMPLATES = {
    'Blue':           ('#64b5f6', '#1e88e5', '#000d47a1'),
    'Brown':          ('#d7ccc8', '#8d6e63', '#004e342e'),
    'Cyan':           ('#80deea', '#00acc1', '#00006064'),
    'Gold':           ('#ffecb3', '#ffc107', '#00ffa000'),
    'Green':          ('#a5d6a7', '#43a047', '#001b5e20'),
    'Grey':           ('#e0e0e0', '#9e9e9e', '#00424242'),
    'Maroon':         ('#ef9a9a', '#d32f2f', '#00880e4f'),
    'Magenta':        ('#f48fb1', '#e91e63', '#00880e4f'),
    'Navy':           ('#90caf9', '#1565c0', '#000d47a1'),
    'Orange':         ('#ffcc80', '#fb8c00', '#00e65100'),
    'Olive':          ('#e6ee9c', '#afb42b', '#00827717'),
    'Red':            ('#ef9a9a', '#f44336', '#00b71c1c'),
    'Pink':           ('#f8bbd0', '#ec407a', '#00880e4f'),
    'Purple':         ('#ce93d8', '#8e24aa', '#004a148c'),
    'Teal':           ('#80cbc4', '#009688', '#00004d40'),
    'Violet':         ('#b39ddb', '#7e57c2', '#004527a0'),
    'Lime':           ('#dce775', '#cddc39', '#00827717'),
    'Salmon':         ('#ffab91', '#ff7043', '#00bf360c'),
    'Turquoise':      ('#a7ffeb', '#1de9b6', '#00004d40'),
    'Crimson':        ('#ffcdd2', '#e53935', '#00b71c1c'),
    'Sand':           ('#fff8e1', '#fbc02d', '#00f57f17'),
    'Midnight Blue':  ('#bbdefb', '#2196f3', '#001a237e'),
    'Jungle Green':   ('#dcedc8', '#8bc34a', '#0033691e'),
    'Forest Green':   ('#c5e1a5', '#689f38', '#0033691e'),
    'Steel':          ('#cfd8dc', '#607d8b', '#0037474f'),
    'Ruby':           ('#fce4ec', '#d81b60', '#00880e4f'),
    'Sky Blue':       ('#B3E5FC', '#2196F3', '#000D47A1'),
    'Earth Brown':    ('#D7CCC8', '#8D6E63', '#004E342E'),
    'Aqua Cyan':      ('#B2EBF2', '#00BCD4', '#00006064'),
    'Pyramids Gold':  ('#FFE082', '#FFC107', '#00FFA000'),
    'Mint Green':     ('#C8E6C9', '#4CAF50', '#001B5E20'),
    'Silver Grey':    ('#E0E0E0', '#9E9E9E', '#00424242'),
    'Nile Maroon':    ('#EF9A9A', '#D32F2F', '#00880E4F'),
    'Rose Magenta':   ('#F48FB1', '#E91E63', '#00880E4F'),
    'Deep Navy':      ('#90CAF9', '#1976D2', '#000D47A1'),
    'Desert Orange':  ('#FFCC80', '#FF9800', '#00E65100'),
    'Olive Branch':   ('#F0F4C3', '#C0CA33', '#00827717'),
    'Peach Pink':     ('#F8BBD0', '#EC407A', '#00880E4F'),
    'Royal Purple':   ('#CE93D8', '#9C27B0', '#004A148C'),
    'Cyber Teal':     ('#B2DFDB', '#009688', '#00004D40'),
    'Violet Dream':   ('#D1C4E9', '#673AB7', '#00311B92'),
    'Lime Juice':     ('#E6EE9C', '#CDDC39', '#00827717'),
    'Salmon Skin':    ('#FFAB91', '#FF7043', '#00BF360C'),
    'Turquoise Sea':  ('#A7FFEB', '#1DE9B6', '#00004D40'),
    'Crimson Flame':  ('#FFCDD2', '#E53935', '#00B71C1C'),
    'Egyptian Sand':  ('#FFF8E1', '#FBC02D', '#00F57F17'),
    'Midnight Blue':  ('#BBDEFB', '#2196F3', '#001A237E'),
    'Kemet Earth':    ('#E0F2F1', '#00796B', '#00004D40'),
    'Ruby Rose':      ('#FCE4EC', '#D81B60', '#00880E4F'),
    'Steel Grey':     ('#CFD8DC', '#607D8B', '#0037474F'),
    'Egypt Blue':     ('#81D4FA', '#0288D1', '#0001579B'),
    'Egypt Sunset':   ('#FFECB3', '#FFA726', '#00F57C00'),
    'Egypt Dunes':    ('#FFF9C4', '#FBC02D', '#00F57F17'),
    'Egypt Classic':  ('#E0E0E0', '#757575', '#00212121'),
    'Egypt Jungle':   ('#DCEDC8', '#8BC34A', '#0033691E'),
    'Egypt Forest':   ('#C5E1A5', '#689F38', '#0033691E'),
    'Egypt Pyramids': ('#FFF59D', '#FDD835', '#00F57F17'),
    'Egypt Kemet':    ('#FFF3B0', '#E0A800', '#00795548'),
    'Egypt Sand':     ('#FFE0B2', '#FB8C00', '#00E65100'),
    'Egypt Sun':      ('#FFF9C4', '#FDD835', '#00F57F17'),
    'Blue-Black':     ('#B3E5FC', '#2196F3', '#00000000'),
    'Brown-Black':    ('#D7CCC8', '#8D6E63', '#00000000'),
    'Green-Black':    ('#C8E6C9', '#4CAF50', '#00000000'),
    'Grey-Black':     ('#E0E0E0', '#9E9E9E', '#00000000'),
    'Maroon-Black':   ('#EF9A9A', '#D32F2F', '#00000000'),
    'Orange-Black':   ('#FFCC80', '#FB8C00', '#00000000'),
    'Pink-Black':     ('#F8BBD0', '#F06292', '#00000000'),
    'Purple-Black':   ('#CE93D8', '#BA68C8', '#00000000'),
    'Teal-Black':     ('#B2DFDB', '#4DB6AC', '#00000000'),
    'Gold-Black':     ('#FFF8E1', '#FFD600', '#00000000'),
    'Red-Black':      ('#FFCDD2', '#F44336', '#00000000')
}

# SKIN GENERAL SETUP
config.plugins.xDreamy.head = ConfigSelection(default='head', choices=[('head', _('Default'))])
config.plugins.xDreamy.skinSelector = ConfigSelection(default='base', choices=[('base', _('Default'))])
config.plugins.xDreamy.skinTemplate = ConfigSelection(default='templates', choices=[
    ('templates', _('Default')),
    ('templates1', _('Style1')),
    ('templates2', _('Style2')),
    ('templates3', _('Style3')),
    ('templates4', _('Style4')),
    ('templates5', _('Style5')),
    ('templates6', _('Style6')),
    ('templates7', _('Style7')),
    ('templates8', _('Style8'))])

config.plugins.xDreamy.KeysStyle = ConfigSelection(default='keys', choices=[
    ('keys', _('Default')),
    ('keys1', _('Keys1')),
    ('keys2', _('Keys2')),
    ('keys3', _('Keys3')),
    ('keys4', _('Keys4')),
    ('keys5', _('Keys5')),
    ('keys6', _('Keys6'))])

config.plugins.xDreamy.clockFormat = ConfigSelection(default="DigitalClock", choices=[
    ('DigitalClock', _('23:59 (24 hrs)')),
    ('DigitalClock1', _('23:59:33 (24 hrs)')),
    ('DigitalClock2', _('12:59 (12 hrs)')),
    ('DigitalClock3', _('12:59 AM (12 hrs)')),
    ('DigitalClock4', _('12:59 AM (12 hrs- MultiSize)')),
    ('DigitalClock5', _('12:59:33 (12 hrs- MultiSize)'))])

config.plugins.xDreamy.dateFormat = ConfigSelection(default="%d %B %Y", choices=[
    ("%d %B %Y", "01 January 2025"),
    ("%d %B %y", "01 January 25"),
    ("%d %b %Y", "01 Jan 2025"),
    ("%d %b %y", "01 Jan 25"),
    ("%d-%m-%Y", "01-01-2025"),
    ("%d-%m-%y", "01-01-25"),
    ("%Y-%m-%d", "2025-01-01"),
    ("%y-%m-%d", "25-01-01"),  
    ("%m/%d/%Y", "01/01/2025"),
    ("%m/%d/%y", "01/01/25"),
    ("%d/%m/%Y", "01/01/2025"),
    ("%d/%m/%y", "01/01/25"),
    ("%Y/%m/%d %A", "2025/01/01 Monday"),
    ("%Y/%m/%d %a", "2025/01/01 Mon"),
    ("%Y.%m.%d", "2025.01.01"),
    ("%y.%m.%d", "25.01.01"),
    ("%A, %d %B %Y", "Monday, 01 January 2025"),
    ("%a, %d %b %Y", "Mon, 01 Jan 2025"),
    ("%A %d %B %Y", "Monday 01 January 2025"),
    ("%a %d %b %Y", "Mon 01 Jan 2025"),
    ("%d %B, %Y", "01 January, 2025"),
    ("%d %b, %Y", "01 Jan, 2025"),
    ("%B %d, %Y", "January 01, 2025"), 
    ("%b %d, %Y", "Jan 01, 2025"), 
    ("%Y %B %d", "2025 January 01"),
    ("%Y %b %d", "2025 Jan 01"),
    ("%y %B %d", "25 January 01"),
    ("%y %b %d", "25 Jan 01"),
    ("%d.%m.%Y", "01.01.2025"),
    ("%d.%m.%y", "01.01.25"),
    ("%d %m %Y", "01 01 2025"),
    ("%A, %d %m %Y", "Monday, 01 01 2025"),
    ("%a, %d %m %Y", "Mon, 01 01 2025"),
    ("%d %m %y", "01 01 25")])

#=============================== SKIN COLORS =============================
# Skin Color Selection
config.plugins.xDreamy.colorSelector = ConfigSelection(default='default-color', choices=[
    ('default-color', _('Default')),
    ('color23_Custom', _('Custom'))])

# Skin Color Templates
config.plugins.xDreamy.BasicColorTemplates = ConfigSelection(default='Blue',
    choices=[(key, _(key)) for key in TEMPLATES.keys()])

# BasicColor → ltbluette (Light/Text Color)
config.plugins.xDreamy.BasicColor = ConfigSelection(default='#ffffff', choices=[
    ('#FFFFFF', _('Default White')),
    ('#B3E5FC', _('Sky Blue')),
    ('#D7CCC8', _('Earth Brown')),
    ('#B2EBF2', _('Aqua Cyan')),
    ('#FFE082', _('Pyramids Gold')),
    ('#C8E6C9', _('Mint Green')),
    ('#E0E0E0', _('Silver Grey')),
    ('#EF9A9A', _('Nile Maroon')),
    ('#F48FB1', _('Rose Magenta')),
    ('#90CAF9', _('Deep Navy')),
    ('#FFCC80', _('Desert Orange')),
    ('#F0F4C3', _('Olive Branch')),
    ('#F8BBD0', _('Peach Pink')),
    ('#CE93D8', _('Royal Purple')),
    ('#B2DFDB', _('Cyber Teal')),
    ('#D1C4E9', _('Violet Dream')),
    ('#E6EE9C', _('Lime Juice')),
    ('#FFAB91', _('Salmon Skin')),
    ('#A7FFEB', _('Turquoise Sea')),
    ('#FFCDD2', _('Crimson Flame')),
    ('#FFF8E1', _('Egyptian Sand')),
    ('#BBDEFB', _('Midnight Blue')),
    ('#E0F2F1', _('Kemet Earth')),
    ('#FCE4EC', _('Ruby Rose')),
    ('#CFD8DC', _('Steel Grey')),
    ('#0049bbff', _('Egypt L.Blue')),
    ('#FF8C00', _('Egypt L.Sunset')),
    ('#D6CDAF', _('Egypt L.Dunes')),
    ('#BFBFBF', _('Egypt L.Classic')),
    ('#A3C9A8', _('Egypt L.Jungle')),
    ('#D9CBA0', _('Egypt L.Forest')),
    ('#ffb703', _('Egypt L.Pyramids')),
    ('#fff3b0', _('Egypt L.Kemet')),
    ('#fb8b24', _('Egypt L.Sand')),
    ('#c9cba3', _('Egypt L.Sun')),
    ('#03a0ff', _('L.Blue')),
    ('#F0CA6D', _('L.Brown')),
    ('#64E33E', _('L.Green')),
    ('#9f9f9f', _('L.Grey')),
    ('#bc7a80', _('L.Maroon')),
    ('#ff9200', _('L.Orange')),
    ('#F56EB3', _('L.Pink')),
    ('#836FFF', _('L.Purple')),
    ('#66b2b2', _('L.Teal')),
    ('#ffee00', _('L.Gold')),
    ('#ff7b7b', _('L.Red')),
    ('#89c2d9', _('L.Cold Blue')),
    ('#CDC7BE', _('L.Cold Brown')),
    ('#C4DFAA', _('L.Cold Green')),
    ('#9BABB3', _('L.Cold Grey')),
    ('#CC18A8', _('L.Cold Maroon')),
    ('#D960AE', _('L.Cold Pink')),
    ('#7520F2', _('L.Cold Purple')),
    ('#3F85BF', _('L.Cold Teal'))
])


# Skin White Text Color  ltbluette (Light/Text Color)
config.plugins.xDreamy.WhiteColor = ConfigSelection(default='#ffffff', choices=[
    ('#FFFFFF', _('Default White')),
    ('#B3E5FC', _('Sky Blue')),
    ('#D7CCC8', _('Earth Brown')),
    ('#B2EBF2', _('Aqua Cyan')),
    ('#FFE082', _('Pyramids Gold')),
    ('#C8E6C9', _('Mint Green')),
    ('#E0E0E0', _('Silver Grey')),
    ('#EF9A9A', _('Nile Maroon')),
    ('#F48FB1', _('Rose Magenta')),
    ('#90CAF9', _('Deep Navy')),
    ('#FFCC80', _('Desert Orange')),
    ('#F0F4C3', _('Olive Branch')),
    ('#F8BBD0', _('Peach Pink')),
    ('#CE93D8', _('Royal Purple')),
    ('#B2DFDB', _('Cyber Teal')),
    ('#D1C4E9', _('Violet Dream')),
    ('#E6EE9C', _('Lime Juice')),
    ('#FFAB91', _('Salmon Skin')),
    ('#A7FFEB', _('Turquoise Sea')),
    ('#FFCDD2', _('Crimson Flame')),
    ('#FFF8E1', _('Egyptian Sand')),
    ('#BBDEFB', _('Midnight Blue')),
    ('#E0F2F1', _('Kemet Earth')),
    ('#FCE4EC', _('Ruby Rose')),
    ('#CFD8DC', _('Steel Grey')),
    ('#0049bbff', _('Egypt L.Blue')),
    ('#FF8C00', _('Egypt L.Sunset')),
    ('#D6CDAF', _('Egypt L.Dunes')),
    ('#BFBFBF', _('Egypt L.Classic')),
    ('#A3C9A8', _('Egypt L.Jungle')),
    ('#D9CBA0', _('Egypt L.Forest')),
    ('#ffb703', _('Egypt L.Pyramids')),
    ('#fff3b0', _('Egypt L.Kemet')),
    ('#fb8b24', _('Egypt L.Sand')),
    ('#c9cba3', _('Egypt L.Sun')),
    ('#03a0ff', _('L.Blue')),
    ('#F0CA6D', _('L.Brown')),
    ('#64E33E', _('L.Green')),
    ('#9f9f9f', _('L.Grey')),
    ('#bc7a80', _('L.Maroon')),
    ('#ff9200', _('L.Orange')),
    ('#F56EB3', _('L.Pink')),
    ('#836FFF', _('L.Purple')),
    ('#66b2b2', _('L.Teal')),
    ('#ffee00', _('L.Gold')),
    ('#ff7b7b', _('L.Red')),
    ('#89c2d9', _('L.Cold Blue')),
    ('#CDC7BE', _('L.Cold Brown')),
    ('#C4DFAA', _('L.Cold Green')),
    ('#9BABB3', _('L.Cold Grey')),
    ('#CC18A8', _('L.Cold Maroon')),
    ('#D960AE', _('L.Cold Pink')),
    ('#7520F2', _('L.Cold Purple')),
    ('#3F85BF', _('L.Cold Teal'))
])

# Skin Selection Color → bluette (Standard color)
config.plugins.xDreamy.SelectionColor = ConfigSelection(default='#1e88e5', choices=[
    ('#2196F3', _('Sky Blue')),
    ('#8D6E63', _('Earth Brown')),
    ('#00BCD4', _('Aqua Cyan')),
    ('#FFC107', _('Pyramids Gold')),
    ('#4CAF50', _('Mint Green')),
    ('#9E9E9E', _('Silver Grey')),
    ('#D32F2F', _('Nile Maroon')),
    ('#E91E63', _('Rose Magenta')),
    ('#1976D2', _('Deep Navy')),
    ('#FF9800', _('Desert Orange')),
    ('#C0CA33', _('Olive Branch')),
    ('#EC407A', _('Peach Pink')),
    ('#9C27B0', _('Royal Purple')),
    ('#009688', _('Cyber Teal')),
    ('#673AB7', _('Violet Dream')),
    ('#CDDC39', _('Lime Juice')),
    ('#FF7043', _('Salmon Skin')),
    ('#1DE9B6', _('Turquoise Sea')),
    ('#E53935', _('Crimson Flame')),
    ('#FBC02D', _('Egyptian Sand')),
    ('#2196F3', _('Midnight Blue')),
    ('#00796B', _('Kemet Earth')),
    ('#D81B60', _('Ruby Rose')),
    ('#607D8B', _('Steel Grey')),
    ('#001b3c85', _('Egypt Blue')),
    ('#A0522D', _('Egypt Sunset')),
    ('#A67C3D', _('Egypt Dunes')),
    ('#4B4B4B', _('Egypt Classic')),
    ('#6B8E23', _('Egypt Jungle')),
    ('#A67C2D', _('Egypt Forest')),
    ('#fb8500', _('Egypt Pyramids')),
    ('#e09f3e', _('Egypt Kemet')),
    ('#e09f3e', _('Egypt Sand')),
    ('#c9cba3', _('Egypt Sun')),
    ('#2f00ff', _('Blue')),
    ('#3F2305', _('Brown')),
    ('#275918', _('Green')),
    ('#424242', _('Grey')),
    ('#800000', _('Maroon')),
    ('#ff5a00', _('Orange')),
    ('#F72798', _('Pink')),
    ('#7F27FF', _('Purple')),
    ('#006666', _('Teal')),
    ('#aa7700', _('Gold')),
    ('#ff0000', _('Red')),
    ('#013C66', _('Cold Blue')),
    ('#593E3E', _('Cold Brown')),
    ('#1E5951', _('Cold Green')),
    ('#43494D', _('Cold Grey')),
    ('#4D093F', _('Cold Maroon')),
    ('#592848', _('Cold Pink')),
    ('#310E66', _('Cold Purple')),
    ('#224766', _('Cold Teal'))
])

# Skin Background Color → header (Dark background)
config.plugins.xDreamy.BackgroundColor = ConfigSelection(default='#00000000', choices=[
    ('#00000000', _('Black')),
    ('#20000000', _('Transparent 1')),
    ('#40000000', _('Transparent 2')),
    ('#60000000', _('Transparent 3')),
    ('#000D47A1', _('Sky Blue')),
    ('#004E342E', _('Earth Brown')),
    ('#00006064', _('Aqua Cyan')),
    ('#00FFA000', _('Pyramids Gold')),
    ('#001B5E20', _('Mint Green')),
    ('#00424242', _('Silver Grey')),
    ('#00880E4F', _('Nile Maroon')),
    ('#00880E4F', _('Rose Magenta')),
    ('#000D47A1', _('Deep Navy')),
    ('#00E65100', _('Desert Orange')),
    ('#00827717', _('Olive Branch')),
    ('#00880E4F', _('Peach Pink')),
    ('#004A148C', _('Royal Purple')),
    ('#00004D40', _('Cyber Teal')),
    ('#00311B92', _('Violet Dream')),
    ('#00827717', _('Lime Juice')),
    ('#00BF360C', _('Salmon Skin')),
    ('#00004D40', _('Turquoise Sea')),
    ('#00B71C1C', _('Crimson Flame')),
    ('#00F57F17', _('Egyptian Sand')),
    ('#001A237E', _('Midnight Blue')),
    ('#00004D40', _('Kemet Earth')),
    ('#00880E4F', _('Ruby Rose')),
    ('#0037474F', _('Steel Grey')),
    ('#05011D33', _('Cold Blue')),
    ('#05332323', _('Cold Brown')),
    ('#0511332E', _('Cold Green')),
    ('#05212526', _('Cold Grey')),
    ('#0526051F', _('Cold Maroon')),
    ('#05331729', _('Cold Pink')),
    ('#05190733', _('Cold Purple')),
    ('#05112333', _('Cold Teal'))
])

config.plugins.xDreamy.transparency = ConfigSelection(default="00", choices=[
    ("00", _("Opaque")),
    ("05", _("5%")),
    ("10", _("10%")),
    ("15", _("15%")),
    ("20", _("20%")),
    ("25", _("25%")),
    ("30", _("30%")),
    ("35", _("35%")),
    ("40", _("40%")),
    ("45", _("45%")),
    ("50", _("50%")),
    ("55", _("55%")),
    ("60", _("60%")),
    ("65", _("65%")),
    ("70", _("70%")),
    ("75", _("75%")),
    ("80", _("80%")),
    ("85", _("85%")),
    ("90", _("90%")),
    ("95", _("95%")),
    ("99", _("Transparent"))])

#================================ SKIN FONTS =============================
# Font Style Selection 
config.plugins.xDreamy.FontStyle = ConfigSelection(default='default', choices=[
    ('default', _('Default')),
    ('basic', _('Custom'))])

# Font Name
config.plugins.xDreamy.FontName = ConfigSelection(default='Verdana.ttf', choices=[
    ('Verdana.ttf', _('Default')),
    ('Andlso.ttf', _('Andlso')),
    ('Beiruti-Regular.ttf', _('Beiruti')),
    ('BonaNovaSC-Regular.ttf', _('BonaNovaSC')),
    ('Dubai-REGULAR.ttf', _('Dubai')),
    ('ElMessiri-Regular.ttf', _('ElMessiri')),
    ('Fustat-Regular.ttf', _('Fustat')),
    ('Nmsbd.ttf', _('Nmsbd')),
    ('Lucida.ttf', _('Lucida')),
    ('Majalla.ttf', _('Majalla')),
    ('Mvboli.ttf', _('Mvboli')),
    ('NaskhArabic-Regular.ttf', _('Naskh')),
    ('PlexSansArabic-Regular.ttf', _('PlexSans')),
    ('ReadexPro-Regular.ttf', _('ReadexPro')),
    ('Rubik-Regular.ttf', _('Rubik')),
    ('Tajawal-Regular.ttf', _('Tajawal')),
    ('Zain-Regular.ttf', _('Zain'))])

#Font Scale
config.plugins.xDreamy.FontScale = ConfigSelection(default="100", choices=[
    ('100', _('Default')),
    ('105', _('5%')),
    ('110', _('10%')),
    ('115', _('15%')),
    ('120', _('20%')),
    ('125', _('25%')),
    ('130', _('30%')),
    ('135', _('35%')),
    ('95', _('-5%')),
    ('90', _('-10%')),
    ('85', _('-15%')),
    ('80', _('-20%')),
    ('75', _('-25%'))])

#================================ INFOBAR ================================
# INFOBAR Templates
config.plugins.xDreamy.InfobarStyle = ConfigSelection(default='InfoBar-1P', choices=[
    ('InfoBar-1P', _('Default')),
    ('InfoBar-2P', _('InfoBar-2P')),
    ('InfoBar-NP', _('InfoBar1-NP')),
    ('InfoBar2-NP', _('InfoBar2-NP')),
    ('InfoBar2-1P', _('InfoBar2-1P')),
    ('InfoBar2-2P', _('InfoBar2-2P')),
    ('InfoBar2-1PW', _('InfoBar2-1PW')),
    ('InfoBar-HMF', _('Custom - InfoBar'))])
# INFOBAR Header
config.plugins.xDreamy.InfobarH = ConfigSelection(default='No Header', choices=[
    ('No Header', _('Default- No Header')),
    ('InfoBar H1', _('H01- EMU/Network/Card')),
    ('InfoBar H2', _('H02- Current & Next Three Days Weather')),
    ('InfoBar H3', _('H03- Slim Header'))])
# INFOBAR Middle
config.plugins.xDreamy.InfobarM = ConfigSelection(default='No Middle', choices=[
    ('No Middle', _('Default- No Middle')),
    ('InfoBar M1', _('M01- ')),
    ('InfoBar M2', _('M02- ')),
    ('InfoBar M3', _('M03- ')),
    ('InfoBar M4', _('M04- '))])
# INFOBAR Footer
config.plugins.xDreamy.InfobarF = ConfigSelection(default='No Footer', choices=[
    ('No Footer', _('Default- No Footer')),
    ('InfoBar F1', _('F01')),
    ('InfoBar F2', _('F02')),
    ('InfoBar F3', _('F03')),
    ('InfoBar F4', _('F04'))])

#============================== SECONDINFOBAR ============================
# SECONDINFOBAR TEMPLATES
config.plugins.xDreamy.SecondInfobar = ConfigSelection(default='SecondInfobar-2P', choices=[
    ('SecondInfobar-2P', _('Default')),
    ('SecondInfobar-NP', _('SecondInfobar-NP')),
    ('SecondInfobar-2PN', _('SecondInfobar-2PN')),
    ('SecondInfobar-2PN2', _('SecondInfobar-2PN2')),
    ('SecondInfobar-HF', _('Custom - SecondInfobar'))])
# SECONDINFOBAR Header
config.plugins.xDreamy.SecondInfobarH = ConfigSelection(default='SecondInfobarH01', choices=[
    ('SecondInfobarH01', _('Default')),
    ('SecondInfobarH02', _('S.InfobarH S1-2E-2P')),
    ('SecondInfobarH03', _('S.InfobarH S2-2E-NP')),
    ('SecondInfobarH04', _('S.InfobarH S2-2E-2P')),
    ('SecondInfobarH05', _('S.InfobarH H-2E-NP')),
    ('SecondInfobarH06', _('S.InfobarH H-2E-2P')),
    ('SecondInfobarH07', _('S.InfobarH V-2E-NP')),
    ('SecondInfobarH08', _('S.InfobarH V-2E-2P')),
    ('SecondInfobarH09', _('S.InfobarH V-2E-2BD'))])
# SECONDINFOBAR Footer
config.plugins.xDreamy.SecondInfobarF = ConfigSelection(default='SecondInfobarF', choices=[
    ('SecondInfobarF', _('Default')),
    ('SecondInfobarF1', _('S.InfobarF F1')),
    ('SecondInfobarF2', _('S.InfobarF F2'))])

#============================== CHANNELS LIST ============================
# CHANNELS LIST
config.plugins.xDreamy.ChannSelector = ConfigSelection(default='C01-MTV-1P', choices=[
    ('C01-MTV-1P', _('Default')),
    ('C02-MTV-2P', _('C02-MTV-2P')),
    ('C03-MTV-7P', _('C03-MTV-7P')),
    ('C04-MTV-13P', _('C04-MTV-13P')),
    ('C05-MTV-NP', _('C05-MTV-NP')),
    ('C06-MTV-NP', _('C06-MTV-NP')),
    ('C07-MTV-1P', _('C07-MTV-1P')),
    ('C08-NP', _('C08-NP')),
    ('C09-NP', _('C09-NP')),
    ('C10-1P', _('C10-1P')),
    ('C11-2P', _('C11-2P')),
    ('C12-2P-NBG', _('C12-2P-NBG')),
    ('C13-7P', _('C13-7P')),
    ('C14-13P', _('C14-13P')),
    ('C15-14P', _('C15-14P'))])

# CHANNELS GRID
config.plugins.xDreamy.ChannSelectorGrid = ConfigSelection(default='G01-MTV-NP', choices=[
    ('G01-MTV-NP', _('G01-MTV-NP')),
    ('G02-1Raw-1P', _('G02-1Raw-1P')),
    ('G03-1Raw-2P', _('G03-1Raw-2P')),
    ('G04-1Raw-1P-Top', _('G04-1Raw-1P-Top')),
    ('G05-Color-2P', _('G05-Color-2P')),
    ('G06-Background-NP', _('G06-Background-NP')),
    ('G07-Transparent-NP', _('G07-Transparent-NP')),
    ('G08-Color-2P', _('G08-Color-2P')),
    ('G09-Backdrop', _('G09-Backdrop'))])

# OTHER SCREENS
config.plugins.xDreamy.EventView = ConfigSelection(default='EventView', choices=[
    ('EventView', _('Default')),
    ('EventView1', _('EventV-01 BD')),
    ('EventView2', _('EventV-02 Big')),
    ('EventView3', _('EventV-03 7P')),
    ('EventView4', _('EventV-04 11P-FSB')),
    ('EventView5', _('EventV-05 1P-FSB'))])

config.plugins.xDreamy.PluginBrowser = ConfigSelection(default='PluginBrowser', choices=[
    ('PluginBrowser', _('Default')),
    ('PluginBrowser1', _('PluginBrowser-01')),
    ('PluginBrowser2', _('PluginBrowser-02')),
    ('PluginBrowser3', _('PluginBrowser-03')),
    ('PluginBrowser4', _('PluginBrowser-04')),
    ('PluginBrowser4GHT', _('PluginBrowser-04 GHT')),
    ('PluginBrowser4GHM', _('PluginBrowser-04 GHM')),
    ('PluginBrowser4GHB', _('PluginBrowser-04 GHB')),
    ('PluginBrowser5GVL', _('PluginBrowser-05 GVL')),
    ('PluginBrowser5GVR', _('PluginBrowser-05 GVR'))])

config.plugins.xDreamy.VolumeBar = ConfigSelection(default='volume1', choices=[
    ('volume1', _('Default')),
    ('volume2', _('volume2')),
    ('volume3', _('volume3')),
    ('volume4', _('volume4')),
    ('volume5', _('volume5'))])

config.plugins.xDreamy.VirtualKeyboard = ConfigSelection(default='VirtualKeyBoard', choices=[
    ('VirtualKeyBoard', _('Default')),
    ('VirtualKeyBoard1', _('Black - Keyboard')),
    ('VirtualKeyBoard2', _('Color - Keyboard'))])
    
config.plugins.xDreamy.NewVirtualKeyboard = ConfigSelection(default='NewVirtualKeyBoard0', choices=[
    ('NewVirtualKeyBoard0', _('Default')),
    ('NewVirtualKeyBoard1', _('NV.KeyBoard1')),
    ('NewVirtualKeyBoard2', _('NV.KeyBoard2')),
    ('NewVirtualKeyBoard3', _('NV.KeyBoard3')),
    ('NewVirtualKeyBoard4', _('NV.KeyBoard4'))])

config.plugins.xDreamy.HistoryZapSelector = ConfigSelection(default='HistoryZapSelector0', choices=[
    ('HistoryZapSelector0', _('Default')),
    ('HistoryZapSelector1', _('HistoryZap1-NP')),
    ('HistoryZapSelector2', _('HistoryZap2-NP')),
    ('HistoryZapSelector3', _('HistoryZap3-NP'))])

config.plugins.xDreamy.EPGMultiSelection = ConfigSelection(default='EPGMultiSelection', choices=[
    ('EPGMultiSelection', _('Default')),
    ('EPGMultiSelection1', _('EPGMultiSelection1'))])

config.plugins.xDreamy.E2Player = ConfigSelection(default='E2Player', choices=[
    ('E2Player', _('Default')),
    ('E2Player1', _('E2Player1')),
    ('E2Player2', _('E2Player2'))])

config.plugins.xDreamy.EnhancedMovieCenter = ConfigSelection(default='EnhancedMovieCenter', choices=[
    ('EnhancedMovieCenter', _('Default')),
    ('EnhancedMovieCenter1', _('E.MovieCenter1')),
    ('EnhancedMovieCenter2', _('E.MovieCenter2')),
    ('EnhancedMovieCenter3', _('E.MovieCenter3'))])

config.plugins.xDreamy.ChannelListBackground = ConfigSelection(default='Black', choices=[
    ('Black', _('Default- Black')),
    ('Color', _('Skin Color')),
    ('Background', _('Background')),
    ('Background1', _('Background1')),
    ('Background2', _('Background2')),
    ('Background3', _('Background3')),
    ('Background4', _('Background4')),
    ('Background5', _('Background5')),
    ('Background6', _('Background6')),
    ('Background7', _('Background7')),
    ('Background8', _('Background8')),
    ('Background9', _('Background9')),
    ('Background10', _('Background10')),
    ('Background11', _('Background11')),
    ('Background12', _('Background12')),
    ('Background13', _('Background13')),
    ('Background14', _('Background14')),
    ('Background15', _('Background15')),
    ('Background16', _('Background16'))])

config.plugins.xDreamy.TurnOff = ConfigSelection(default='Background', choices=[
    ('Background', _('Background')),
    ('Background1', _('Background1')),
    ('Background2', _('Background2')),
    ('Background3', _('Background3')),
    ('Background4', _('Background4')),
    ('Background5', _('Background5')),
    ('Background6', _('Background6')),
    ('Background7', _('Background7')),
    ('Background8', _('Background8')),
    ('Background9', _('Background9')),
    ('Background10', _('Background10')),
    ('Background11', _('Background11')),
    ('Background12', _('Background12')),
    ('Background13', _('Background13')),
    ('Background14', _('Background14')),
    ('Background15', _('Background15')),
    ('Background16', _('Background16'))])

config.plugins.xDreamy.WeatherSource = ConfigSelection(default='OAWeatherPlugin', choices=[
    ('OAWeatherPlugin', _('Default-OAWeatherPlugin')),
    ('MSNWeatherPlugin', _('MSNWeatherPlugin'))])

config.plugins.xDreamy.BitrateSource = ConfigSelection(default='BitrateRenderer', choices=[
    ('BitrateRenderer', _('Default-BitrateRenderer')),
    ('BitratePlugin', _('Bitrate Plugin'))])

config.plugins.xDreamy.SubtitlesClock = ConfigSelection(default='SC', choices=[
    ('SC', _('Default- No Clock')),
    ('SC1', _('DSC-Bottom Right')),
    ('SC2', _('DSC-Bottom Left')),
    ('SC3', _('DSC-Top Right')),
    ('SC4', _('DSC-Top Left'))])

config.plugins.xDreamy.RatingStars = ConfigSelection(default='NRS', choices=[
    ('NRS', _('Default-Disable')),
    ('RS', _('Enable'))])

config.plugins.xDreamy.CamName = ConfigSelection(default='Access', choices=[
    ('Access', _('Default')),
    ('CaidInfo2', _('CaidInfo')),
    ('CamdRAED', _('CamdRAED')),
    ('CryptoInfo', _('CryptoInfo')),
    ('EcmInfo', _('EcmInfo'))])

config.plugins.xDreamy.channelnamecolor = ConfigSelection(default="CLC", choices=[
    ("CLC", _("White - White")),
    ("CLC1", _("White - Color")),
    ("CLC2", _("Color - White")),
    ("CLC3", _("Color - Color"))])

config.plugins.xDreamy.menufontcolor = ConfigSelection(default='MC', choices=[
    ('MC', _('Default- White')),
    ('MC1', _('Skin Color'))])

config.plugins.xDreamy.crypt = ConfigSelection(default='Cryptoname', choices=[
    ('Cryptoname', _('Default-Name')),
    ('Cryptobar', _('Crypt-Bar'))])

config.plugins.xDreamy.posterRemovalInterval = ConfigSelection(default="31536000", choices=[
    ("86400", _("1 Day")),               # 1 day = 86400 seconds
    ("432000", _("5 Days")),             # 5 days = 432000 seconds
    ("864000", _("10 Days")),            # 10 days = 864000 seconds
    ("1296000", _("15 Days")),           # 15 days = 1296000 seconds
    ("2592000", _("30 Days")),           # 30 days = 2592000 seconds
    ("5184000", _("2 Months")),          # 2 months = 60 days = 5184000 seconds
    ("10368000", _("4 Months")),         # 4 months = 120 days = 10368000 seconds
    ("15552000", _("6 Months")),         # 6 months = 180 days = 15552000 seconds
    ("31536000", _("12 Months")),        # 12 months = 365 days = 31536000 seconds
    ("63072000", _("2 Years")),          # 2 years = 730 days = 63072000 seconds
])

config.plugins.xDreamy.posters= ConfigSelection(default='iPosterX', choices=[
    ('iPosterX', _('Default'))])
#    ('xtraEvent', _('xtraEvent'))])

def applyDateFormat():
    skinFiles = [
        "/usr/share/enigma2/xDreamy/sample/head-head.xml",
        "/usr/share/enigma2/xDreamy/skin.xml"
    ]

    new_format = config.plugins.xDreamy.dateFormat.value
    changes_made = False  

    for skinFile in skinFiles:
        try:
            if not os.path.exists(skinFile):
                logger.warning(_("Skin file not found: {skinFile}").format(skinFile=skinFile))
                continue  

            with open(skinFile, "r") as file:
                skin_data = file.read()

            logger.debug(_("Checking file: {skinFile}").format(skinFile=skinFile))  

            # ✅ Define the start and end of the <convert>` tag
            start_tag = '<convert type="ClockToText">Format '
            end_tag = '</convert>'

            # ✅ Find the position of the start and end tags
            start_index = skin_data.find(start_tag)
            end_index = skin_data.find(end_tag, start_index) if start_index != -1 else -1

            if start_index != -1 and end_index != -1:
                # ✅ Extract the old `<convert>` tag (including the old format)
                old_convert_tag = skin_data[start_index:end_index + len(end_tag)]

                # ✅ Create the new `<convert>` tag with the new format
                new_convert_tag = f'{start_tag}{new_format}{end_tag}'

                # ✅ Replace the old tag with the new one
                updated_skin_data = skin_data.replace(old_convert_tag, new_convert_tag)

                if updated_skin_data != skin_data:
                    try:
                        with open(skinFile, "w") as file:
                            file.write(updated_skin_data)
                        logger.info(_("Updated date format to: {new_format} in {skinFile}").format(new_format=new_format, skinFile=skinFile))
                        changes_made = True  
                    except IOError as e:
                        logger.error(_("Failed to write to {skinFile}: {error}").format(skinFile=skinFile, error=e))
            else:
                logger.warning(_("No <convert> tag found in {skinFile}!").format(skinFile=skinFile))

        except Exception as e:
            logger.error(_("Error updating {skinFile}: {error}").format(skinFile=skinFile, error=e))

    if changes_made:
        logger.info(_("Date format updated in skin templates. Restart Enigma2 manually if needed."))
    else:
        logger.warning(_("No changes detected in skin templates."))

# ✅ Ensure function runs when setting is changed
config.plugins.xDreamy.dateFormat.addNotifier(lambda _: applyDateFormat())

########################################################## COLORS CODE CHANGE ##########################################################
def apply_template(template_name):
    """Apply a template by updating the predefined three color values in C-default-color.xml."""
    if template_name in TEMPLATES:
        ltbluette_value, bluette_value, header_value = TEMPLATES[template_name]

        # Get transparency value from config
        transparency_value = config.plugins.xDreamy.transparency.value  # e.g., "25"

        # Ensure header_value starts with "#" and is 9 characters long
        if header_value.startswith("#") and len(header_value) == 9:
            header_value = f"#{transparency_value}{header_value[3:]}"  # Apply transparency

        update_colors_in_file(
            '/usr/share/enigma2/xDreamy/sample/C-default-color.xml',
            ltbluette_value, None, bluette_value, header_value
        )
        logger.info(_("Template '{template_name}' applied to C-default-color.xml with transparency {transparency_value}.").format(template_name=template_name, transparency_value=transparency_value))
    else:
        logger.warning(_("Template '{template_name}' not found.").format(template_name=template_name))

def update_individual_colors(ltbluette_value=None, white_value=None, bluette_value=None, header_value=None):
    """Update one or more individual colors in C-color23_Custom.xml."""
    update_colors_in_file(
        '/usr/share/enigma2/xDreamy/sample/C-color23_Custom.xml',
        ltbluette_value, white_value, bluette_value, header_value
    )
    logger.info(_("Selected colors updated in C-color23_Custom.xml."))

def update_colors_in_file(file_path, ltbluette_value=None, white_value=None, bluette_value=None, header_value=None):
    try:
        updated_lines = []
        color_updated = {"ltbluette": False, "white": False, "bluette": False, "header": False}

        # Read the current file
        with open(file_path, 'r') as file:
            lines = file.readlines()

        # Get transparency value from config
        transparency_value = config.plugins.xDreamy.transparency.value  # e.g., "25"

        # Process each line and update colors
        for line in lines:
            if '<color name="ltbluette"' in line and ltbluette_value is not None:
                line = f'<color name="ltbluette" value="{ltbluette_value}"/>\n'
                color_updated["ltbluette"] = True
            elif '<color name="white"' in line and white_value is not None:
                line = f'<color name="white" value="{white_value}"/>\n'
                color_updated["white"] = True
            elif '<color name="bluette"' in line and bluette_value is not None:
                line = f'<color name="bluette" value="{bluette_value}"/>\n'
                color_updated["bluette"] = True
            elif '<color name="header"' in line and header_value is not None:
                # Ensure header_value starts with "#" and is 9 characters long
                if header_value.startswith("#") and len(header_value) == 9:
                    # Apply transparency by replacing the first two digits after "#"
                    new_color = f"#{transparency_value}{header_value[3:]}"
                    line = f'<color name="header" value="{new_color}"/>\n'
                    color_updated["header"] = True

            updated_lines.append(line)  # Add the processed line to the list

        # Write the updated lines back to the file (overwrite mode)
        with open(file_path, 'w') as file:
            file.writelines(updated_lines)

        os.system("sync")  # Ensure changes are saved
        logger.info(_("Colors updated in {file_path}, Header: {header_value} -> {new_color}").format(file_path=file_path, header_value=header_value, new_color=new_color))

    except Exception as e:
        logger.error(_("Error updating colors in {file_path}: {error}").format(file_path=file_path, error=e))


########################################################## FONTS NAME & SIZE CHANGE ##########################################################
def update_font_settings(font_name=None, font_scale=None):
    font_file_path = '/usr/share/enigma2/xDreamy/sample/font-basic.xml'
    try:
        with open(font_file_path, 'r') as file:
            lines = file.readlines()
        
        with open(font_file_path, 'w') as file:
            for line in lines:
                if '<font name="Regular"' in line:
                    line = f'<font name="Regular" filename="/usr/share/enigma2/xDreamy/fonts/{font_name}" scale="{font_scale}" />\n'
                file.write(line)
        
        os.system("sync")  # Save changes
        logger.info(_("Font settings updated: {font_name}, scale={font_scale}").format(font_name=font_name, font_scale=font_scale))
    except Exception as e:
        logger.error(_("Error updating font settings: {error}").format(error=e))

########################################################## iPOSTERX CHANGE ##########################################################
# Update the renderer logic
import os
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Configuration
FILES_TO_UPDATE = [
    '/usr/lib/enigma2/python/Components/Renderer/iPosterX.py',
    '/usr/lib/enigma2/python/Components/Renderer/iPosterXDownloadThread.py',
    '/usr/lib/enigma2/python/Components/Renderer/iBackdropX.py',
    '/usr/lib/enigma2/python/Components/Renderer/iBackdropXDownloadThread.py',
    # Add more files here as needed
]

def replace_class_names(file_path, enable):
    """Replace class names in a file to enable or disable the renderer."""
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()

        with open(file_path, 'w') as file:
            for line in lines:
                # Check if the line contains a class definition starting with "i"
                if line.strip().startswith("class i"):
                    if enable:
                        # Enable: Replace "OFF_" with "i"
                        line = line.replace("OFF_", "i")
                    else:
                        # Disable: Replace "i" with "OFF_"
                        line = line.replace("class i", "class OFF_")
                file.write(line)

        logger.info(_("Updated class names in {file_path} (enable={enable})").format(file_path=file_path, enable=enable))
    except Exception as e:
        logger.error(_("Error updating class names in {file_path}: {error}").format(file_path=file_path, error=e))

def update_renderer_status(enable, files_to_update=None):
    """
    Enable or disable a renderer by updating class names in the specified files.
    
    :param enable: Boolean, True to enable the renderer, False to disable it.
    :param files_to_update: List of file paths to update. If None, defaults to PosterX files.
    """
    if files_to_update is None:
        # Default to PosterX files if no specific files are provided
        files_to_update = [
            '/usr/lib/enigma2/python/Components/Renderer/iPosterX.py',
            '/usr/lib/enigma2/python/Components/Renderer/iPosterXDownloadThread.py',
            '/usr/lib/enigma2/python/Components/Renderer/iBackdropX.py',
            '/usr/lib/enigma2/python/Components/Renderer/iBackdropXDownloadThread.py',
        ]

    try:
        for file_path in files_to_update:
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    lines = file.readlines()

                with open(file_path, 'w') as file:
                    for line in lines:
                        # Enable: Replace "OFF_" with "i"
                        if enable:
                            line = line.replace("OFF_", "i")
                        # Disable: Replace "i" with "OFF_"
                        else:
                            line = line.replace("class i", "class OFF_")
                        file.write(line)

                logger.info(_("Updated {file_path} to {'enable' if enable else 'disable'} renderer.").format(file_path=file_path))
            else:
                logger.warning(_("File not found: {file_path}").format(file_path=file_path))

        os.system("sync")  # Ensure changes are saved
        logger.info(_("Renderer {'enabled' if enable else 'disabled'} successfully."))
    except Exception as e:
        logger.error(_("Error updating renderer status: {error}").format(error=e))

# Notifier for PosterX
config.plugins.xDreamy.enablePosterX.addNotifier(lambda config: update_renderer_status(config.value))

def update_removal_time(removal_time):
    """Update the auto-removal interval for posters."""
    try:
        posterx_file_path = '/usr/lib/enigma2/python/Components/Renderer/iPosterX.py'
        with open(posterx_file_path, 'r') as file:
            lines = file.readlines()

        with open(posterx_file_path, 'w') as file:
            for line in lines:
                if 'elif diff_tm > 31536000:' in line:
                    # Preserve the indentation of the original line
                    indentation = line[:line.find('elif')]  # Get the leading spaces/tabs
                    line = f"{indentation}elif diff_tm > {removal_time}:\n"
                file.write(line)

        os.system("sync")  # Ensure changes are saved
        logger.info(_("Poster removal time updated to: {removal_time} seconds").format(removal_time=removal_time))
    except Exception as e:
        logger.error(_("Error updating poster removal time: {error}").format(error=e))

config.plugins.xDreamy.posterRemovalInterval.addNotifier(lambda config: update_removal_time(config.value))

def autostart(reason, **kwargs):
    if reason == 0:  # Only run on startup
        if cur_skin == 'xDreamy':
            if config.plugins.xDreamy.bootlogos.value is True:
                if not fileExists(mvi + 'bootlogoBack.mvi'):
                    shutil.copy(mvi + 'bootlogo.mvi', mvi + 'bootlogoBack.mvi')
                if fileExists(logopath + 'bootlogo.mvi'):
                    os.remove(logopath + 'bootlogo.mvi')
                if fileExists(logopath + 'backdrop.mvi'):
                    os.remove(logopath + 'backdrop.mvi')
                if fileExists(logopath + 'bootlogo_wait.mvi'):
                    os.remove(logopath + 'bootlogo_wait.mvi')

                if fileExists(bootlog + 'bootlogo1.mvi'):
                    newscreen = random.choice(os.listdir(bootlog))
                    final = bootlog + newscreen
                    shutil.copy(final, mvi + 'bootlogo.mvi')
                    shutil.copy(final, mvi + 'backdrop.mvi')
        else:
            if fileExists(mvi + 'bootlogoBack.mvi'):
                shutil.copy(mvi + 'bootlogoBack.mvi', mvi + 'bootlogo.mvi')
                os.remove(mvi + 'bootlogoBack.mvi')

# ✅ Ensure function runs after Enigma2 boots
def onEnigmaStart(reason, **kwargs):
    if reason == 0:  # Runs only on full Enigma2 startup (not standby mode)
        logger.info(_("Enigma2 Startup Detected - Applying Date Format Changes"))
        applyDateFormat()

def Plugins(**kwargs):
    pluginList = [
        PluginDescriptor(
            name=_("XDREAMY"),
            description=_('Customization tool for XDREAMY Skin'),
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon='plugin.png',
            fnc=main
        ),
        PluginDescriptor(
            name=_("XDREAMY BOOT"),
            description=_("XDREAMY BOOT LOGO"),
            where=PluginDescriptor.WHERE_AUTOSTART,
            fnc=autostart
        )
    ]
    
    # تحقق مما إذا كان يجب عرض الإضافة في قائمة الامتدادات
    if config.plugins.xDreamy.ShowInExtensions.value:
        pluginList.append(
            PluginDescriptor(
                name=_("XDREAMY Skin Settings"),
                description=_("Customization tool for XDREAMY Skin"),
                where=[PluginDescriptor.WHERE_EXTENSIONSMENU],
                fnc=main
            )
        )
    
    return pluginList

#====================================================================

def switch_poster_render():
    """Switch between iPosterX and xtraEvent in XML skin files."""
    base_path = "/usr/share/enigma2/xDreamy/sample/"
    target_files = [f for f in os.listdir(base_path) if f.startswith(("infobar-", "secondinfobar-", "CHL-", "CHLG-"))]

    # Get user config selection
    selected_render = config.plugins.xDreamy.posters.value  # 'iPosterX' or 'xtraEvent'

    # Define the replacement mappings
    replacements = {
        'iPosterX': 'xtraPoster',
        'iBackdropX': 'xtraBackdrop'
    } if selected_render == 'xtraEvent' else {
        'xtraPoster': 'iPosterX',
        'xtraBackdrop': 'iBackdropX'
    }

    for filename in target_files:
        file_path = os.path.join(base_path, filename)

        try:
            with open(file_path, 'r') as file:
                content = file.read()

            # Replace occurrences
            for old, new in replacements.items():
                content = content.replace(old, new)

            # Write back the updated content
            with open(file_path, 'w') as file:
                file.write(content)

            logger.info(_("Updated poster rendering in {filename} ({selected_render})").format(filename=filename, selected_render=selected_render))

        except Exception as e:
            logger.error(_("Error processing {filename}: {error}").format(filename=filename, error=e))
#====================================================================
def main(session, **kwargs):
    session.open(xDreamySetup)

def remove_exif(image_path):
    with Image.open(image_path) as img:
        img.save(image_path, "PNG")

def convert_image(image):
    path = image
    img = Image.open(path)
    img.save(path, "PNG")
    return image
    

class xDreamySetup(ConfigListScreen, Screen):
    skin = '''
                                    <screen name="xDreamySetup" position="center,center" size="1000,640" title="XDREAMY skin customization plugin">
                                        <eLabel font="Regular; 24" foregroundColor="#00ff4A3C" halign="center" position="20,598" size="120,26" text="Cancel"/>
                                        <eLabel font="Regular; 24" foregroundColor="#0056C856" halign="center" position="220,598" size="120,26" text="Save"/>
                                        <widget name="Preview" position="997,690" size="498, 280" zPosition="1"/>
                                        <widget name="config" font="Regular; 24" itemHeight="40" position="5,5" scrollbarMode="showOnDemand" size="990,550"/>
                                        <widget name="city" font="Regular; 26" position="564,571" size="420,60" foregroundColor="#00ff4A3C" backgroundColor="#000000" transparent="1" zPosition="4" halign="center" valign="bottom"/>
                                        <widget name="helpText" font="Regular; 22" position="5,560" size="990,30" foregroundColor="#00ffffff" backgroundColor="#000000" transparent="1" zPosition="2" halign="left" valign="center"/>
                                    </screen>
           '''

    def __init__(self, session):
        self.version = '.xDreamy'
        Screen.__init__(self, session)
        self.session = session
        self.skinFile = '/usr/share/enigma2/xDreamy/skin.xml'
        self.previewFiles = '/usr/share/enigma2/xDreamy/sample/'
        self['Preview'] = Pixmap()
        self['city'] = Label('')
        self['helpText'] = Label('')  # Initialize the helpText label
        self['yellow'] = Label(_('Check for Update'))  # Add translation for yellow key
        self['blue'] = Label(_('Version'))  # Add translation for blue key
        self.setup_title = f"XDREAMY SKIN v {version}"
        self.activeComponents = []  # Initialize activeComponents attribute
        list = []
        ConfigListScreen.__init__(self, list, session=self.session, on_change=self.changedEntry)
        self.onChangedEntry = []
        self.editListEntry = None
        self.createSetup()  # ✅ تأكد أن `createSetup` يتم استدعاؤها أولًا
        self.onLayoutFinish.append(self.createSetup)
        self.onLayoutFinish.append(self.ShowPicture)
        self["actions"] = ActionMap(["SetupActions"], {
            'ok': self.keyOK,
            "cancel": self.keyCancel,
            "save": self.keySave,
        }, -2)
        self['actions'] = ActionMap(['OkCancelActions',
                                     'DirectionActions',
                                     'InputActions',
                                     'VirtualKeyboardActions',
                                     'MenuActions',
                                     'NumberActions',
                                     'InfoActions',
                                     'ColorActions'], {'showVirtualKeyboard': self.KeyText,
                                                       'left': self.keyLeft,
                                                       'right': self.keyRight,
                                                       'down': self.keyDown,
                                                       'up': self.keyUp,
                                                       'red': self.keyExit,
                                                       'green': self.keySave,
                                                       'yellow': self.checkforUpdate,
                                                       'blue': self.info,
                                                       'cancel': self.keyExit,
                                                       'ok': self.keyRun}, -1)

        self.timerx = eTimer()
        if fileExists('/var/lib/dpkg/status'):
            self.timerx_conn = self.timerx.timeout.connect(self.checkforUpdate)
        else:
            self.timerx.callback.append(self.checkforUpdate)
        self.timerx.start(5000, True)
        self.onLayoutFinish.append(self.ShowPicture)
        self.onLayoutFinish.append(self.__layoutFinished)

        # Add notifier to InfobarStyle to update the list when the selection changes
        config.plugins.xDreamy.InfobarStyle.addNotifier(self.onInfobarStyleChange)

        # Call this function during initialization
        update_plugin_install_status()


    def __layoutFinished(self):
        self['city'].setText("%s" % str(config.plugins.xDreamy.city.value))
        self.setTitle(self.setup_title)
        
    def updateHelpText(self):
        current = self["config"].getCurrent()
        if current:
            self['helpText'].setText(current[2] if len(current) > 2 else '')

    def mesInfo(self):
        message = _(
            "Experience Enigma2 skin like never before with XDREAMY\n\n"
            "XDREAMY skin is a new vision, created by Inspiron.\n"
            "Users can fully customize their interface, and change layout,\n"
            "colors, fonts, and screens to suit their preferences.\n"
            "Drawing inspiration from Dreamy and oDreamy skins,\n"
            "XDREAMY incorporates cutting-edge rendering technology,\n"
            "including the efficient PosterX component recoded by M.Hussein using AI.\n\n"
            "Supported Images\n"
            "-----------------\n"
            "Egami, OpenATV, OpenSpa, PurE2, OpenDroid, OpenBH & Alliance Based Images.\n"
            "OpenPLi, OpenVIX, OpenHDF, OpenTR, Satlodge, NonSoloSat, Foxbob & PLi Base Images.\n\n"
            "Forum support: Linuxsat-support.com\n"
            "Mahmoud Hussein"
        )
        self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

    def getImagePath(self, item_name):
        base_dir = "/usr/share/enigma2/xDreamy/screens/"
        item_name = item_name.lower().replace(" ", "").replace("-", "")
        return os.path.join(base_dir, f"{item_name}.png")

    def openSelectionPopup(self, current):
        sel = current[1]

        # ✅ Ensure the setting has valid choices
        if hasattr(sel, "choices"):
            options = [(str(opt), opt) for opt in sel.choices]  # Handle both list and dict
        else:
            logger.warning(_("No choices available for {current}").format(current=current[0]))
            return

        # ✅ Open popup with available choices
        self.session.openWithCallback(
            lambda choice: self.selectionMade(choice, sel),
            ChoiceBox,
            title=_("Select an option for: ") + current[0],
            list=options
        )

    def selectionMade(self, choice, configItem):
        if choice:
            configItem.value = choice[1]  # ✅ Apply the selected option
            self.createSetup()  # ✅ Refresh UI


    def keyRun(self):
        current = self["config"].getCurrent()
        if current and len(current) > 1:
            sel = current[1]
            if sel == config.plugins.xDreamy.png:
                config.plugins.xDreamy.png.setValue(0)
                config.plugins.xDreamy.png.save()
                self.removPng()
            elif sel == config.plugins.xDreamy.weather:
                self.KeyMenu()
            elif sel == config.plugins.xDreamy.oaweather:
                self.KeyMenu2()
            elif sel == config.plugins.xDreamy.city:
                self.KeyText()
            elif sel == config.plugins.xDreamy.api:
                self.keyApi()
            elif sel == config.plugins.xDreamy.txtapi:
                self.KeyText()
            elif sel == config.plugins.xDreamy.api2:
                self.keyApi2()
            elif sel == config.plugins.xDreamy.txtapi2:
                self.KeyText()
            elif sel == config.plugins.xDreamy.api3:
                self.keyApi3()
            elif sel == config.plugins.xDreamy.txtapi3:
                self.KeyText()
            elif sel == config.plugins.xDreamy.api4:
                self.keyApi4()
            elif sel == config.plugins.xDreamy.txtapi4:
                self.KeyText()
            # ✅ Open Popup for ConfigSelection Settings
            elif isinstance(sel, ConfigSelection):
                self.openSelectionPopup(current)  # ✅ Show popup with available options

            elif sel == config.plugins.xDreamy.install_ajpanel:
                self.installPlugin("AJPanel", "https://raw.githubusercontent.com/AMAJamry/AJPanel/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_linuxsatpanel:
                self.installPlugin("LinuxsatPanel", "https://raw.githubusercontent.com/Belfagor2005/LinuxsatPanel/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_CiefpPlugins:
                self.installPlugin("CiefpPlugins", "https://raw.githubusercontent.com/ciefp/CiefpPlugins/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_smartpanel:
                self.installPlugin("SmartPanel", "https://raw.githubusercontent.com/emilnabil/download-plugins/refs/heads/main/SmartAddonspanel/smart-Panel.sh")
            elif sel == config.plugins.xDreamy.install_elisatpanel:
                self.installPlugin("EliSatPanel", "https://raw.githubusercontent.com/eliesat/eliesatpanel/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_magicpanel:
                self.installPlugin("MagicPanel", "https://gitlab.com/h-ahmed/Panel/-/raw/main/MagicPanel-install.sh")
            elif sel == config.plugins.xDreamy.install_msnweather:
                self.installPlugin("MSNWeather", "https://raw.githubusercontent.com/fairbird/WeatherPlugin/master/installer.sh")
            elif sel == config.plugins.xDreamy.install_oaweather:
                self.installPlugin("OAWeather", "https://gitlab.com/hmeng80/extensions/-/raw/main/oaweather/oaweather.sh")
            elif sel == config.plugins.xDreamy.install_multicammanager:
                self.installPlugin("MultiCamManager", "https://raw.githubusercontent.com/levi-45/Manager/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_NCam:
                self.installPlugin("NCam", "https://raw.githubusercontent.com/biko-73/Ncam_EMU/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_keyadder:
                self.installPlugin("KeyAdder", "https://raw.githubusercontent.com/fairbird/KeyAdder/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_xklass:
                self.installPlugin("XKlass", "https://gitlab.com/MOHAMED_OS/dz_store/-/raw/main/XKlass/online-setup")
            elif sel == config.plugins.xDreamy.install_youtube:
                self.installPlugin("YouTube", "https://raw.githubusercontent.com/fairbird/Youtube-Opensource-DreamOS/master/installer.sh")
            elif sel == config.plugins.xDreamy.install_e2iplayer:
                self.installPlugin("E2iPlayer", "https://gitlab.com/eliesat/extensions/-/raw/main/e2iplayer/e2iplayer-main.sh")
            elif sel == config.plugins.xDreamy.install_transmission:
                self.installPlugin("Transmission", "http://dreambox4u.com/dreamarabia/Transmission_e2/Transmission_e2.sh")
            elif sel == config.plugins.xDreamy.install_multistalkerpro:
                self.installPlugin("MutliStalkerPro", "https://raw.githubusercontent.com/biko-73/Multi-Stalker/main/pro/installer.sh")
            elif sel == config.plugins.xDreamy.install_ipaudiopro:
                self.installPlugin("IPAudioPro", "https://raw.githubusercontent.com/biko-73/ipaudio/main/ipaudio_pro.sh")
            elif sel == config.plugins.xDreamy.install_EPGGrabber:
                self.installPlugin("EPGGrabber", "https://raw.githubusercontent.com/ziko-ZR1/Epg-plugin/master/Download/installer.sh")
            elif sel == config.plugins.xDreamy.install_subssupport:
                self.installPlugin("SubsSupport", "https://github.com/popking159/ssupport/raw/main/subssupport-install.sh")
            elif sel == config.plugins.xDreamy.install_historyzapselector:
                self.installPlugin("HistoryZapSelector", "https://raw.githubusercontent.com/biko-73/History_Zap_Selector/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_newvirtualkeyboard:
                self.installPlugin("NewVirtualKeyBoard", "https://raw.githubusercontent.com/fairbird/NewVirtualKeyBoard/main/installer.sh")
            elif sel == config.plugins.xDreamy.install_raedquicksignal:
                self.installPlugin("RaedQuickSignal", "https://raw.githubusercontent.com/fairbird/RaedQuickSignal/main/installer.sh")

    def installPlugin(self, plugin_name, url):
        if check_plugin_installed(plugin_name):
            self.session.openWithCallback(lambda result: self.runInstallation(result, plugin_name, url), MessageBox, 
                                          _("{plugin_name} is already installed. Do you want to open, reinstall, remove, or cancel?").format(plugin_name=plugin_name), 
                                          MessageBox.TYPE_YESNO, default=False, simple=True, list=[("Open", "open"), ("Reinstall", "reinstall"), ("Remove", "remove"), ("Cancel", "cancel")])
        else:
            self.session.openWithCallback(lambda result: self.runInstallation(result, plugin_name, url), MessageBox, 
                                          _("{plugin_name} is not installed. Do you want to install it now?").format(plugin_name=plugin_name), 
                                          MessageBox.TYPE_YESNO)

    def runInstallation(self, result, plugin_name, url):
        if result == "open":
            self.session.open(MessageBox, _("Opening {plugin_name}...").format(plugin_name=plugin_name), MessageBox.TYPE_INFO, timeout=4)
            # Logic to open the plugin
        elif result == "reinstall" or result == True:
            command = f"wget -q --no-check-certificate {url} -O - | /bin/sh"
            self.session.open(Console, _('Installing Plugin'), [command], closeOnSuccess=False)
        elif result == "remove":
            command = f"opkg remove enigma2-plugin-extensions-{plugin_name.lower()}"
            self.session.open(Console, _('Removing Plugin'), [command], closeOnSuccess=False)
        else:
            self.session.open(MessageBox, _("Operation cancelled."), MessageBox.TYPE_INFO, timeout=4)

    def keyApi(self, answer=None):
        api = "/tmp/apikey.txt"
        if answer is None:
            if fileExists(api) and os.stat(api).st_size > 0:
                self.session.openWithCallback(self.keyApi, MessageBox, _("Import Api Key TMDB from /tmp/apikey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing {api} !").format(api=api)), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api) and os.stat(api).st_size > 0:
                with open(api, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(tmdb_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi.setValue(fpage)
                    config.plugins.xDreamy.api.setValue(True)
                    config.plugins.xDreamy.txtapi.save()
                    self.session.open(MessageBox, _("TMDB ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("TMDB ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing {api} !").format(api=api)), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def keyApi2(self, answer=None):
        api2 = "/tmp/omdbkey.txt"
        if answer is None:
            if fileExists(api2) and os.stat(api2).st_size > 0:
                self.session.openWithCallback(self.keyApi2, MessageBox, _("Import Api Key OMDB from /tmp/omdbkey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing {api2} !").format(api2=api2)), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api2) and os.stat(api2).st_size > 0:
                with open(api2, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(omdb_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi2.setValue(fpage)
                    config.plugins.xDreamy.api2.setValue(True)
                    config.plugins.xDreamy.txtapi2.save()
                    self.session.open(MessageBox, _("OMDB ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("OMDB ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing {api2} !").format(api2=api2)), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def keyApi3(self, answer=None):
        api3 = "/tmp/thetvdbkey.txt"
        if answer is None:
            if fileExists(api3) and os.stat(api3).st_size > 0:
                self.session.openWithCallback(self.keyApi3, MessageBox, _("Import Api Key TheTVDB from /tmp/thetvdbkey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing {api3} !").format(api3=api3)), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api3) and os.stat(api3).st_size > 0:
                with open(api3, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(thetvdb_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi3.setValue(fpage)
                    config.plugins.xDreamy.api3.setValue(True)
                    config.plugins.xDreamy.txtapi3.save()
                    self.session.open(MessageBox, _("TheTVDB ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("TheTVDB ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing {api3} !").format(api3=api3)), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def keyApi4(self, answer=None):
        api4 = "/tmp/fanartkey.txt"
        if answer is None:
            if fileExists(api4) and os.stat(api4).st_size > 0:
                self.session.openWithCallback(self.keyApi4, MessageBox, _("Import Api Key Fanart from /tmp/fanartkey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing {api4} !").format(api4=api4)), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api4) and os.stat(api4).st_size > 0:
                with open(api4, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(fanart_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi4.setValue(fpage)
                    config.plugins.xDreamy.api4.setValue(True)
                    config.plugins.xDreamy.txtapi4.save()
                    self.session.open(MessageBox, _("Fanart ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("Fanart ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing {api4} !").format(api4=api4)), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def KeyText(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        sel = self["config"].getCurrent()
        if sel and len(sel) > 1:
            self.session.openWithCallback(self.VirtualKeyBoardCallback, VirtualKeyBoard, title=sel[0], text=sel[1].value)

    def VirtualKeyBoardCallback(self, callback=None):
        if callback is not None and len(callback):
            self["config"].getCurrent()[1].value = callback
            self["config"].invalidate(self["config"].getCurrent())
        return

    def createSetup(self):
        try:
            self.editListEntry = None                                     
            list = []
            section = '\\c00289496' + _('SKIN GENERAL SETUP  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Skin Style:'), config.plugins.xDreamy.skinTemplate, _('Choose the overall visual theme for your interface. This affects layouts, and graphical elements.')))
            list.append(getConfigListEntry(_('Keys Style:'), config.plugins.xDreamy.KeysStyle, _('Select the design style for on-screen buttons and key prompts. Different styles offer varying visual effects.')))
            list.append(getConfigListEntry(_('Font Style:'), config.plugins.xDreamy.FontStyle, _('Set the default font scheme. Choose "Basic" for standard fonts or "Custom" for advanced font control for font style and size.')))
            if config.plugins.xDreamy.FontStyle.value == 'basic':
                list.append(getConfigListEntry(_('      - Font Type:'), config.plugins.xDreamy.FontName, _('Select your preferred font family. Verdana is the default for optimal readability on TV screens.')))
                list.append(getConfigListEntry(_('      - Font Size:'), config.plugins.xDreamy.FontScale, _('Adjust text size in 5 percent increments. 100 percent is standard size. Increase for better visibility or decrease for more screen space.')))
            list.append(getConfigListEntry(_("Date Format:"), config.plugins.xDreamy.dateFormat, _("Customize how dates are displayed. Options include different orderings of day/month/year and various separators.")))
            list.append(getConfigListEntry(_("Clock Format:"), config.plugins.xDreamy.clockFormat, _("Select between 12-hour (AM/PM) or 24-hour time format for all clock displays in the interface.")))
            list.append(getConfigListEntry(_('Show in Extensions:'), config.plugins.xDreamy.ShowInExtensions, _('Toggle visibility of xDreamy in the Extensions menu. Set to "No" to hide the plugin from the Extensions menu.')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('SKIN GENERAL COLORS  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Skin General Color:'), config.plugins.xDreamy.colorSelector, _('Select color scheme for the skin, Choose "Default" in order to select one of the color templates or "Custom" to select your own colors from 4 variable.')))
            if config.plugins.xDreamy.colorSelector.value == 'default-color':
                list.append(getConfigListEntry(_('      - Color Templates:'), config.plugins.xDreamy.BasicColorTemplates, _('Select a predefined color template for the skin.')))
                list.append(getConfigListEntry(_('      - Background Transparency:'), config.plugins.xDreamy.transparency, _('Adjust the transparency level for the skin background.')))
            if config.plugins.xDreamy.colorSelector.value == 'color23_Custom':
                list.append(getConfigListEntry(_('      - Titles Color:'), config.plugins.xDreamy.BasicColor, _('Select the color for main titles.')))
                list.append(getConfigListEntry(_('      - Text Color:'), config.plugins.xDreamy.WhiteColor, _('Select the color for general text.')))
                list.append(getConfigListEntry(_('      - Selection Color:'), config.plugins.xDreamy.SelectionColor, _('Select the color for selection highlights.')))
                list.append(getConfigListEntry(_('      - Background Color:'), config.plugins.xDreamy.BackgroundColor, _('Select the color for the skin background.')))
                list.append(getConfigListEntry(_('      - Background Transparency:'), config.plugins.xDreamy.transparency, _('Adjust the transparency level for the skin background.')))
            list.append(getConfigListEntry(_('Menu Font Color:'), config.plugins.xDreamy.menufontcolor, _('Choose the font color for the menu. Default is white.')))
            list.append(getConfigListEntry(_('Channel Names Color:'), config.plugins.xDreamy.channelnamecolor, _('Choose the font color for channel names. Default is white.')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('SKIN BASIC SCREENS  __________________________________________________________')
            list.append(getConfigListEntry(section))

#            section = '\\c0056c856' + _('InfoBar :')
#            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('InfoBar Style:'), config.plugins.xDreamy.InfobarStyle, _('Choose the style for the InfoBar from the templates or Choose "Custom - Infobar" to customize the header, middle and footer using the options below..')))
            if config.plugins.xDreamy.InfobarStyle.value == 'InfoBar-HMF':
                list.append(getConfigListEntry(_('      - Infobar Header'), config.plugins.xDreamy.InfobarH, _('Select the style for the InfoBar Header after choosing "Custom - Infobar" to customize the Header of your customized InfoBar.')))
                list.append(getConfigListEntry(_('      - Infobar Middle'), config.plugins.xDreamy.InfobarM, _('Select the style for the InfoBar Middle after choosing "Custom - Infobar" to customize the Middle of your customized InfoBar.')))
                list.append(getConfigListEntry(_('      - Infobar Footer'), config.plugins.xDreamy.InfobarF, _('Select the style for the InfoBar Footer after choosing "Custom - Infobar" to customize the Footer of your customized InfoBar.')))

#            section = '\\c0056c856' + _('SecondInfobar :')
#            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('SecondInfobar Style'), config.plugins.xDreamy.SecondInfobar, _('Select the style for the SecondInfoBar templates or Choose "Custom - SecondInfobar" to customize the header and footer using the options below.')))
            if config.plugins.xDreamy.SecondInfobar.value == 'SecondInfobar-HF':            
                list.append(getConfigListEntry(_('      - SecondInfobar H'), config.plugins.xDreamy.SecondInfobarH, _('Select the header style for the custom SecondInfoBar.')))
                list.append(getConfigListEntry(_('      - SecondInfobar F'), config.plugins.xDreamy.SecondInfobarF, _('Select the footer style for the custom SecondInfobar.')))
            
#            section = '\\c0056c856' + _('Channels List :')
#            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Channels List Style'), config.plugins.xDreamy.ChannSelector, _('Choose the style for the regular channels list, working with all images')))
            list.append(getConfigListEntry(_('Channels List Grid'), config.plugins.xDreamy.ChannSelectorGrid, _('Select the grid style for the channels list in the supported images. Currently supported by OpenATV, Egami, Foxbob, OpenDroid images. Open Channels List press Menu>Settings> Channel Selection Legacy=Regular & Full Screen=Grid')))

#            section = '\\c0056c856' + _('OTHERS SCREENS :')
#            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('EventView Style:'), config.plugins.xDreamy.EventView, _('Choose the style for the EventView screen.')))
            list.append(getConfigListEntry(_('Volume Bar Style:'), config.plugins.xDreamy.VolumeBar, _('Choose the style for the Volume Bar display.')))
            list.append(getConfigListEntry(_('Plugin Browser Style:'), config.plugins.xDreamy.PluginBrowser, _('Select the style for the Grid Plugin Browser. Supported by OpenATV, Egami, Foxbob, OpenSpa, and OpenDroid images.')))
            list.append(getConfigListEntry(_('EPG MultiSelection Style:'), config.plugins.xDreamy.EPGMultiSelection, _('Choose the style for the EPG MultiSelection screen.')))
            list.append(getConfigListEntry(_('History Zap Selector Style:'), config.plugins.xDreamy.HistoryZapSelector, _('Select the style for the Image History Zap Selector.')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('USER PLUGINS SCREENS  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('E2Player Style:'), config.plugins.xDreamy.E2Player, _('Select the style for the E2Player Plugin')))
            list.append(getConfigListEntry(_('New Virtual Keyboard Style:'), config.plugins.xDreamy.NewVirtualKeyboard, _('Choose the style for the New Virtual Keyboard plugin.')))
            list.append(getConfigListEntry(_('Enhanced Movie Center Style:'), config.plugins.xDreamy.EnhancedMovieCenter, _('Select the style for the Enhanced Movie Center "EMC"')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('USER BACKGROUND  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('ShutDown Style:'), config.plugins.xDreamy.TurnOff, _('Choose the background wallpaper style for the restart, reboot, shutdown screen')))
            list.append(getConfigListEntry(_('Bootlogos Random:'), config.plugins.xDreamy.bootlogos, _('Enable or Disable skin random Bootlogos. When enabled, The skin Bootlogos will change randomly with each reboot, restart, and power-off. Disabling this option restores the original image Bootlogo.')))
            list.append(getConfigListEntry(_('Virtual Keyboard Style:'), config.plugins.xDreamy.VirtualKeyboard, _('Choose the style for the image virtual keyboard, Default is skin color, or Balck Bacground or Image Background.')))
            list.append(getConfigListEntry(_('Channels List Background Style:'), config.plugins.xDreamy.ChannelListBackground, _('Choose the background wallpaper style for the regular channels list, Default=skin color.')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('USER DATA SOURCE  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Bitrate Source:'), config.plugins.xDreamy.BitrateSource, _('Select the source for bitrate information. The default option uses the skin renderer to calculate values. or install Bitrates Plugin from image feed, default is skin render')))
            list.append(getConfigListEntry(_('Rating & Stars:'), config.plugins.xDreamy.RatingStars, _('Enable or disable parental rating stars based on IMDB and OMDB information. default is disable')))
            list.append(getConfigListEntry(_('Subtitles Clock:'), config.plugins.xDreamy.SubtitlesClock, _('Select the position for the subtitles clock. This is active only when the subtitles-text option is enabled.')))
            list.append(getConfigListEntry(_('SoftCam Name:'), config.plugins.xDreamy.CamName, _('Select the source for SoftCam information. Use this if the SoftCam name is not displayed properly or if you want to change the name format.')))
            list.append(getConfigListEntry(_('Crypt Infobar:'), config.plugins.xDreamy.crypt, _('Select the style of Crypt Data in infoBar, Default is Name')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('WEATHER DATA SOURCE  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Weather Source:'), config.plugins.xDreamy.WeatherSource, _('Select the source plugin for weather information "Default is OAWeather" ')))
            list.append(getConfigListEntry("      Install or Open OAWeather Plugin", config.plugins.xDreamy.oaweather))
            list.append(getConfigListEntry("      Install or Open MsnWeather Plugin", config.plugins.xDreamy.weather))
            if os.path.isdir(weatherz):
                list.append(getConfigListEntry("     Setting Weather City", config.plugins.xDreamy.city, _('Set the city for weather information directly from the plugin')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('SERVER API KEY SETUP  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("API KEY SETUP:", config.plugins.xDreamy.actapi, _("Apply the skin API keys or insert your personal API keys.")))
            if config.plugins.xDreamy.actapi.value is True:
                list.append(getConfigListEntry("    TMDB API:", config.plugins.xDreamy.data, _("Settings TMDB ApiKey")))
                if config.plugins.xDreamy.data.value is True:
                    list.append(getConfigListEntry("      - Load TMDB Apikey", config.plugins.xDreamy.api, _("Load TMDB Apikey from /tmp/apikey.txt")))
                    list.append(getConfigListEntry("      - Set TMDB Apikey", config.plugins.xDreamy.txtapi, _("Signup on TMDB and input your free personal ApiKey manually")))
                list.append(getConfigListEntry("    OMDB API:", config.plugins.xDreamy.data2, _("Settings OMDB APIKEY")))
                if config.plugins.xDreamy.data2.value is True:
                    list.append(getConfigListEntry("      - Load OMDB Apikey", config.plugins.xDreamy.api2, _("Load OMDB Apikey from /tmp/omdbkey.txt")))
                    list.append(getConfigListEntry("      - Set OMDB Apikey", config.plugins.xDreamy.txtapi2, _("Signup on OMDB and input your free personal ApiKey manually")))
                list.append(getConfigListEntry("    TVDB API:", config.plugins.xDreamy.data3, _("Settings TheTVDB APIKEY")))
                if config.plugins.xDreamy.data3.value is True:
                    list.append(getConfigListEntry("      - Load TVDB Apikey", config.plugins.xDreamy.api3, _("Load TheTVDB Apikey from /tmp/thetvdbkey.txt")))
                    list.append(getConfigListEntry("    - Set TVDB Apikey", config.plugins.xDreamy.txtapi3, _("Signup on TheTVDB and input your free personal ApiKey manually")))
                list.append(getConfigListEntry("    Fanart API:", config.plugins.xDreamy.data4, _("Settings Fanart APIKEY")))
                if config.plugins.xDreamy.data4.value is True:
                    list.append(getConfigListEntry("      - Load Fanart Apikey", config.plugins.xDreamy.api4, _("Load Fanart Apikey from /tmp/fanartkey.txt")))
                    list.append(getConfigListEntry("      - Set Fanart Apikey", config.plugins.xDreamy.txtapi4, _("Signup on Fanart and input your free personal ApiKey manually")))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('POSTERS SOURCES  __________________________________________________________')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('POSTERS:'), config.plugins.xDreamy.posters, _('Select the primary color scheme for the skin.')))
            if config.plugins.xDreamy.posters.value == 'iPosterX':
            # Add new entries for PosterX features
                list.append(getConfigListEntry(_("Enable PosterX"), config.plugins.xDreamy.enablePosterX, _("Enable or disable the PosterX plugin.")))
                if config.plugins.xDreamy.enablePosterX.value is True:
                    list.append(getConfigListEntry(_("Poster Removal Interval"), config.plugins.xDreamy.posterRemovalInterval, _("Set the time interval for auto-removal of posters.")))
                    list.append(getConfigListEntry(_('Remove all Posters (OK)'), config.plugins.xDreamy.png, _('Remove all posters PNG files from the poster and backdrop folders.')))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c00289496' + _('=================================================================')
            list.append(getConfigListEntry(section))
            section = '\\c00ff5400' + _('                                XDREAMY TOOLS BOX                ')
            list.append(getConfigListEntry(section))
            section = '\\c00289496' + _('=================================================================')
            list.append(getConfigListEntry(section))

            section = '\\c0056c856' + _('Panels Plugins :')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("    AJPanel", config.plugins.xDreamy.install_ajpanel, _("Install or Open AJPanel: A versatile plugin developed by AMAJamry that includes a set of powerful tools to fully control your Enigma2 box. Features include system management, plugin updates, streaming services, and more.")))
            list.append(getConfigListEntry("    Linuxsat Panel", config.plugins.xDreamy.install_linuxsatpanel, _("Install or Open LinuxsatPanel: An all-in-one management tool supported by Linuxsat-support. It provides a comprehensive set of features for managing your Enigma2 device, including system information, plugin updates, and more.")))
            list.append(getConfigListEntry("    Ciefp Plugins", config.plugins.xDreamy.install_CiefpPlugins, _("Install or Open Ciefp Plugins Panel: An all-in-one management tool supported by Ciefp. It provides a comprehensive set of features for managing your Enigma2 device, including channels settings and more.")))
            list.append(getConfigListEntry("    SmartAddns Panel", config.plugins.xDreamy.install_smartpanel, _("Install or Open SmartPanel Supported by Emil Nabil.")))
            list.append(getConfigListEntry("    EliSat Panel", config.plugins.xDreamy.install_elisatpanel, _("Install or Open EliSatPanel Supported by EliSat.")))
            list.append(getConfigListEntry("    Magic Panel", config.plugins.xDreamy.install_magicpanel, _("Install or Open MagicPanel Supported by Hamdy Ahmed.")))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c0056c856' + _('Weather Plugins :')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("    MSNWeather", config.plugins.xDreamy.install_msnweather, _("Install or Open MSNWeather Plugin: A weather forecasting plugin supported by Fairbird. It provides accurate and up-to-date weather information, including forecasts, current conditions, and weather alerts.")))
            list.append(getConfigListEntry("    OAWeather", config.plugins.xDreamy.install_oaweather, _("Install or Open OAWeather Plugin (from external source): A weather forecasting plugin supported by Lululla. It provides accurate and up-to-date weather information, including forecasts, current conditions, and weather alerts.")))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c0056c856' + _('SoftCam Plugins :')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("    MultiCamManager", config.plugins.xDreamy.install_multicammanager, _("Install or Open MultiCamManager: A plugin developed by Levi45 for managing softcams. It allows you to download and install the latest versions of OSCam and NCam files, providing an easy way to manage multiple CAM configurations.")))
            list.append(getConfigListEntry("    NCam", config.plugins.xDreamy.install_NCam, _("Install or Open NCam emulator for enigma2, supported by Fairbaird")))
            list.append(getConfigListEntry("    KeyAdder", config.plugins.xDreamy.install_keyadder, _("Install or Open KeyAdder plugin to update Softcam file from diffrenet resources")))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c0056c856' + _('Media Plugins :')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("    X-Klass", config.plugins.xDreamy.install_xklass, _("Install or Open X-Klass: A feature-rich IPTV streaming plugin supported by KiddaC. It offers a wide range of IPTV channels and includes advanced features such as EPG, recording, and playback options.")))
            list.append(getConfigListEntry("    YouTube", config.plugins.xDreamy.install_youtube, _("Install or Open")))
            list.append(getConfigListEntry("    E2iPlayer", config.plugins.xDreamy.install_e2iplayer, _("Install or Open E2iPlayer: A popular plugin developed by Mohamed_OS for watching online videos, movies, and series. It supports various streaming services and provides a user-friendly interface for easy navigation.")))
            list.append(getConfigListEntry("    Transmission", config.plugins.xDreamy.install_transmission, _("Install or Open Transmission: A torrent client plugin supported by Ostende. It allows you to download and watch the latest content from torrent sites directly on your Enigma2 device. Features include torrent management, download scheduling, and more.")))
            list.append(getConfigListEntry("    MultiStalkerPro", config.plugins.xDreamy.install_multistalkerpro, _("Install or Open MultiStalkerPro: A powerful plugin for managing IPTV stalker portals. It provides advanced features for streaming and managing IPTV content.")))

            section = '\\c00289496' + _('  ')
            list.append(getConfigListEntry(section))

            section = '\\c0056c856' + _('Utility Plugins :')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("    IPAudioPro", config.plugins.xDreamy.install_ipaudiopro, _("Install or Open IPAudioPro Plugin: A plugin used to add audio for the playing channels with your own lang, Supported by Ziko.")))
            list.append(getConfigListEntry("    EPGGrabber", config.plugins.xDreamy.install_EPGGrabber, _("Install or Open.")))
            list.append(getConfigListEntry("    SubsSupport", config.plugins.xDreamy.install_subssupport, _("Install or Open SubsSupport: A plugin for managing subtitle downloads and synchronization. It supports various subtitle formats and provides an easy way to find and apply subtitles to your media content.")))
            list.append(getConfigListEntry("    HistoryZapSelector", config.plugins.xDreamy.install_historyzapselector, _("Install or Open HistoryZapSelector: A plugin for managing and navigating your zap history. It provides an intuitive interface for easy access to previously viewed channels and programs.")))
            list.append(getConfigListEntry("    NewVirtualKeyboard", config.plugins.xDreamy.install_newvirtualkeyboard, _("Install or Open NewVirtualKeyboard: A modern virtual keyboard plugin that offers enhanced functionality and a user-friendly interface for easy text input on your Enigma2 device.")))
            list.append(getConfigListEntry("    RaedQuickSignal", config.plugins.xDreamy.install_raedquicksignal, _("Install or Open RaedQuickSignal which offer a modern interface to display AGC and SNR plus more tools and resouces.")))

            self["config"].list = list
            self["config"].l.setList(list)
            self.updateHelpText()
            self.ShowPicture()

        except Exception as e:
            logger.error(_("Error in createSetup: {error}").format(error=e))

    def onInfobarStyleChange(self, configElement):
        self.createSetup()

    def GetPicturePath(self):
        currentConfig = self["config"].getCurrent()
        if currentConfig and len(currentConfig) > 1:
            returnValue = currentConfig[1].value
        else:
            returnValue = '/usr/share/enigma2/xDreamy/screens/default.png'
        PicturePath = '/usr/share/enigma2/xDreamy/screens/default.png'
        if not isinstance(returnValue, str):
            returnValue = PicturePath
        PicturePath = convert_image(PicturePath)
        c = ['setup', 'autoupdate', 'theweather', 'user', 'basic', 'weather source:']
        if currentConfig and currentConfig[0].lower().strip() in c:
            return PicturePath

        if currentConfig and 'oaweather' in currentConfig[0].lower().strip():
            return PicturePath
        if currentConfig and 'msnweather' in currentConfig[0].lower().strip():
            return PicturePath
        path = '/usr/share/enigma2/xDreamy/screens/' + returnValue + '.png'
        if fileExists(path):
            return convert_image(path)
        else:
            return PicturePath

    def UpdatePicture(self):
        self.onLayoutFinish.append(self.ShowPicture)

    def removPng(self):
        logger.info(_('Removing PNG files...'))
        removePng()
        logger.info(_('PNG files removed'))
        aboutbox = self.session.open(MessageBox, _('All png are removed from folder!'), MessageBox.TYPE_INFO)
        aboutbox.setTitle(_('Info...'))
        
    def ShowPicture(self, data=None):
        """عرض الصور بناءً على العنصر المحدد في القائمة."""
        if not self["Preview"].instance:
            return

        size = self['Preview'].instance.size()
        if size.isNull():
            size.setWidth(498)
            size.setHeight(280)

        # ✅ الحصول على مسار الصورة الافتراضية
        default_image_path = "/usr/share/enigma2/xDreamy/screens/default.png"

        # ✅ الحصول على مسار الصورة بناءً على العنصر الحالي
        pixmapx = self.GetPicturePath()

        if fileExists(pixmapx):
            logger.debug(_("Loading default preview image: {pixmapx}").format(pixmapx=pixmapx))
        else:
            logger.warning(_("Preview image not found: {pixmapx}, checking for specific item image...").format(pixmapx=pixmapx))
            pixmapx = default_image_path  # تعيين الصورة الافتراضية إذا لم يتم العثور على الصورة الخاصة

        # ✅ البحث عن الصورة بناءً على العنصر المحدد في القائمة
        current_item = self["config"].getCurrent()
    
        if current_item and len(current_item) > 0:
            item_name = current_item[0].lower().replace("install_", "").replace(" ", "")

            # ✅ التحقق مما إذا كان العنصر هو "قالب لون" أو "إضافة"
            image_path = f"/usr/share/enigma2/xDreamy/screens/{item_name}.png"
            if fileExists(image_path):
                logger.debug(_("Loading specific item image: {image_path}").format(image_path=image_path))
                pixmapx = image_path
            else:
                logger.warning(_("Image not found for {item_name}, using default image.").format(item_name=item_name))
    
        # ✅ تحميل الصورة النهائية
        if fileExists(pixmapx):
            png = loadPic(pixmapx, size.width(), size.height(), 0, 0, 0, 1)
            self["Preview"].instance.setPixmap(png)
            logger.debug(_("Image displayed: {pixmapx}").format(pixmapx=pixmapx))
        else:
            logger.warning(_("No valid image found, skipping preview update."))

    def DecodePicture(self, PicInfo=None):
        logger.debug(_('PicInfo={PicInfo}').format(PicInfo=PicInfo))
        if PicInfo is None:
            PicInfo = '/usr/share/enigma2/xDreamy/screens/default.png'
        ptr = self.PicLoad.getData()
        if ptr is not None:
            self["Preview"].instance.setPixmap(ptr)
            self["Preview"].instance.show()
        else:
            logger.warning(_("Image data not available. Check the image."))

    def info(self):
        aboutbox = self.session.open(MessageBox, _('Setup xDreamy for xDreamy v.{version}').format(version=version), MessageBox.TYPE_INFO)
        aboutbox.setTitle(_('Info...'))

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        self.createSetup()
        sel = self["config"].getCurrent()[1]
        if sel and sel == config.plugins.xDreamy.png:
            config.plugins.xDreamy.png.setValue(0)
            config.plugins.xDreamy.png.save()
            self.removPng()
        if sel and sel == config.plugins.xDreamy.api:
            config.plugins.xDreamy.api.setValue(0)
            config.plugins.xDreamy.api.save()
            self.keyApi()
        if sel and sel == config.plugins.xDreamy.api2:
            config.plugins.xDreamy.api2.setValue(0)
            config.plugins.xDreamy.api2.save()
            self.keyApi2()
        if sel and sel == config.plugins.xDreamy.api3:
            config.plugins.xDreamy.api3.setValue(0)
            config.plugins.xDreamy.api3.save()
            self.keyApi3()
        if sel and sel == config.plugins.xDreamy.api4:
            config.plugins.xDreamy.api4.setValue(0)
            config.plugins.xDreamy.api4.save()
            self.keyApi4()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        self.createSetup()
        sel = self["config"].getCurrent()[1]
        if sel and sel == config.plugins.xDreamy.png:
            config.plugins.xDreamy.png.setValue(0)
            config.plugins.xDreamy.png.save()
            self.removPng()
        if sel and sel == config.plugins.xDreamy.api:
            config.plugins.xDreamy.api.setValue(0)
            config.plugins.xDreamy.api.save()
            self.keyApi()
        if sel and sel == config.plugins.xDreamy.api2:
            config.plugins.xDreamy.api2.setValue(0)
            config.plugins.xDreamy.api2.save()
            self.keyApi2()
        if sel and sel == config.plugins.xDreamy.api3:
            config.plugins.xDreamy.api3.setValue(0)
            config.plugins.xDreamy.api3.save()
            self.keyApi3()
        if sel and sel == config.plugins.xDreamy.api4:
            config.plugins.xDreamy.api4.setValue(0)
            config.plugins.xDreamy.api4.save()
            self.keyApi4()

    def keyDown(self):
        self['config'].instance.moveSelection(self['config'].instance.moveDown)
        self.createSetup()

    def keyUp(self):
        self['config'].instance.moveSelection(self['config'].instance.moveUp)
        self.createSetup()

    def keyOK(self):
        current = self["config"].getCurrent()
        if current:
            sel = current[1]
            
            # ✅ If it's a text input (e.g., city name), open keyboard
            if sel == config.plugins.xDreamy.city:
                self.openCitySelection()
            elif isinstance(sel, ConfigText):
                self.KeyText()

            # ✅ If it's a selection list, open popup
            elif isinstance(sel, ConfigSelection):
                self.openSelectionPopup(current)

    def changedEntry(self):
        self.item = self["config"].getCurrent()
        for x in self.onChangedEntry:
            x()
        try:
            if isinstance(self["config"].getCurrent()[1], ConfigOnOff) or isinstance(self["config"].getCurrent()[1], ConfigYesNo) or isinstance(self["config"].getCurrent()[1], ConfigSelection):
                self.createSetup()
        except Exception as e:
            logger.error(_("Error in changedEntry: {error}").format(error=e))

    def getCurrentValue(self):
        current = self["config"].getCurrent()
        if current and len(current) > 1:
            return str(current[1].getText())
        return ""

    def getCurrentEntry(self):
        current = self["config"].getCurrent()
        if current:
            return current[0]
        return ""

    def createSummary(self):
        from Screens.Setup import SetupSummary
        return SetupSummary

    def keySave(self):
        """حفظ الإعدادات وتحديث الملفات الضرورية ثم إعادة تشغيل الواجهة إذا لزم الأمر."""

        try:
            # ✅ تحديث Bootlogo إذا تم التفعيل
            if config.plugins.xDreamy.bootlogos.value:
                if not fileExists(mvi + 'bootlogoBack.mvi'):
                    shutil.copy(mvi + 'bootlogo.mvi', mvi + 'bootlogoBack.mvi')
            else:
                if fileExists(mvi + 'bootlogoBack.mvi'):
                    shutil.copy(mvi + 'bootlogoBack.mvi', mvi + 'bootlogo.mvi')
                    os.remove(mvi + 'bootlogoBack.mvi')

            # ✅ تحديث الخط إذا كان النمط مخصصًا
            if config.plugins.xDreamy.FontStyle.value == 'basic':
                update_font_settings(
                    config.plugins.xDreamy.FontName.value, 
                    config.plugins.xDreamy.FontScale.value
                )

            # ✅ تحديث الألوان بناءً على الإعدادات المختارة
            if config.plugins.xDreamy.colorSelector.value == "default-color":
                apply_template(config.plugins.xDreamy.BasicColorTemplates.value)
            elif config.plugins.xDreamy.colorSelector.value == "color23_Custom":
                update_individual_colors(
                    ltbluette_value=config.plugins.xDreamy.BasicColor.value,
                    white_value=config.plugins.xDreamy.WhiteColor.value,
                    bluette_value=config.plugins.xDreamy.SelectionColor.value,
                    header_value=config.plugins.xDreamy.BackgroundColor.value)

            # ✅ تحديث تنسيق التاريخ في ملفات السكين
            applyDateFormat()  # ✅ Ensure the date format is applied before saving
    
            # ✅ حفظ جميع التعديلات
            for x in self['config'].list:
                if len(x) > 1:  # التحقق من وجود قيم للحفظ
                    x[1].save()
            # Save the new configurations
            config.plugins.xDreamy.enablePosterX.save()
            config.plugins.xDreamy.posterRemovalInterval.save()
            config.plugins.xDreamy.city.save()
            config.plugins.xDreamy.save()
            configfile.save()
            os.system("sync")  # تأكيد حفظ التغييرات في النظام
    
        except Exception as e:
            logger.error(_("⚠️ خطأ أثناء حفظ الإعدادات: {error}").format(error=e))
    
        try:
            # ✅ إنشاء ملف السكين الجديد
            skin_lines = []
            skin_file_paths = [
                f'head-{config.plugins.xDreamy.head.value}.xml',
                f'font-{config.plugins.xDreamy.FontStyle.value}.xml',
                f'C-{config.plugins.xDreamy.colorSelector.value}.xml',
                f'DC-{config.plugins.xDreamy.clockFormat.value}.xml',
                f'TP-{config.plugins.xDreamy.skinTemplate.value}.xml',
                f'keys-{config.plugins.xDreamy.KeysStyle.value}.xml',
                f'infobar-{config.plugins.xDreamy.InfobarStyle.value}.xml',
                f'IH-{config.plugins.xDreamy.InfobarH.value}.xml',
                f'IM-{config.plugins.xDreamy.InfobarM.value}.xml',
                f'IF-{config.plugins.xDreamy.InfobarF.value}.xml',
                f'secondinfobar-{config.plugins.xDreamy.SecondInfobar.value}.xml',
                f'SIH-{config.plugins.xDreamy.SecondInfobarH.value}.xml',
                f'SIF-{config.plugins.xDreamy.SecondInfobarF.value}.xml',
                f'CHL-{config.plugins.xDreamy.ChannSelector.value}.xml',
                f'CHLG-{config.plugins.xDreamy.ChannSelectorGrid.value}.xml',
                f'CLB-{config.plugins.xDreamy.ChannelListBackground.value}.xml',
                f'CLB1-{config.plugins.xDreamy.TurnOff.value}.xml',
                f'EV-{config.plugins.xDreamy.EventView.value}.xml',
                f'vol-{config.plugins.xDreamy.VolumeBar.value}.xml',
                f'VKB-{config.plugins.xDreamy.VirtualKeyboard.value}.xml',
                f'NVKB-{config.plugins.xDreamy.NewVirtualKeyboard.value}.xml',
                f'PB-{config.plugins.xDreamy.PluginBrowser.value}.xml',
                f'HZS-{config.plugins.xDreamy.HistoryZapSelector.value}.xml',
                f'EPG-{config.plugins.xDreamy.EPGMultiSelection.value}.xml',
                f'E2Player-{config.plugins.xDreamy.E2Player.value}.xml',
                f'EMC-{config.plugins.xDreamy.EnhancedMovieCenter.value}.xml',
                f'WS-{config.plugins.xDreamy.WeatherSource.value}.xml',
                f'BS-{config.plugins.xDreamy.BitrateSource.value}.xml',
                f'SC-{config.plugins.xDreamy.SubtitlesClock.value}.xml',
                f'RS-{config.plugins.xDreamy.RatingStars.value}.xml',
                f'MC-{config.plugins.xDreamy.menufontcolor.value}.xml',
                f'CRY-{config.plugins.xDreamy.crypt.value}.xml',
                f'CC-{config.plugins.xDreamy.channelnamecolor.value}.xml',
                f'CA-{config.plugins.xDreamy.CamName.value}.xml'
            ]

            for file_name in skin_file_paths:
                file_path = os.path.join(self.previewFiles, file_name)
                if os.path.isfile(file_path):
                    with open(file_path, 'r') as skFile:
                        skin_lines.extend(skFile.readlines())
    
            base_file_name = 'base.xml'
            if config.plugins.xDreamy.skinSelector.value in ['base1', 'base2', 'base3', 'base4']:
                base_file_name = f'base{config.plugins.xDreamy.skinSelector.value[-1]}.xml'
    
            base_file_path = os.path.join(self.previewFiles, base_file_name)
            if os.path.isfile(base_file_path):
                with open(base_file_path, 'r') as skFile:
                    skin_lines.extend(skFile.readlines())
    
            with open(self.skinFile, 'w') as xFile:
                xFile.writelines(skin_lines)
    
            # ✅ طلب إعادة تشغيل الواجهة لتطبيق التغييرات
            self.session.openWithCallback(
                self.restartGUI, 
                MessageBox, 
                _('GUI needs a restart to apply a new skin.\nDo you want to Restart the GUI now?'), 
                MessageBox.TYPE_YESNO
            )

        except Exception as e:
            if hasattr(self, 'session'):
                self.session.open(MessageBox, _('Error processing the skin file! ') + str(e), MessageBox.TYPE_ERROR)
            else:
                logger.error(_("⚠️ Error processing skin file: {error}").format(error=e))

    def restartGUI(self, answer):
        if answer is True:
            self.session.open(TryQuitMainloop, 3)
        else:
            self.close()

    def checkforUpdate(self):
        try:
            destr = '/tmp/xDreamyv.txt'
            req = Request('https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamyv.txt')
            req.add_header('User-Agent', 'Mozilla/5.0')
            response = urlopen(req)
            data = response.read().decode('utf-8').strip()

            logger.debug(_('fp read: {fp}').format(fp=data))

            with open(destr, 'w') as f:
                f.write(data)

            if fileExists(destr):
                with open(destr, 'r') as cc:
                    line = cc.readline().strip()
                    vers, url = line.split('#')
                    version_server = vers.strip()
                    self.updateurl = url.strip()

                # Compare versions
                if str(version_server) == str(version):
                    message = _(
                        '{server_version} {version_server}\n{installed_version} {version}\n\n{congrats}'
                    ).format(
                        server_version=_('Server version:'),
                        version_server=version_server,
                        installed_version=_('Version installed:'),
                        version=version,
                        congrats=_('Congratulation, You have the last version of XDREAMY!')
                    )
                    self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

                elif version_server > version:
                    changelog = self.getChangelogText()
                    message = _(
                        'Server version: {server_v}\nInstalled version: {local_v}\n\nUpdate available!\n\nWhat’s New:\n{changelog}\n\nDo you want to run the update now?'
                    ).format(
                        server_v=version_server,
                        local_v=version,
                        changelog=changelog
                    )
                    self.session.openWithCallback(self.update, MessageBox, message, MessageBox.TYPE_YESNO)

                else:
                    self.session.open(
                        MessageBox,
                        _('You have version {version}!!!').format(version=version),
                        MessageBox.TYPE_INFO,
                        timeout=10
                    )
        except Exception as e:
            logger.error(_('error: {error}').format(error=str(e)))

    def update(self, answer):
        if answer is True:
            self.session.open(xDreamyUpdater, self.updateurl)
        else:
            return

    def keyExit(self):
        self.close()

    def KeyMenu(self):
        if os.path.isdir(weatherz):
            weatherPluginEntryCount = config.plugins.WeatherPlugin.entrycount.value
            if weatherPluginEntryCount >= 1:
                self.session.openWithCallback(self.goWeather, MessageBox, _('Data entered for the Weather, do you want to continue the same?'), MessageBox.TYPE_YESNO)
            else:
                self.goWeather(True)
        else:
            restartbox = self.session.openWithCallback(self.goWeatherInstall, MessageBox, _('Weather Plugin Plugin Not Installed!!\nDo you really want to install now?'), MessageBox.TYPE_YESNO)
            restartbox.setTitle(_('Install Weather Plugin and Reboot'))
        self.UpdatePicture()

    def goWeather(self, result=False):
        if result:
            try:
                from .addons import WeatherSearch
                entry = config.plugins.WeatherPlugin.Entry[0]
                self.session.openWithCallback(self.UpdateComponents, WeatherSearch.MSNWeatherPluginEntryConfigScreen, entry)
            except Exception as e:
                logger.error(_("Error in goWeather: {error}").format(error=e))

    def goWeatherInstall(self, result=False):
        if result:
            try:
                cmd = 'enigma2-plugin-extensions-weatherplugin'
                self.session.open(Console, _('Install WeatherPlugin'), ['opkg install {cmd}'.format(cmd=cmd)], closeOnSuccess=False)
                time.sleep(5)
            except Exception as e:
                logger.error(_("Error in goWeatherInstall: {error}").format(error=e))
        else:
            message = _('Plugin WeatherPlugin not installed!!!')
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

    def KeyMenu2(self, answer=None):
        if os.path.isdir(OAWeather):
            if answer is None:
                self.session.openWithCallback(self.KeyMenu2, MessageBox, _('Open OAWeather, do you want to continue?'), MessageBox.TYPE_YESNO)
            elif answer:
                self.goOAWeather(True)
        else:
            restartbox = self.session.openWithCallback(self.goOAWeatherInstall, MessageBox, _('OAWeather Plugin Plugin Not Installed!!\nDo you really want to install now?'), MessageBox.TYPE_YESNO)
            restartbox.setTitle(_('Install OAWeather Plugin and Reboot'))
        self.UpdatePicture()

    def goOAWeather(self, result=False):
        if result:
            try:
                from Plugins.Extensions.OAWeather.plugin import WeatherSettingsView
                logger.debug(_('i am here!!'))
                self.session.openWithCallback(self.UpdateComponents2, WeatherSettingsView)
            except Exception as e:
                logger.debug(_('passed!!'))
                logger.error(_("Error in goOAWeather: {error}").format(error=e))

    def goOAWeatherInstall(self, result=False):
        if result:
            try:
                cmd = 'enigma2-plugin-extensions-oaweather'
                self.session.open(Console, _('Install OAWeatherPlugin'), ['opkg install {cmd}'.format(cmd=cmd)], closeOnSuccess=False)
                time.sleep(5)
            except Exception as e:
                logger.error(_("Error in goOAWeatherInstall: {error}").format(error=e))
        else:
            message = _('Plugin OAWeatherPlugin not installed!!!')
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

    def UpdateComponents(self):
        try:
            weatherPluginEntryCount = config.plugins.WeatherPlugin.entrycount.value
            if weatherPluginEntryCount >= 1:
                zLine = ''
                weatherPluginEntry = config.plugins.WeatherPlugin.Entry[0]
                location = weatherPluginEntry.weatherlocationcode.value
                city = weatherPluginEntry.city.value
                zLine = str(city) + ' - ' + str(location)
                config.plugins.xDreamy.city.setValue(zLine)
                config.plugins.xDreamy.city.save()
                self['city'].setText(zLine)
                self.createSetup()
            else:
                return
        except Exception as e:
            logger.error(_("Error in UpdateComponents: {error}").format(error=e))

    def UpdateComponents2(self):
        try:
            if config.plugins.OAWeather.enabled.value:
                zLine = ''
                city = config.plugins.OAWeather.weathercity.value
                location = config.plugins.OAWeather.owm_geocode.value.split(",")
                zLine = str(city)
                if location:
                    zLine += ' - ' + str(location)
                config.plugins.xDreamy.city.setValue(zLine)
                config.plugins.xDreamy.city.save()
                self['city'].setText(zLine)
                self.createSetup()
            else:
                return
        except Exception as e:
            logger.error(_("Error in UpdateComponents2: {error}").format(error=e))

class xDreamyUpdater(Screen):

    def __init__(self, session, updateurl):
        self.session = session
        skin = '''
                
                    
                    
                    
                                    <screen name="xDreamyUpdater" position="center,center" size="840,260" flags="wfBorder" backgroundColor="background">
                                        <widget name="status" position="20,10" size="800,70" transparent="1" font="Regular; 40" foregroundColor="foreground" backgroundColor="background" valign="center" halign="left" noWrap="1"/>
                                        <widget source="progress" render="Progress" position="20,120" size="800,20" transparent="1" borderWidth="0" foregroundColor="white" backgroundColor="background"/>
                                        <widget source="progresstext" render="Label" position="209,164" zPosition="2" font="Regular; 28" halign="center" transparent="1" size="400,70" foregroundColor="foreground" backgroundColor="background"/>
                                    </screen>'''

        self.skin = skin
        Screen.__init__(self, session)
        self.updateurl = updateurl
        logger.debug(_('self.updateurl: {updateurl}').format(updateurl=self.updateurl))
        self['status'] = Label()
        self['progress'] = Progress()
        self['progresstext'] = StaticText()
        self.downloading = False
        self.last_recvbytes = 0
        self.error_message = None
        self.download = None
        self.aborted = False
        self.startUpdate()

    def getChangelogText(self):
        try:
            changelog_url = "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/changelog.txt"
            req = Request(changelog_url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            response = urlopen(req, timeout=5)
            if response.getcode() == 200:
                return response.read().decode('utf-8').strip()
            else:
                return _("(Could not load changelog)")
        except Exception as e:
            return _("(Changelog error: %s)") % str(e)

    def startUpdate(self):
        self['status'].setText(_('Downloading XDREAMY Skin...'))
        self.dlfile = '/tmp/xDreamy.ipk'
        logger.debug(_('self.dlfile: {dlfile}').format(dlfile=self.dlfile))
        self.download = downloadWithProgress(self.updateurl, self.dlfile)
        self.download.addProgress(self.downloadProgress)
        self.download.start().addCallback(self.downloadFinished).addErrback(self.downloadFailed)

    def downloadFinished(self, string=''):
        self['status'].setText(_('Installing updates please wait!'))
        os.system('opkg install --force-reinstall --force-overwrite /tmp/xDreamy.ipk')
        os.system('sync')
        os.system('rm -r /tmp/xDreamy.ipk')
        os.system('sync')
        restartbox = self.session.openWithCallback(self.restartGUI, MessageBox, _('XDREAMY update was done!!!\nDo you want to restart the GUI now?'), MessageBox.TYPE_YESNO)
        restartbox.setTitle(_('Restart GUI now?'))

    def downloadFailed(self, failure_instance=None, error_message=''):
        text = _('Error downloading files!')
        if error_message == '' and failure_instance is not None:
            error_message = failure_instance.getErrorMessage()
            text += ': ' + error_message
        self['status'].setText(text)
        return

    def downloadProgress(self, recvbytes, totalbytes):
        self['status'].setText(_('Download in progress...'))
        self['progress'].value = int(100 * self.last_recvbytes / float(totalbytes))
        self['progresstext'].text = _('{recv_kbytes} of {total_kbytes} kBytes ({percent:.2f}%)').format(
            recv_kbytes=self.last_recvbytes / 1024,
            total_kbytes=totalbytes / 1024,
            percent=100 * self.last_recvbytes / float(totalbytes)
        )
        self.last_recvbytes = recvbytes

    def restartGUI(self, answer):
        if answer is True:
            self.session.open(TryQuitMainloop, 3)
        else:
            self.close()

    def goOAWeatherInstall(self, result=False):
        if result:
            try:
                cmd = 'enigma2-plugin-extensions-oaweather'
                self.session.open(Console, _('Install OAWeatherPlugin'), ['opkg install %s' % cmd], closeOnSuccess=False)
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error in goOAWeatherInstall: {e}")
        else:
            message = _('Plugin OAWeatherPlugin not installed!!!')
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

    def UpdateComponents(self):
        try:
            weatherPluginEntryCount = config.plugins.WeatherPlugin.entrycount.value
            if weatherPluginEntryCount >= 1:
                zLine = ''
                weatherPluginEntry = config.plugins.WeatherPlugin.Entry[0]
                location = weatherPluginEntry.weatherlocationcode.value
                city = weatherPluginEntry.city.value
                zLine = str(city) + ' - ' + str(location)
                config.plugins.xDreamy.city.setValue(zLine)
                config.plugins.xDreamy.city.save()
                self['city'].setText(zLine)
                self.createSetup()
            else:
                return
        except Exception as e:
            logger.error(f"Error in UpdateComponents: {e}")

    def UpdateComponents2(self):
        try:
            if config.plugins.OAWeather.enabled.value:
                zLine = ''
                city = config.plugins.OAWeather.weathercity.value
                location = config.plugins.OAWeather.owm_geocode.value.split(",")
                zLine = str(city)
                if location:
                    zLine += ' - ' + str(location)
                config.plugins.xDreamy.city.setValue(zLine)
                config.plugins.xDreamy.city.save()
                self['city'].setText(zLine)
                self.createSetup()
            else:
                return
        except Exception as e:
            logger.error(f"Error in UpdateComponents2: {e}")

class xDreamyUpdater(Screen):

    def __init__(self, session, updateurl):
        self.session = session
        skin = '''
                
                    
                    
                    
                                    <screen name="xDreamyUpdater" position="center,center" size="840,260" flags="wfBorder" backgroundColor="background">
                                        <widget name="status" position="20,10" size="800,70" transparent="1" font="Regular; 40" foregroundColor="foreground" backgroundColor="background" valign="center" halign="left" noWrap="1"/>
                                        <widget source="progress" render="Progress" position="20,120" size="800,20" transparent="1" borderWidth="0" foregroundColor="white" backgroundColor="background"/>
                                        <widget source="progresstext" render="Label" position="209,164" zPosition="2" font="Regular; 28" halign="center" transparent="1" size="400,70" foregroundColor="foreground" backgroundColor="background"/>
                                    </screen>'''

        self.skin = skin
        Screen.__init__(self, session)
        self.updateurl = updateurl
        logger.debug(f'self.updateurl: {self.updateurl}')
        self['status'] = Label()
        self['progress'] = Progress()
        self['progresstext'] = StaticText()
        self.downloading = False
        self.last_recvbytes = 0
        self.error_message = None
        self.download = None
        self.aborted = False
        self.startUpdate()

    def startUpdate(self):
        self['status'].setText(_('Downloading XDREAMY Skin...'))
        self.dlfile = '/tmp/xDreamy.ipk'
        logger.debug(f'self.dlfile: {self.dlfile}')
        self.download = downloadWithProgress(self.updateurl, self.dlfile)
        self.download.addProgress(self.downloadProgress)
        self.download.start().addCallback(self.downloadFinished).addErrback(self.downloadFailed)

    def downloadFinished(self, string=''):
        self['status'].setText(_('Installing updates please wait!'))
        os.system('opkg install --force-reinstall --force-overwrite /tmp/xDreamy.ipk')
        os.system('sync')
        os.system('rm -r /tmp/xDreamy.ipk')
        os.system('sync')
        restartbox = self.session.openWithCallback(self.restartGUI, MessageBox, _('XDREAMY update was done!!!\nDo you want to restart the GUI now?'), MessageBox.TYPE_YESNO)
        restartbox.setTitle(_('Restart GUI now?'))

    def downloadFailed(self, failure_instance=None, error_message=''):
        text = _('Error downloading files!')
        if error_message == '' and failure_instance is not None:
            error_message = failure_instance.getErrorMessage()
            text += ': ' + error_message
        self['status'].setText(text)
        return

    def downloadProgress(self, recvbytes, totalbytes):
        self['status'].setText(_('Download in progress...'))
        self['progress'].value = int(100 * self.last_recvbytes / float(totalbytes))
        self['progresstext'].text = '%d of %d kBytes (%.2f%%)' % (self.last_recvbytes / 1024, totalbytes / 1024, 100 * self.last_recvbytes / float(totalbytes))
        self.last_recvbytes = recvbytes

    def restartGUI(self, answer):
        if answer is True:
            self.session.open(TryQuitMainloop, 3)
        else:
            self.close()

def check_plugin_installed(plugin_name):
    plugin_paths = {
        "AJPanel": resolveFilename(SCOPE_PLUGINS, "Extensions/AJPan"),
        "LinuxsatPanel": resolveFilename(SCOPE_PLUGINS, "Extensions/LinuxsatPanel"),
        "CiefpPlugins": resolveFilename(SCOPE_PLUGINS, "Extensions/CiefpPlugins"),
        "SmartPanel": resolveFilename(SCOPE_PLUGINS, "Extensions/SmartAddonspanel"),
        "EliSatPanel": resolveFilename(SCOPE_PLUGINS, "Extensions/ElieSatPanel"),
        "MagicPanel": resolveFilename(SCOPE_PLUGINS, "Extensions/MagicPanel"),
        "MSNWeather": resolveFilename(SCOPE_PLUGINS, "Extensions/WeatherPlugin"),
        "OAWeather": resolveFilename(SCOPE_PLUGINS, "Extensions/OAWeather"),
        "MultiCamManager": resolveFilename(SCOPE_PLUGINS, "Extensions/Manager"),
        "NCam": resolveFilename(SCOPE_PLUGINS, "Extensions/NCam"),
        "KeyAdder": resolveFilename(SCOPE_PLUGINS, "Extensions/KeyAdder"),
        "XKlass": resolveFilename(SCOPE_PLUGINS, "Extensions/XKlass"),
        "YouTube": resolveFilename(SCOPE_PLUGINS, "Extensions/YouTube"),
        "E2iPlayer": resolveFilename(SCOPE_PLUGINS, "Extensions/IPTVPlayer"),
        "Transmission": resolveFilename(SCOPE_PLUGINS, "Extensions/Transmission"),
        "MultiStalkerPro": resolveFilename(SCOPE_PLUGINS, "Extensions/MultiStalkerPro"),
        "IPAudioPro": resolveFilename(SCOPE_PLUGINS, "Extensions/IPAudioPro"),
        "EPGGrabber": resolveFilename(SCOPE_PLUGINS, "Extensions/EPGGrabber"),
        "SubsSupport": resolveFilename(SCOPE_PLUGINS, "Extensions/SubsSupport"),
        "HistoryZapSelector": resolveFilename(SCOPE_PLUGINS, "Extensions/HistoryZapSelector"),
        "NewVirtualKeyboard": resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NewVirtualKeyBoard"),
        "RaedQuickSignal": resolveFilename(SCOPE_PLUGINS, "Extensions/RaedQuickSignal"),
    }
    if os.path.isdir(plugin_paths.get(plugin_name, "")):
        return True

    # Check the Enigma2 plugin registry
    try:
        from Plugins.Plugin import PluginDescriptor
        if hasattr(PluginDescriptor, 'plugins'):
            for plugin in PluginDescriptor.plugins:
                if plugin.name == plugin_name:
                    return True
    except ImportError:
        pass
    return False

def update_plugin_install_status():
    plugin_configs = {
        "LinuxsatPanel": config.plugins.xDreamy.install_linuxsatpanel,
        "AJPanel": config.plugins.xDreamy.install_ajpanel,
        "CiefpPlugins": config.plugins.xDreamy.install_CiefpPlugins,
        "SmartPanel": config.plugins.xDreamy.install_smartpanel,
        "EliSatPanel": config.plugins.xDreamy.install_elisatpanel,
        "MagicPanel": config.plugins.xDreamy.install_magicpanel,
        "MSNWeather": config.plugins.xDreamy.install_msnweather,
        "OAWeather": config.plugins.xDreamy.install_oaweather,
        "MultiCamManager": config.plugins.xDreamy.install_multicammanager,
        "NCam": config.plugins.xDreamy.install_NCam,
        "KeyAdder": config.plugins.xDreamy.install_keyadder,
        "XKlass": config.plugins.xDreamy.install_xklass,
        "YouTube": config.plugins.xDreamy.install_youtube,
        "E2iPlayer": config.plugins.xDreamy.install_e2iplayer,
        "Transmission": config.plugins.xDreamy.install_transmission,
        "MultiStalkerPro": config.plugins.xDreamy.install_multistalkerpro,
        "IPAudioPro": config.plugins.xDreamy.install_ipaudiopro,
        "EPGGrabber": config.plugins.xDreamy.install_EPGGrabber,
        "SubsSupport": config.plugins.xDreamy.install_subssupport,
        "HistoryZapSelector": config.plugins.xDreamy.install_historyzapselector,
        "NewVirtualKeyboard": config.plugins.xDreamy.install_newvirtualkeyboard,
        "RaedQuickSignal": config.plugins.xDreamy.install_raedquicksignal,
    }
    for plugin_name, config_entry in plugin_configs.items():
        if check_plugin_installed(plugin_name):
            config_entry.setValue(True)

# Call this function during initialization
update_plugin_install_status()