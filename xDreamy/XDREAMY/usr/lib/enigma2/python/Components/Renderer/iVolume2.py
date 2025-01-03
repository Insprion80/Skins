from Components.Renderer.Renderer import Renderer
from enigma import ePixmap, eTimer, eDVBVolumecontrol

class iVolume2(Renderer):

    def __init__(self):
        Renderer.__init__(self)
        self.vol_timer = eTimer()
        self.vol_timer.callback.append(self.pollme)
    GUI_WIDGET = ePixmap

    def changed(self, what):
        if not self.suspended:
            value = str(eDVBVolumecontrol.getInstance().getVolume())
            self.instance.setPixmapFromFile('/usr/share/enigma2/oDreamy-FHD/skin_default/volume/' + value + '.png')

    def pollme(self):
        self.changed(None)
        return

    def onShow(self):
        self.suspended = False
        self.vol_timer.start(200)

    def onHide(self):
        self.suspended = True
        self.vol_timer.stop()
