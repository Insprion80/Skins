#!/bin/sh
# XDREAMY AiO - One-click Enigma2 Setup Script
# Version: 1.2 by M.Hussein
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
log "=============================================="
log "        XDREAMY AiO Enigma2 Setup Wizard"
log "    Universal One-Click Configuration Script"
log "=============================================="
log "Script Version: 1.2 by M.Hussein"
log "Started at: $(date)"
log ""
log "This script will:"
log " "
log " • Set static IP (auto-detect 192.168.x.10)"
log " • Set root password to 'root'"
log " • Detect location & timezone automatically"
log " • Sync time using NTP"
log " • Clean non-Ar/En languages"
log " • Remove unnecessary plugins (bloatware)"
log " • Update feeds + install key extensions"
log " • Install xDreamy, AJPanel, Transmission..."
log " • Set xDreamy as default skin + restart GUI"
log ""


echo "Press any key to skip script start (5s timeout)..."
trap '' ERR
read -t 5 -n 1 key
READ_RESULT=$?
trap 'log "[ERROR] Line $LINENO failed. Continuing..."' ERR
if [ "$READ_RESULT" = "0" ]; then
  log "⏩ Skipped by user input"
  exit 0
else
  log "⏱ No User Action. Starting script execution..."
fi

# === Basic Info ===
log ""
log "==> Detecting Basic System Info..."
IMAGE_NAME=$(grep -i 'distro' /etc/image-version 2>/dev/null | cut -d= -f2 | tr -d '\r\n')
[ -z "$IMAGE_NAME" ] && IMAGE_NAME=$(head -n1 /etc/issue 2>/dev/null | tr -d '\r\n')
[ -z "$IMAGE_NAME" ] && IMAGE_NAME="Unknown"

BOX_MODEL=$(cat /etc/hostname 2>/dev/null || echo "Unknown")
PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}' || echo "Unknown")
NET_IFACE=$(ip -o -4 route show to default | awk '{print $5}')
[ -z "$NET_IFACE" ] && NET_IFACE="eth0"

log "✔ Image     : $IMAGE_NAME"
log "✔ Box Model : $BOX_MODEL"
log "✔ Python    : $PYTHON_VERSION"
log "✔ Network   : $NET_IFACE"

# === Static IP ===
log ""
log "==> Setting static IP (192.168.X.10)"
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
log_done

# === Set Root Password ===
log ""
log "==> Setting root password to 'root'"
echo -e "root\nroot" | passwd root >/dev/null 2>&1 && log_done || log_fail

# === Language Cleanup ===
log ""
log "==> Cleaning up languages"
cd /usr/share/enigma2/po 2>/dev/null || true
for lang in *; do
  [ "$lang" = "en" ] || [ "$lang" = "ar" ] && continue
  rm -rf "$lang" && log "   Removed: $lang"
done
log "✔ Language cleanup done"

# === Bloatware Removal ===
log ""
log "==> Removing bloatware"
BLOAT_PACKAGES="
enigma2-plugin-extensions-atilehd
enigma2-plugin-extensions-dvdplayer
enigma2-plugin-extensions-mediaplayer
enigma2-plugin-extensions-pictureplayer
enigma2-plugin-systemplugins-hotplug
enigma2-plugin-systemplugins-multitranscodingsetup
"
for pkg in $BLOAT_PACKAGES; do
  log_action "$pkg"
  opkg remove --force-depends "$pkg" >/dev/null 2>&1 && log_done || log_skip
done

# === Feed Update & Dependencies ===
log ""
log "==> Updating feeds and installing extensions"
opkg update >/dev/null 2>&1 && log "   • Feed update ......... [ ✔ ]"
opkg upgrade >/dev/null 2>&1 && log "   • Feed upgrade ........ [ ✔ ]"

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

# === Timezone & Time Sync ===
log ""
log "==> Detecting location and syncing time"
CITY=$(curl -s https://ipapi.co/city/)
TIMEZONE=$(curl -s https://ipapi.co/timezone/)
log "✔ Location  : $CITY"
log "✔ Timezone  : $TIMEZONE"

if [ -n "$TIMEZONE" ]; then
  echo "$TIMEZONE" > /etc/timezone
  log "✔ Timezone saved to /etc/timezone"
fi

log_action "Stopping any NTP service"
/etc/init.d/ntpd stop >/dev/null 2>&1 && sleep 1

log_action "Syncing time via pool.ntp.org"
ntpd -q -p pool.ntp.org >/dev/null 2>&1 && log_done || log_skip

log_action "Restarting NTP service"
/etc/init.d/ntpd start >/dev/null 2>&1 && log_done || log_skip

# === 3rd-Party Plugin Installation ===
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

# === Apply Skin ===
log ""
log "==> Applying xDreamy as default skin"
SKIN_CFG="/etc/enigma2/settings"
SKIN_PATH="xDreamy/skin.xml"

log_action "Stopping Enigma2"
init 4 && sleep 4 && log_done || log_fail

cp "$SKIN_CFG" "${SKIN_CFG}.bak"
sed -i '/^config.skin.primary_skin=/d' "$SKIN_CFG"
echo "config.skin.primary_skin=$SKIN_PATH" >> "$SKIN_CFG"
log "✔ Skin set to $SKIN_PATH"

log_action "Starting Enigma2"
init 3 && log_done || log_fail

# === Done ===
log ""
log "✔ All tasks complete."
log "✔ Full log: $LOGFILE"
log "🎉 XDREAMY AiO setup finished!"

exit 0