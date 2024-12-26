# -*- coding: utf-8 -*-
# mod by Lululla

from . import _
# from Components.AVSwitch import AVSwitch
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.config import (
    # ConfigInteger,
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
from enigma import eTimer, loadPic  # , ePicLoad
from PIL import Image
from Plugins.Plugin import PluginDescriptor
from Screens.Console import Console
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Tools.Directories import fileExists
from Tools.Directories import SCOPE_PLUGINS
from Tools.Directories import resolveFilename
from Tools.Downloader import downloadWithProgress
import os
import random
import sys
import time
import shutil
import glob

PY3 = sys.version_info.major >= 3
if PY3:
    from urllib.request import urlopen
    from urllib.request import Request
else:
    from urllib2 import urlopen
    from urllib2 import Request

version = "4.8.0"
my_cur_skin = False
cur_skin = config.skin.primary_skin.value.replace('/skin.xml', '')
OAWeather = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('OAWeather'))
weatherz = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('WeatherPlugin'))
mvi = '/usr/share/'
bootlog = '/usr/lib/enigma2/python/Plugins/Extensions/xDreamy/bootlogos/'
logopath = '/etc/enigma2/'
tmdb_skin = "%senigma2/%s/apikey" % (mvi, cur_skin)
tmdb_api = "3c3efcf47c3577558812bb9d64019d65"
omdb_skin = "%senigma2/%s/omdbkey" % (mvi, cur_skin)
omdb_api = "cb1d9f55"

try:
    if my_cur_skin is False:
        skin_paths = {
            "tmdb_api": "/usr/share/enigma2/{}/apikey".format(cur_skin),
            "omdb_api": "/usr/share/enigma2/{}/omdbkey".format(cur_skin),
            # "thetvdbkey": "/usr/share/enigma2/{}/thetvdbkey".format(cur_skin)
            # "visual_api": "/etc/enigma2/VisualWeather/apikey.txt"
        }
        for key, path in skin_paths.items():
            if fileExists(path):
                with open(path, "r") as f:
                    value = f.read().strip()
                    if key == "tmdb_api":
                        tmdb_api = value
                    elif key == "omdb_api":
                        omdb_api = value
                    # elif key == "thetvdbkey":
                        # thetvdbkey = value
                    # elif key == "visual_api":
                        # visual_api = value
                my_cur_skin = True
except Exception as e:
    print("Errore nel caricamento delle API:", str(e))
    my_cur_skin = False


def isMountedInRW(path):
    testfile = path + '/tmp-rw-test'
    os.system('touch ' + testfile)
    if os.path.exists(testfile):
        os.system('rm -f ' + testfile)
        return True
    return False


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
    print('Rimuovo file PNG e JPG...')
    if os.path.exists(path_poster):
        png_files = glob.glob(os.path.join(path_poster, "*.png"))
        jpg_files = glob.glob(os.path.join(path_poster, "*.jpg"))
        files_to_remove = png_files + jpg_files
        if not files_to_remove:
            print("Nessun file PNG o JPG trovato nella cartella " + path_poster)
        for file in files_to_remove:
            try:
                os.remove(file)
                print("Rimosso: " + file)
            except Exception as e:
                print("Errore durante la rimozione di " + file + ": " + str(e))
    else:
        print("La cartella " + path_poster + " non esiste.")

    if os.path.exists(patch_backdrop):
        png_files_backdrop = glob.glob(os.path.join(patch_backdrop, "*.png"))
        jpg_files_backdrop = glob.glob(os.path.join(patch_backdrop, "*.jpg"))
        files_to_remove_backdrop = png_files_backdrop + jpg_files_backdrop
        if not files_to_remove_backdrop:
            print("Nessun file PNG o JPG trovato nella cartella " + patch_backdrop)
        else:
            for file in files_to_remove_backdrop:
                try:
                    os.remove(file)
                    print("Rimosso: " + file)
                except Exception as e:
                    print("Errore durante la rimozione di " + file + ": " + str(e))
    else:
        print("La cartella " + patch_backdrop + " non esiste.")


config.plugins.xDreamy = ConfigSubsection()
config.plugins.xDreamy.png = NoSave(ConfigYesNo(default=False))  # NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.header = NoSave(ConfigNothing())
config.plugins.xDreamy.weather = NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.oaweather = NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.city = ConfigText(default='', visible_width=50, fixed_size=False)
config.plugins.xDreamy.actapi = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.data = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api = ConfigYesNo(default=False)  # NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.txtapi = ConfigText(default=tmdb_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.data2 = NoSave(ConfigOnOff(default=False))
config.plugins.xDreamy.api2 = ConfigYesNo(default=False)  # NoSave(ConfigSelection(['-> Ok']))
config.plugins.xDreamy.txtapi2 = ConfigText(default=omdb_api, visible_width=50, fixed_size=False)
config.plugins.xDreamy.bootlogos = ConfigOnOff(default=False)

