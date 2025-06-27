#!/bin/sh

# XDREAMY AiO - One-click Enigma2 Setup Script
LOGFILE="/tmp/xdreamy_aio.log"

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
log "         XDREAMY AiO Setup Wizard"
log "     All-in-One Enigma2 Configuration Tool"
log "=============================================="
log "This script will:"
log " "
log " • Set static IP (192.168.1.10)"
log " • Set root password to 'root'"
log " • Remove non-Ar/En languages"
log " • Remove bloatware"
log " • Update feeds + install tools"
log " • Install xDreamy, AJPanel, etc."
log " • Apply skin + restart GUI"
log ""

echo "Press any key to skip script start (5s timeout)..."

# Temporarily disable trap to suppress harmless timeout error
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

log ""
log "==> Detecting Basic System Info..."

IMAGE_NAME="Unknown"
[ -f /etc/image-version ] && IMAGE_NAME=$(grep -i 'distro' /etc/image-version | cut -d= -f2 | tr -d '\r\n')
[ "$IMAGE_NAME" = "Unknown" ] && [ -f /etc/issue ] && IMAGE_NAME=$(head -n 1 /etc/issue | tr -d '\r\n')

BOX_MODEL="Unknown"
[ -f /etc/hostname ] && BOX_MODEL=$(cat /etc/hostname)

PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}')

log "✔ Image     : $IMAGE_NAME"
log "✔ Box Model : $BOX_MODEL"
log "✔ Python    : $PYTHON_VERSION"

# Static IP
log ""
log "==> Setting static IP 192.168.1.10"
cp /etc/network/interfaces /etc/network/interfaces.bak 2>/dev/null
cat > /etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address 192.168.1.10
    netmask 255.255.255.0
    gateway 192.168.1.1
    dns-nameservers 8.8.8.8
EOF
log_done

# Set root password
log ""
log "==> Setting root password to 'root'"
echo -e "root\nroot" | passwd root >/dev/null 2>&1 && log_done || log_fail

# Remove extra languages
log ""
log "==> Cleaning up languages"
cd /usr/share/enigma2/po 2>/dev/null || true
for lang in *; do
  [ "$lang" = "en" ] || [ "$lang" = "ar" ] && continue
  rm -rf "$lang" && log "   Removed: $lang"
done
log "✔ Language cleanup done"

# Remove bloatware
log ""
log "==> Removing bloatware"
BLOAT_PACKAGES="
enigma2-plugin-extensions-atilehd
enigma2-plugin-extensions-dvdplayer
enigma2-plugin-extensions-mediaplayer
enigma2-plugin-extensions-pictureplayer
enigma2-plugin-systemplugins-cablescan
enigma2-plugin-systemplugins-hotplug
enigma2-plugin-systemplugins-positionersetup
enigma2-plugin-systemplugins-multitranscodingsetup
"
for pkg in $BLOAT_PACKAGES; do
  log_action "$pkg"
  opkg remove --force-depends "$pkg" >/dev/null 2>&1 && log_done || log_skip
done

# Update feeds + install packages
log ""
log "==> Updating feeds and installing extensions"
opkg update >/dev/null 2>&1 && log "   • Feed update ......... done"
opkg upgrade >/dev/null 2>&1 && log "   • Feed upgrade ........ done"

EXT_PACKAGES="
xz
curl
wget
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

# Install 3rd-party plugins
log ""
log "==> Installing 3rd-party plugins"
log_action "xDreamy Skin"
wget -q --no-check-certificate https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

log_action "MoviesManager"
wget -q --no-check-certificate http://dreambox4u.com/dreamarabia/Transmission_e2/MoviesManager.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

log_action "Transmission_e2"
wget -q --no-check-certificate http://dreambox4u.com/dreamarabia/Transmission_e2/Transmission_e2.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

log_action "AJPanel"
wget -q --no-check-certificate https://raw.githubusercontent.com/AMAJamry/AJPanel/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

log_action "SubSSupport"
wget -q --no-check-certificate https://github.com/popking159/ssupport/raw/main/subssupport-install.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

log_action "Levi Manager"
wget -q --no-check-certificate https://raw.githubusercontent.com/levi-45/Manager/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_done || log_fail

# Apply xDreamy skin
log ""
log "==> Applying xDreamy as default skin"
SKIN_CFG="/etc/enigma2/settings"
SKIN_PATH="XDREAMY/skin.xml"

log_action "Stopping Enigma2"
init 4 && sleep 4 && log_done || log_fail

cp "$SKIN_CFG" "${SKIN_CFG}.bak"
sed -i '/^config.skin.primary_skin=/d' "$SKIN_CFG"
echo "config.skin.primary_skin=$SKIN_PATH" >> "$SKIN_CFG"
log "✔ Skin set to $SKIN_PATH"

log_action "Starting Enigma2"
init 3 && log_done || log_fail

log ""
log "✔ All tasks complete."
log "✔ Full log: $LOGFILE"
log "🎉 XDREAMY AiO setup finished!"

exit 0
