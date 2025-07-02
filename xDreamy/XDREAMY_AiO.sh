#!/bin/sh
# XDREAMY AiO - One-click Enigma2 Setup Script
# Version: 1.3 by M.Hussein
LOGFILE="/tmp/XDREAMY_AiO.log"

log() {
  printf "%s\n" "$*" | tee -a "$LOGFILE"
}

log_action() {
  printf "    • %-45s" "$1" | tee -a "$LOGFILE"
}

log_done() {
  echo " [ ✔ ]" | tee -a "$LOGFILE"
}

log_skip() {
  echo " [ skipped ]" | tee -a "$LOGFILE"
}

log_fail() {
  echo " [ ✖ ]" | tee -a "$LOGFILE"
}

trap 'log "[ERROR] Line $LINENO failed. Continuing..."' ERR

printf "\n\n"
log "==========================================================="
log "      ★ XDREAMY AiO - Enigma2 Universal Setup Wizard ★"
log "           Version 1.2 - Developed by M.Hussein"
log "==========================================================="
log "Started at: $(date)"
log ""
log "What this script does:"
log ""
log " 🔌 Network Configuration:"
log "    • Automatically detect LAN subnet (192.168.X.10)"
log "    • Set static IP and dual DNS (8.8.8.8, 9.9.9.9)"
log "    • Set root user password to 'root'"
log ""
log " 🌍 System Localization:"
log "    • Detect your city & timezone via IP lookup"
log "    • Sync accurate time via NTP"
log "    • Force OSD language to English (en_EN)"
log "    • Keep local language + Arabic + English only"
log ""
log " 🔧 System Optimization:"
log "    • Remove unnecessary pre-installed plugins"
log "    • Clean up unused locale files"
log ""
log " 📦 Plugin & Skin Installer:"
log "    • Update feed and install important tools"
log "    • Install xDreamy skin, AJPanel, Transmission, etc."
log "    • Apply xDreamy as default Enigma2 skin"
log ""
log "🗂 Log saved to: /tmp/XDREAMY_AiO.log"
log ""

COUNTDOWN=10
echo "You have $COUNTDOWN seconds to cancel (press any key)..."
trap '' ERR
while [ $COUNTDOWN -gt 0 ]; do
  printf "\rStarting in %2d seconds... Press any key to abort." $COUNTDOWN
  read -t 1 -n 1 key && break
  COUNTDOWN=$((COUNTDOWN - 1))
done
trap 'log "[ERROR] Line $LINENO failed. Continuing..."' ERR

if [ -n "$key" ]; then
log ""
log "⏩ Skipped by user input"
  exit 0
else
  log "\n⏱ No User Action. Starting script execution..."
fi