config.plugins.xDreamy.colorSelector = ConfigSelection(default='head', choices=[
    ('head', _('Default')),
    ('color1_Blue', _('Blue')),
    ('color2_Brown', _('Brown')),
    ('color3_Green', _('Green')),
    ('color4_Grey', _('Grey')),
    ('color5_Maroon', _('Maroon')),
    ('color6_Orange', _('Orange')),
    ('color7_Pink', _('Pink')),
    ('color8_Purple', _('Purple')),
    ('color9_Teal', _('Teal')),
    ('color10_Gold', _('Gold')),
    ('color11_Red', _('Red'))])
config.plugins.xDreamy.FontStyle = ConfigSelection(default='basic', choices=[
    ('basic', _('Default')),
    ('font1', _('Andalus')),
    ('font2', _('Beiruti')),
    ('font3', _('BonaNovaSC')),
    ('font4', _('Dubai')),
    ('font5', _('ElMessiri')),
    ('font6', _('Fustat')),
    ('font7', _('Lucida')),
    ('font8', _('Majalla')),
    ('font9', _('MV Boli')),
    ('font10', _('Nask')),
    ('font11', _('PlexSans')),
    ('font12', _('ReadexPro')),
    ('font13', _('Rubik')),
    ('font14', _('Tajawal')),
    ('font15', _('Zain')),
    ('font16', _('Nmsbd'))])
config.plugins.xDreamy.skinSelector = ConfigSelection(default='base', choices=[
    ('base', _('Default')),
    ('base1', _('Style2')),
    ('base2', _('Style3')),
    ('base3', _('Style4')),
    ('base4', _('Style5')),
    ('base5', _('Style6'))])
config.plugins.xDreamy.KeysStyle = ConfigSelection(default='keys', choices=[
    ('keys', _('Default')),
    ('keys1', _('Keys1')),
    ('keys2', _('Keys2')),
    ('keys3', _('Keys3')),
    ('keys4', _('Keys4')),
    ('keys5', _('Keys5')),
    ('keys6', _('Keys6'))])
config.plugins.xDreamy.InfobarStyle = ConfigSelection(default='InfoBar-1P', choices=[
    ('InfoBar-1P', _('Default')),
    ('InfoBar-2P', _('InfoBar1-2P')),
    ('InfoBar-NP', _('InfoBar1-NP')),
    ('InfoBar2-NP', _('InfoBar2-NP')),
    ('InfoBar2-1P', _('InfoBar2-1P')),
    ('InfoBar2-2P', _('InfoBar2-2P')),
    ('InfoBar2-1PW', _('InfoBar2-1PW')),
    ('InfoBar3-F1', _('InfoBar3-F1')),
    ('InfoBar3-F2', _('InfoBar3-F2')),
    ('InfoBar3-F3', _('InfoBar3-F3'))])
config.plugins.xDreamy.SecondInfobarStyle = ConfigSelection(default='SecondInfobar-2P', choices=[
    ('SecondInfobar-2P', _('Default')),
    ('SecondInfobar-NP', _('SecondInfobar-NP')),
    ('SecondInfobar-2PN', _('SecondInfobar-2PN')),
    ('SecondInfobar-2PN2', _('SecondInfobar-2PN2'))])
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
config.plugins.xDreamy.EventView = ConfigSelection(default='EventView', choices=[
    ('EventView', _('Default')),
    ('EventView1', _('EventV-01 BD')),
    ('EventView2', _('EventV-02 Big ')),
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
    ('VirtualKeyBoardor', _('V.Keyboardor')),
    ('VirtualKeyBoard1', _('V.Keyboard1')),
    ('VirtualKeyBoard2', _('V.Keyboard2'))])
config.plugins.xDreamy.NewVirtualKeyboard = ConfigSelection(default='NewVirtualKeyBoard', choices=[
    ('NewVirtualKeyBoard', _('Default')),
    ('NewVirtualKeyBoard1', _('NV.KeyBoard1')),
    ('NewVirtualKeyBoard2', _('NV.KeyBoard2')),
    ('NewVirtualKeyBoard3', _('NV.KeyBoard3')),
    ('NewVirtualKeyBoard4', _('NV.KeyBoard4'))])
config.plugins.xDreamy.HistoryZapSelector = ConfigSelection(default='HistoryZapSelector', choices=[
    ('HistoryZapSelector', _('Default')),
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
config.plugins.xDreamy.ChannelListBackground = ConfigSelection(default='Background', choices=[
    ('Background', _('Default')),
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
    ('Background15', _('Background15'))])
config.plugins.xDreamy.TurnOff = ConfigSelection(default='Background', choices=[
    ('Background', _('Default')),
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
    ('Background15', _('Background15'))])
config.plugins.xDreamy.WeatherSource = ConfigSelection(default='OAWeatherPlugin', choices=[
    ('OAWeatherPlugin', _('Default-OAWeatherPlugin')),
    ('MSNWeatherPlugin', _('MSNWeatherPlugin'))])
config.plugins.xDreamy.BitrateSource = ConfigSelection(default='BitrateRenderer', choices=[
    ('BitrateRenderer', _('Default-BitrateRenderer')),
    ('BitratePlugin', _('Bitrate Plugin'))])
config.plugins.xDreamy.SubtitlesClock = ConfigSelection(default='SC', choices=[
    ('SC', _('Default')),
    ('SC1', _('DSC-BR')),
    ('SC2', _('DSC-BL')),
    ('SC3', _('DSC-TR')),
    ('SC4', _('DSC-TL'))])
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
    ("CLC", _("Default")),
    ("CLC1", _("Skin Color"))])
config.plugins.xDreamy.menufontcolor = ConfigSelection(default='MC', choices=[
    ('MC', _('Default')),
    ('MC1', _('Skin Color'))])

def autostart(reason, **kwargs):
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


def Plugins(**kwargs):
    return [PluginDescriptor(
            name=_("XDREAMY"),
            description=_('Customization tool for XDREAMY Skin'),
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon='plugin.png',
            fnc=main),

            PluginDescriptor(
            name=_("XDREAMY BOOT"),
            description="XDREAMY BOOT LOGO",
            where=PluginDescriptor.WHERE_AUTOSTART,
            fnc=autostart)]
    # return PluginDescriptor(name='XDREAMY', description=_('Customization tool for XDREAMY Skin'), where=PluginDescriptor.WHERE_PLUGINMENU, icon='plugin.png', fnc=main)


def main(session, **kwargs):
    session.open(xDreamySetup)


def remove_exif(image_path):
    with Image.open(image_path) as img:
        img.save(image_path, "PNG")


def convert_image(image):
    path = image
    # remove_exif(path)
    img = Image.open(path)
    img.save(path, "PNG")
    return image