# === Basic Info ===
log ""
log "==> Detecting Basic System Info..."
IMAGE_NAME="Unknown"
[ -f /etc/image-version ] && IMAGE_NAME=$(grep -i 'distro' /etc/image-version | cut -d= -f2 | tr -d '
')
[ "$IMAGE_NAME" = "Unknown" ] && [ -f /etc/issue ] && IMAGE_NAME=$(head -n 1 /etc/issue | tr -d '
')
BOX_MODEL="Unknown"
[ -f /etc/hostname ] && BOX_MODEL=$(cat /etc/hostname)
PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}')
NET_IFACE=$(ip -o -4 route show to default | awk '{print $5}')
[ -z "$NET_IFACE" ] && NET_IFACE="eth0"
log "✔ Image            : $IMAGE_NAME"
log "✔ Box Model        : $BOX_MODEL"
log "✔ Python           : $PYTHON_VERSION"
log "✔ Network          : $NET_IFACE"

COUNTRY_LANG=$(curl -s https://ipapi.co/languages/ | cut -d, -f1 | cut -c1-2)
[ -z "$COUNTRY_LANG" ] && COUNTRY_LANG="en"
log "✔ Local language   : $COUNTRY_LANG"

# === Network and Password ===
log ""
log "==> Setting Network IP and Account Password..."
IP_PREFIX=$(ip addr | grep 'inet 192.168' | awk '{print $2}' | cut -d. -f1-3 | head -n1)
[ -z "$IP_PREFIX" ] && IP_PREFIX="192.168.1"
cp /etc/network/interfaces /etc/network/interfaces.bak 2>/dev/null
cat > /etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto $NET_IFACE
iface $NET_IFACE inet static
    address $IP_PREFIX.10
    netmask 255.255.255.0
    gateway $IP_PREFIX.1
    dns-nameservers 8.8.8.8 9.9.9.9
EOF
log_action "Setting static IP ($IP_PREFIX.10)"; /etc/init.d/networking restart >/dev/null 2>&1 && log_done || log_fail
log_action "Setting root password to 'root'"; echo -e "root
root" | passwd root >/dev/null 2>&1 && log_done || log_fail

# === Locale & Language ===
log ""
log "==> Cleaning locale files (only keep en, ar, $COUNTRY_LANG)..."
cd /usr/share/enigma2/po 2>/dev/null || true
for lang in *; do
  [ "$lang" = "en" ] || [ "$lang" = "ar" ] || [ "$lang" = "$COUNTRY_LANG" ] && continue
  rm -rf "$lang" && log "      Removed from po/: $lang"
done

for folder in /usr/share/locale/*; do
  base=$(basename "$folder")
  case "$base" in
    en|en_*|ar|ar_*|$COUNTRY_LANG|${COUNTRY_LANG}_*) ;;
    *) rm -rf "$folder" && log "      Removed from locale/: $base" ;;
  esac
done

[ -d /usr/share/locale-langpack ] && find /usr/share/locale-langpack -mindepth 1 -maxdepth 1 ! -name 'en*' ! -name 'ar*' ! -name "$COUNTRY_LANG" -exec rm -rf {} \;
log "✔ Locale cleanup done"
log_action "Set default language to English"
sed -i '/^config.osd.language=/d' /etc/enigma2/settings
echo "config.osd.language=en_EN" >> /etc/enigma2/settings && log_done || log_fail

# === Timezone & NTP ===
log ""
log "==> Detect Geolocation and Timezone..."
CITY=$(curl -s https://ipapi.co/city/)
TIMEZONE=$(curl -s https://ipapi.co/timezone/)
log "✔ Location  : $CITY"
log "✔ Timezone  : $TIMEZONE"
if [ -n "$TIMEZONE" ]; then
  echo "$TIMEZONE" > /etc/timezone
  log "✔ Timezone saved to /etc/timezone"
  log_action "Stopping any NTP service"; /etc/init.d/ntpd stop >/dev/null 2>&1 && log_done || log_skip
  log_action "Syncing time via pool.ntp.org"; ntpd -q -p pool.ntp.org >/dev/null 2>&1 && log_done || log_skip
  log_action "Restarting NTP service"; /etc/init.d/ntpd start >/dev/null 2>&1 && log_done || log_skip
fi

# === Bloatware ===
log ""
log "==> Removing bloatware...."
BLOAT_PACKAGES="
enigma2-plugin-extensions-atilehd
enigma2-plugin-extensions-dvdplayer
enigma2-plugin-extensions-mediaplayer
enigma2-plugin-extensions-pictureplayer
enigma2-plugin-extensions-mediascanner
enigma2-plugin-systemplugins-cablescan
enigma2-plugin-systemplugins-hotplug
enigma2-plugin-systemplugins-moviecut
enigma2-plugin-systemplugins-cutlisteditor
enigma2-plugin-systemplugins-audiosync
enigma2-plugin-systemplugins-multitranscodingsetup
enigma2-plugin-systemplugins-satfinder
enigma2-plugin-systemplugins-crashlogautosubmit
enigma2-plugin-systemplugins-frontprocessorupgrade
enigma2-plugin-systemplugins-networkwizard
enigma2-plugin-systemplugins-satipclient
enigma2-plugin-systemplugins-videomode
enigma2-plugin-systemplugins-videotune
enigma2-plugin-systemplugins-mphelp
enigma2-plugin-systemplugins-videoenhancement"

for pkg in $BLOAT_PACKAGES; do
  log_action "$pkg"
  opkg remove --force-depends "$pkg" >/dev/null 2>&1 && log_done || log_skip
  sleep 0.2
# Optional: remove sleep if you want faster execution
  done

# === Feed Update ===
log ""
log "==> Updating Feeds and Upgrade...."
opkg update >/dev/null 2>&1 && log_action "Feeds Update" && log_done || log_fail
opkg upgrade >/dev/null 2>&1 && log_action "Feeds Upgrade" && log_done || log_fail

# === Install Extensions ===
log ""
log "==> Installing  Dependencies and Extensions...."
EXT_PACKAGES="
xz
curl
wget
ntpd
transmission
transmission-client
python3-transmission-rpc
python3-beautifulsoup4
enigma2-plugin-extensions-tmdb
enigma2-plugin-extensions-cacheflush
enigma2-plugin-extensions-epgtranslator
enigma2-plugin-systemplugins-serviceapp
"
for pkg in $EXT_PACKAGES; do
  log_action "$pkg"
  opkg install "$pkg" >/dev/null 2>&1 && log_done || log_skip
done

# === 3rd-Party Plugins ===
log ""
log "==> Installing 3rd-party plugins"
log_action "xDreamy Skin"
wget -q --no-check-certificate https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail
log_action "Transmission_e2"
wget -q --no-check-certificate http://dreambox4u.com/dreamarabia/Transmission_e2/Transmission_e2.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail
log_action "AJPanel"
wget -q --no-check-certificate https://raw.githubusercontent.com/AMAJamry/AJPanel/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail
log_action "SubSSupport"
wget -q --no-check-certificate https://github.com/popking159/ssupport/raw/main/subssupport-install.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail
log_action "Levi Manager"
wget -q --no-check-certificate https://raw.githubusercontent.com/levi-45/Manager/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail
log_action "Eliesatpanel"
wget -q "--no-check-certificate" https://raw.githubusercontent.com/eliesat/eliesatpanel/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

# === Skin Setup ===
log ""
log "==> Applying xDreamy as default skin"
SKIN_CFG="/etc/enigma2/settings"
SKIN_PATH="xDreamy/skin.xml"
log_action "Stopping Enigma2"
init 4 && sleep 4 && log_done || log_fail
cp "$SKIN_CFG" "${SKIN_CFG}.bak"
sed -i '/^config.skin.primary_skin=/d' "$SKIN_CFG"
echo "config.skin.primary_skin=$SKIN_PATH" >> "$SKIN_CFG"
log_action "Skin set to $SKIN_PATH"
log_done
log_action "Starting Enigma2"
init 3 && log_done || log_fail

# === Done ===
log ""
log "✔ All tasks complete."
log "✔ Full log: $LOGFILE"
log "🎉 XDREAMY AiO setup finished!"

exit 0