class xDreamySetup(ConfigListScreen, Screen):
    skin = '''<screen name="xDreamySetup" position="center,center" size="1000,640" title="XDREAMY skin customization plugin">
    <eLabel font="Regular; 24" foregroundColor="#00ff4A3C" halign="center" position="20,598" size="120,26" text="Cancel"/>
    <eLabel font="Regular; 24" foregroundColor="#0056C856" halign="center" position="220,598" size="120,26" text="Save"/>
    <widget name="Preview" position="997,690" size="498, 280" zPosition="1"/>
    <widget name="config" font="Regular; 24" itemHeight="40" position="5,5" scrollbarMode="showOnDemand" size="990,550"/>
    <widget name="city" font="Regular; 26" position="564,571" size="420,60" foregroundColor="#00ff4A3C" backgroundColor="#000000" transparent="1" zPosition="4" halign="center" valign="bottom"/>
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
        self.setup_title = f"XDREAMY Setup  v {version}" 
        list = []
        section = '--------------------------( SKIN GENERAL SETUP )-----------------------'
        list.append(getConfigListEntry(section))
        section = '--------------------------( SKIN APIKEY SETUP )-----------------------'
        list.append(getConfigListEntry(section))
        ConfigListScreen.__init__(self, list, session=self.session, on_change=self.changedEntry)
        self.onChangedEntry = []
        self.createSetup()
        self['actions'] = ActionMap(['OkCancelActions',
                                     'DirectionActions',
                                     # 'InputBoxActions',
                                     'InputActions',
                                     'VirtualKeyboardActions',
                                     # 'EPGSelectActions',
                                     'MenuActions',
                                     'NumberActions',
                                     # # 'HelpActions',
                                     'InfoActions',
                                     # 'HotkeyActions',
                                     'ColorActions'], {'showVirtualKeyboard': self.KeyText,
                                                       'left': self.keyLeft,
                                                       'right': self.keyRight,
                                                       'down': self.keyDown,
                                                       'up': self.keyUp,
                                                       'red': self.keyExit,
                                                       'green': self.keySave,
                                                       'menu': self.Checkskin,
                                                       'yellow': self.checkforUpdate,
                                                       'info': self.mesInfo,
                                                       'blue': self.info,
                                                       #'5': self.Checkskin,
                                                       'cancel': self.keyExit,
                                                       'ok': self.keyRun}, -1)
        '''
        self.PicLoad = ePicLoad()
        self.Scale = AVSwitch().getFramebufferScale()
        try:
            self.PicLoad.PictureData.get().append(self.DecodePicture)
        except:
            self.PicLoad_conn = self.PicLoad.PictureData.connect(self.DecodePicture)
        '''
        self.timerx = eTimer()
        if fileExists('/var/lib/dpkg/status'):
            self.timerx_conn = self.timerx.timeout.connect(self.checkforUpdate)
        else:
            self.timerx.callback.append(self.checkforUpdate)
        self.timerx.start(5000, True)
        # self.onLayoutFinish.append(self.UpdatePicture)
        self.onLayoutFinish.append(self.ShowPicture)
        self.onLayoutFinish.append(self.__layoutFinished)

    def __layoutFinished(self):
        self['city'].setText("%s" % str(config.plugins.xDreamy.city.value))
        self.setTitle(self.setup_title) 

    def mesInfo(self):
        message = (
            "Experience Enigma2 skin like never before with XDREAMY\n\n"
            "XDREAMY skin is a new vision, created by Inspiron.\n"
            "Users can fully customize their interface, and change layout,\n"
            "colors, fonts, and screens to suit their preferences.\n"
            "Drawing inspiration from Dreamy and oDreamy skins,\n"
            "XDREAMY incorporates cutting-edge rendering technology,\n"
            "including the efficient PosterX component recoded by Lululla.\n\n"
            "Supported Images\n"
            "-----------------\n"
            "Egami, OpenATV, OpenSpa, PurE2, OpenDroid, OpenBH & Alliance Based Images.\n"
            "OpenPLi, OpenVIX, OpenHDF, OpenTR, Satlodge, NonSoloSat, & PLi Base Images.\n\n"
            "Forum support: Linuxsat-support.com\n"
            "Mahmoud Hussein"
        )
        self.session.open(MessageBox, _(message), MessageBox.TYPE_INFO, timeout=10)

    def keyRun(self):
        sel = self["config"].getCurrent()[1]
        if sel and sel == config.plugins.xDreamy.png:
            config.plugins.xDreamy.png.setValue(0)
            config.plugins.xDreamy.png.save()
            self.removPng()
        if sel and sel == config.plugins.xDreamy.weather:
            self.KeyMenu()
        if sel and sel == config.plugins.xDreamy.oaweather:
            self.KeyMenu2()
        if sel and sel == config.plugins.xDreamy.city:
            self.KeyText()
        if sel and sel == config.plugins.xDreamy.api:
            self.keyApi()
        if sel and sel == config.plugins.xDreamy.txtapi:
            self.KeyText()
        if sel and sel == config.plugins.xDreamy.api2:
            self.keyApi2()
        if sel and sel == config.plugins.xDreamy.txtapi2:
            self.KeyText()

    def keyApi(self, answer=None):
        api = "/tmp/apikey.txt"
        if answer is None:
            if fileExists(api) and os.stat(api).st_size > 0:
                self.session.openWithCallback(self.keyApi, MessageBox, _("Import Api Key TMDB from /tmp/apikey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing %s !") % api), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api) and os.stat(api).st_size > 0:
                with open(api, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(tmdb_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi.setValue(fpage)
                    config.plugins.xDreamy.txtapi.save()
                    self.session.open(MessageBox, _("TMDB ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("TMDB ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing %s !") % api), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def keyApi2(self, answer=None):
        api2 = "/tmp/omdbkey.txt"
        if answer is None:
            if fileExists(api2) and os.stat(api2).st_size > 0:
                self.session.openWithCallback(self.keyApi2, MessageBox, _("Import Api Key OMDB from /tmp/omdbkey.txt?"))
            else:
                self.session.open(MessageBox, (_("Missing %s !") % api2), MessageBox.TYPE_INFO, timeout=4)
        elif answer:
            if fileExists(api2) and os.stat(api2).st_size > 0:
                with open(api2, 'r') as f:
                    fpage = f.readline().strip()
                if fpage:
                    with open(omdb_skin, "w") as t:
                        t.write(fpage)
                    config.plugins.xDreamy.txtapi2.setValue(fpage)
                    config.plugins.xDreamy.txtapi2.save()
                    self.session.open(MessageBox, _("OMDB ApiKey Imported & Stored!"), MessageBox.TYPE_INFO, timeout=4)
                else:
                    self.session.open(MessageBox, _("OMDB ApiKey is empty!"), MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(MessageBox, (_("Missing %s !") % api2), MessageBox.TYPE_INFO, timeout=4)
        self.createSetup()

    def KeyText(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        sel = self["config"].getCurrent()
        if sel:
            self.session.openWithCallback(self.VirtualKeyBoardCallback, VirtualKeyBoard, title=self["config"].getCurrent()[0], text=self["config"].getCurrent()[1].value)

    def VirtualKeyBoardCallback(self, callback=None):
        if callback is not None and len(callback):
            self["config"].getCurrent()[1].value = callback
            self["config"].invalidate(self["config"].getCurrent())
        return

    def createSetup(self):
        try:
            self.editListEntry = None
            list = []
            section = '\\c00289496' + _('-------------------------------( SKIN GENERAL SETUP )---------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('General Skin Style:'), config.plugins.xDreamy.skinSelector))
            list.append(getConfigListEntry(_('Skin Font Style:'), config.plugins.xDreamy.FontStyle))
            list.append(getConfigListEntry(_('Skin Keys Style:'), config.plugins.xDreamy.KeysStyle))
            list.append(getConfigListEntry(_('Remove all png (OK)'), config.plugins.xDreamy.png))
            section = '\\c00289496' + _('--------------------------------( SKIN COLORS SETUP )---------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Skin Color Style:'), config.plugins.xDreamy.colorSelector))
            list.append(getConfigListEntry(_('Menu Font Color:'), config.plugins.xDreamy.menufontcolor))
            list.append(getConfigListEntry(_('Channel Names Color:'), config.plugins.xDreamy.channelnamecolor))
            section = '\\c00289496' + _('--------------------------------( SKIN BASIC SCREENS )--------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('InfoBar Style:'), config.plugins.xDreamy.InfobarStyle))
            list.append(getConfigListEntry(_('SecondInfobar Style:'), config.plugins.xDreamy.SecondInfobarStyle))
            list.append(getConfigListEntry(_('Channels List Style:'), config.plugins.xDreamy.ChannSelector))
            list.append(getConfigListEntry(_('EventView Style:'), config.plugins.xDreamy.EventView))
            list.append(getConfigListEntry(_('Volume Bar Style:'), config.plugins.xDreamy.VolumeBar))
            list.append(getConfigListEntry(_('Plugin Browser Style:'), config.plugins.xDreamy.PluginBrowser))
            list.append(getConfigListEntry(_('Virtual Keyboard Style:'), config.plugins.xDreamy.VirtualKeyboard))
            list.append(getConfigListEntry(_('History Zap Selector Style:'), config.plugins.xDreamy.HistoryZapSelector))
            section = '\\c00289496' + _('------------------------------( USER PLUGINS SCREENS )-------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('New Virtual Keyboard Style:'), config.plugins.xDreamy.NewVirtualKeyboard))
            list.append(getConfigListEntry(_('EPG MultiSelection Style:'), config.plugins.xDreamy.EPGMultiSelection))
            list.append(getConfigListEntry(_('E2Player Style:'), config.plugins.xDreamy.E2Player))
            list.append(getConfigListEntry(_('Enhanced Movie Center Style:'), config.plugins.xDreamy.EnhancedMovieCenter))
            section = '\\c00289496' + _('---------------------------------( USER BACKGROUND )---------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Channels List Background Style:'), config.plugins.xDreamy.ChannelListBackground))
            list.append(getConfigListEntry(_('ShutDown Style:'), config.plugins.xDreamy.TurnOff))
            list.append(getConfigListEntry(_('Bootlogos Random:'), config.plugins.xDreamy.bootlogos))
            section = '\\c00289496' + _('---------------------------------( USER DATA SOURCE )--------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Bitrate Source:'), config.plugins.xDreamy.BitrateSource))
            list.append(getConfigListEntry(_('Rating & Stars:'), config.plugins.xDreamy.RatingStars))
            list.append(getConfigListEntry(_('Subtitles Clock:'), config.plugins.xDreamy.SubtitlesClock))
            list.append(getConfigListEntry(_('Cam Name:'), config.plugins.xDreamy.CamName))
            section = '\\c00289496' + _('--------------------------------( WEATHER DATA SOURCE )-------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry(_('Weather Source:'), config.plugins.xDreamy.WeatherSource))
            list.append(getConfigListEntry("Install or Open OAWeather Plugin", config.plugins.xDreamy.oaweather))
            list.append(getConfigListEntry("Install or Open MsnWeather Plugin", config.plugins.xDreamy.weather))
            if os.path.isdir(weatherz):
                list.append(getConfigListEntry("--Setting Weather City", config.plugins.xDreamy.city))

            section = '\\c00289496' + _('-------------------------------( SERVER API KEY SETUP )-------------------------')
            list.append(getConfigListEntry(section))
            list.append(getConfigListEntry("API KEY SETUP:", config.plugins.xDreamy.actapi, _("Settings Apikey Server")))
            if config.plugins.xDreamy.actapi.value is True:
                list.append(getConfigListEntry("TMDB API:", config.plugins.xDreamy.data, _("Settings TMDB ApiKey")))
                if config.plugins.xDreamy.data.value is True:
                    list.append(getConfigListEntry("--Load TMDB Apikey", config.plugins.xDreamy.api, _("Load TMDB Apikey from /tmp/apikey.txt")))
                    list.append(getConfigListEntry("--Set TMDB Apikey", config.plugins.xDreamy.txtapi, _("Signup on TMDB and input free personal ApiKey")))
                list.append(getConfigListEntry("OMDB API:", config.plugins.xDreamy.data2, _("Settings OMDB APIKEY")))
                if config.plugins.xDreamy.data2.value is True:
                    list.append(getConfigListEntry("--Load OMDB Apikey", config.plugins.xDreamy.api2, _("Load OMDB Apikey from /tmp/omdbkey.txt")))
                    list.append(getConfigListEntry("--Set OMDB Apikey", config.plugins.xDreamy.txtapi2, _("Signup on OMDB and input free personal ApiKey")))

            self["config"].list = list
            self["config"].l.setList(list)
            self.ShowPicture()
        except KeyError:
            print("keyError")

    def Checkskin(self):
        self.session.openWithCallback(self.Checkskin2,
                                      MessageBox, _("[Checkskin] This operation checks if the skin has its components (is not sure)..\nDo you really want to continue?"),
                                      MessageBox.TYPE_YESNO)

    def Checkskin2(self, answer):
        if answer:
            from .addons import checkskin
            self.check_module = eTimer()
            check = checkskin.check_module_skin()
            try:
                self.check_module_conn = self.check_module.timeout.connect(check)
            except:
                self.check_module.callback.append(check)
            self.check_module.start(100, True)
            self.openVi()

    def openVi(self, callback=''):
        from .addons.File_Commander import File_Commander
        user_log = '/tmp/my_debug.log'
        if fileExists(user_log):
            self.session.open(File_Commander, user_log)

    def GetPicturePath(self):
        currentConfig = self["config"].getCurrent()[0]
        returnValue = self['config'].getCurrent()[1].value
        PicturePath = '/usr/share/enigma2/xDreamy/screens/default.png'
        # OAWeatherpng = '/usr/share/enigma2/xDreamy/screens/OAWeatherPlugin.png'
        # MsnWeatherPng = '/usr/share/enigma2/xDreamy/screens/MSNWeatherPlugin.png'
        if not isinstance(returnValue, str):
            returnValue = PicturePath  # if fileExists(PicturePath) else ''
        # try:
        PicturePath = convert_image(PicturePath)
        c = ['setup', 'autoupdate', 'theweather', 'user', 'basic', 'weather source:']
        if currentConfig and currentConfig.lower().strip() in c:
            return PicturePath

        if 'oaweather' in currentConfig.lower().strip():
            return PicturePath  # OAWeatherpng
        if 'msnweather' in currentConfig.lower().strip():
            return PicturePath  # MsnWeatherPng
        path = '/usr/share/enigma2/xDreamy/screens/' + returnValue + '.png'
        if fileExists(path):
            return convert_image(path)
        else:
            return PicturePath

        # except Exception as e:
            # print('error GetPicturePath:', e)

    def UpdatePicture(self):
        self.onLayoutFinish.append(self.ShowPicture)

    def removPng(self):
        print('from remove png......')
        removePng()
        print('png are removed')
        aboutbox = self.session.open(MessageBox, _('All png are removed from folder!'), MessageBox.TYPE_INFO)
        aboutbox.setTitle(_('Info...'))

    def ShowPicture(self, data=None):
        if self["Preview"].instance:
            size = self['Preview'].instance.size()
            if size.isNull():
                size.setWidth(498)
                size.setHeight(280)
            pixmapx = self.GetPicturePath()
            if not fileExists(pixmapx):
                print("Immagine non trovata:", pixmapx)
                return
            png = loadPic(pixmapx, size.width(), size.height(), 0, 0, 0, 1)
            self["Preview"].instance.setPixmap(png)

    def DecodePicture(self, PicInfo=None):
        print('PicInfo=', PicInfo)
        if PicInfo is None:
            PicInfo = '/usr/share/enigma2/xDreamy/screens/default.png'
        ptr = self.PicLoad.getData()
        if ptr is not None:
            self["Preview"].instance.setPixmap(ptr)
            self["Preview"].instance.show()
        else:
            print("Dati dell'immagine non disponibili. Controlla l'immagine.")

    def info(self):
        aboutbox = self.session.open(MessageBox, _('Setup xDreamy for xDreamy v.%s') % version, MessageBox.TYPE_INFO)
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
        # self.ShowPicture()

    def keyDown(self):
        self['config'].instance.moveSelection(self['config'].instance.moveDown)
        self.createSetup()
        # self.ShowPicture()

    def keyUp(self):
        self['config'].instance.moveSelection(self['config'].instance.moveUp)
        self.createSetup()
        # self.ShowPicture()

    def changedEntry(self):
        self.item = self["config"].getCurrent()
        for x in self.onChangedEntry:
            x()
        try:
            if isinstance(self["config"].getCurrent()[1], ConfigOnOff) or isinstance(self["config"].getCurrent()[1], ConfigYesNo) or isinstance(self["config"].getCurrent()[1], ConfigSelection):
                self.createSetup()
        except Exception as e:
            print("Error in changedEntry:", e)

    def getCurrentValue(self):
        if self["config"].getCurrent() and len(self["config"].getCurrent()) > 0:
            return str(self["config"].getCurrent()[1].getText())
        return ""

    def getCurrentEntry(self):
        return self["config"].getCurrent() and self["config"].getCurrent()[0] or ""

    def createSummary(self):
        from Screens.Setup import SetupSummary
        return SetupSummary

    def keySave(self):
        if not fileExists(self.skinFile + self.version):
            for x in self['config'].list:
                x[1].cancel()
            self.close()
            return
        # if self["config"].isChanged():

        if config.plugins.xDreamy.bootlogos.value is True:
            if not fileExists(mvi + 'bootlogoBack.mvi'):
                shutil.copy(mvi + 'bootlogo.mvi', mvi + 'bootlogoBack.mvi')
        else:
            if fileExists(mvi + 'bootlogoBack.mvi'):
                shutil.copy(mvi + 'bootlogoBack.mvi', mvi + 'bootlogo.mvi')
                os.remove(mvi + 'bootlogoBack.mvi')

        try:
            for x in self['config'].list:
                if len(x) > 1:  # Check if x has at least two elements
                    x[1].save()
            config.plugins.xDreamy.save()
            configfile.save()
        except IndexError:
            print("Errore: x non ha abbastanza elementi.")
        try:
            skin_lines = []
            skin_file_paths = [
                f'head-{config.plugins.xDreamy.colorSelector.value}.xml',
                f'font-{config.plugins.xDreamy.FontStyle.value}.xml',
                f'keys-{config.plugins.xDreamy.KeysStyle.value}.xml',
                f'infobar-{config.plugins.xDreamy.InfobarStyle.value}.xml',
                f'secondinfobar-{config.plugins.xDreamy.SecondInfobarStyle.value}.xml',
                f'CHL-{config.plugins.xDreamy.ChannSelector.value}.xml',
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
                f'CC-{config.plugins.xDreamy.channelnamecolor.value}.xml',
                f'CA-{config.plugins.xDreamy.CamName.value}.xml'
            ]

            for file_name in skin_file_paths:
                file_path = os.path.join(self.previewFiles, file_name)
                if os.path.isfile(file_path):
                    with open(file_path, 'r') as skFile:
                        skin_lines.extend(skFile.readlines())

            base_file_name = 'base.xml'
            if config.plugins.xDreamy.skinSelector.value in ['base1', 'base2', 'base3', 'base4', 'base5']:
                base_file_name = f'base{config.plugins.xDreamy.skinSelector.value[-1]}.xml'

            base_file_path = os.path.join(self.previewFiles, base_file_name)
            if os.path.isfile(base_file_path):
                with open(base_file_path, 'r') as skFile:
                    skin_lines.extend(skFile.readlines())

            with open(self.skinFile, 'w') as xFile:
                xFile.writelines(skin_lines)

            self.session.openWithCallback(self.restartGUI, MessageBox, _('GUI needs a restart to apply a new skin.\nDo you want to Restart the GUI now?'), MessageBox.TYPE_YESNO)

        except Exception as e:
            self.session.open(MessageBox, _('Error by processing the skin file !!!') + str(e), MessageBox.TYPE_ERROR)

    def restartGUI(self, answer):
        if answer is True:
            self.session.open(TryQuitMainloop, 3)
        else:
            self.close()

    def checkforUpdate(self):
        try:
            fp = ''
            destr = '/tmp/xDreamyv.txt'
            req = Request('https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamyv.txt')
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
            fp = urlopen(req)
            fp = fp.read().decode('utf-8')
            print('fp read:', fp)
            with open(destr, 'w') as f:
                f.write(str(fp))  # .decode("utf-8"))
                f.seek(0)
            if fileExists(destr):
                with open(destr, 'r') as cc:
                    s1 = cc.readline()  # .decode("utf-8")
                    vers = s1.split('#')[0]
                    url = s1.split('#')[1]
                    version_server = vers.strip()
                    self.updateurl = url.strip()
                    cc.close()
                    if str(version_server) == str(version):
                        message = '%s %s\n%s %s\n\n%s' % (_('Server version:'),
                                                          version_server,
                                                          _('Version installed:'),
                                                          version,
                                                          _('Congratulation, You have the last version of XDREAMY!'))
                    elif version_server > version:
                        message = '%s %s\n%s %s\n\n%s' % (_('Server version:'),
                                                          version_server,
                                                          _('Version installed:'),
                                                          version,
                                                          _('The update is available!\n\nDo you want to run the update now?'))
                        self.session.openWithCallback(self.update, MessageBox, message, MessageBox.TYPE_YESNO)
                    else:
                        self.session.open(MessageBox, _('You have version %s!!!') % version, MessageBox.TYPE_INFO, timeout=10)
        except Exception as e:
            print('error: ', str(e))

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
            except:
                pass

    def goWeatherInstall(self, result=False):
        if result:
            try:
                cmd = 'enigma2-plugin-extensions-weatherplugin'
                self.session.open(Console, _('Install WeatherPlugin'), ['opkg install %s' % cmd], closeOnSuccess=False)
                time.sleep(5)
            except Exception as e:
                print(e)
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
                print('i am here!!')
                self.session.openWithCallback(self.UpdateComponents2, WeatherSettingsView)
            except:
                print('passed!!')
                pass

    def goOAWeatherInstall(self, result=False):
        if result:
            try:
                cmd = 'enigma2-plugin-extensions-oaweather'
                self.session.open(Console, _('Install OAWeatherPlugin'), ['opkg install %s' % cmd], closeOnSuccess=False)
                time.sleep(5)
            except Exception as e:
                print(e)
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
        except:
            pass

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
        except:
            pass

class xDreamyUpdater(Screen):

    def __init__(self, session, updateurl):
        self.session = session
        skin = '''
                <screen name="xDreamyUpdater" position="center,center" size="840,260" flags="wfBorder" backgroundColor="background">
    <widget name="status" position="20,10" size="800,70" transparent="1" font="Regular; 40" foregroundColor="foreground" backgroundColor="background" valign="center" halign="left" noWrap="1"/>
    <widget source="progress" render="Progress" position="20,120" size="800,20" transparent="1" borderWidth="0" foregroundColor="white" backgroundColor="background"/>
    <widget source="progresstext" render="Label" position="209,164" zPosition="2" font="Regular; 28" halign="center" transparent="1" size="400,70" foregroundColor="foreground" backgroundColor="background"/>
</screen>
                '''
        self.skin = skin
        Screen.__init__(self, session)
        self.updateurl = updateurl
        print('self.updateurl', self.updateurl)
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
        print('self.dlfile', self.dlfile)
        self.download = downloadWithProgress(self.updateurl, self.dlfile)
        self.download.addProgress(self.downloadProgress)
        self.download.start().addCallback(self.downloadFinished).addErrback(self.downloadFailed)

    def downloadFinished(self, string=''):
        self['status'].setText(_('Installing updates please waite!'))
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
