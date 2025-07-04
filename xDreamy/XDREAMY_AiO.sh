#!/bin/sh
# ★ XDREAMY AiO - Enigma2 One-Click Setup Script ★
# Version: 1.4 by M.Hussein
LOGFILE="/tmp/XDREAMY_AiO.log"

# === Logging Functions ===
log() { printf "%s\n" "$*" | tee -a "$LOGFILE"; }
log_action() { printf "    • %-45s" "$1" | tee -a "$LOGFILE"; }
log_done() { echo " [ ✔ ]" | tee -a "$LOGFILE"; }
log_skip() { echo " [ skipped ]" | tee -a "$LOGFILE"; }
log_fail() { echo " [ ✖ ]" | tee -a "$LOGFILE"; }
trap 'log "[ERROR] Line $LINENO failed. Continuing..."' ERR

# === Header ===
clear
log "============================================================="
log "      ★ XDREAMY AiO - Enigma2 Universal Setup Wizard ★"
log "           Version 1.4 - Developed by M.Hussein"
log "============================================================="
log "Started at: $(date)"
log ""
log "What this script does:"
log ""
log " 🔌 Network Configuration:"
log "    • Auto-detect LAN subnet and set static IP"
log "    • Set DNS (8.8.8.8, 9.9.9.9)"
log "    • Set root password to 'root'"
log ""
log " 🌍 System Localization:"
log "    • Detect city and timezone via IP"
log "    • Sync time using NTP"
log "    • Force language to en_EN (English)"
log "    • Keep only local + ar + en locales"
log ""
log " 🔧 System Optimization:"
log "    • Remove unnecessary bloatware"
log ""
log " 📦 Plugin & Skin Installer:"
log "    • Update feeds and install dependencies"
log "    • Install xDreamy, AJPanel, Transmission, etc."
log "    • Apply xDreamy skin"
log ""
log "🗂 Log saved to: $LOGFILE"
log ""

# === Countdown ===
log "⏱ Starting script execution... Please wait while XDREAMY_AiO prepares your image (this may take 1–2 minutes)..."

# === System Info ===
log ""
log "==> Detecting Basic System Info..."
IMAGE_NAME=$(grep -i 'distro' /etc/image-version 2>/dev/null | cut -d= -f2)
BOX_MODEL=$(cat /etc/hostname)
PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}')
NET_IFACE=$(ip -o -4 route show to default | awk '{print $5}')
LANG_CODE=$(curl -s https://ipapi.co/languages/ | cut -d',' -f1 | cut -c1-2)
[ -z "$LANG_CODE" ] && LANG_CODE="en"
log "✔ Image            : $IMAGE_NAME"
log "✔ Box Model        : $BOX_MODEL"
log "✔ Python           : $PYTHON_VERSION"
log "✔ Network Interface: $NET_IFACE"
log "✔ Local Language   : $LANG_CODE"

# === Network Setup ===
log ""
log "==> Setting Network IP and Account Password..."

IP_PREFIX=$(ip addr | grep 'inet 192.168' | awk '{print $2}' | cut -d. -f1-3 | head -n1)
[ -z "$IP_PREFIX" ] && IP_PREFIX="192.168.1"
STATIC_IP="${IP_PREFIX}.10"
GATEWAY="${IP_PREFIX}.1"
DNS1="8.8.8.8"
DNS2="9.9.9.9"

# Backup existing interface config if exists
[ -f /etc/network/interfaces ] && cp /etc/network/interfaces /etc/network/interfaces.bak

# Apply new interface config
cat > /etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto $NET_IFACE
iface $NET_IFACE inet static
    address $STATIC_IP
    netmask 255.255.255.0
    gateway $GATEWAY
    dns-nameservers $DNS1 $DNS2
EOF

# Restart networking
/etc/init.d/networking restart >/dev/null 2>&1 && log_action "Restarting networking service" && log_done || log_fail

# Logging details
log_action "Setting static IP address to $STATIC_IP" && log_done
log_action "Setting DNS servers: Primary $DNS1, Secondary $DNS2" && log_done

# Set root password
echo -e "root\nroot" | passwd root >/dev/null 2>&1 && \
log_action "Setting root password to 'root'" && log_done || log_fail

# === Locale Setup ===
log ""
log "==> Locale Configuration..."
SETTINGS_FILE="/etc/enigma2/settings"
[ -f "$SETTINGS_FILE" ] && cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
sed -i '/^config.osd.language=/d' "$SETTINGS_FILE"
echo "config.osd.language=en_EN" >> "$SETTINGS_FILE"
log_action "Set default language to English"; log_done

cd /usr/share/enigma2/po 2>/dev/null || true
for lang in *; do
  [ "$lang" = "en" ] || [ "$lang" = "ar" ] || [ "$lang" = "$LANG_CODE" ] || rm -rf "$lang"
done
cd /usr/share/locale 2>/dev/null || true
for folder in *; do
  case "$folder" in
    en|en_*|ar|ar_*|$LANG_CODE|${LANG_CODE}_*) ;; 
    *) rm -rf "$folder" ;;
  esac
done
log "   Removed locale/: *"
log_action "Clean unused languages"; log_done

# === Timezone / NTP ===
log ""
log "==> Detect Geolocation and Timezone..."
CITY=$(curl -s https://ipapi.co/city/)
TZ=$(curl -s https://ipapi.co/timezone/)
log "✔ Location         : $CITY"
log "✔ Timezone         : $TZ"
echo "$TZ" > /etc/timezone 2>/dev/null && log "✔ Timezone saved to /etc/timezone"
log_action "Stopping any NTP service"; /etc/init.d/ntpd stop >/dev/null 2>&1 && log_done || log_skip
log_action "Syncing time via pool.ntp.org"; ntpd -q -p pool.ntp.org >/dev/null 2>&1 && log_done || log_skip
log_action "Restarting NTP service"; /etc/init.d/ntpd start >/dev/null 2>&1 && log_done || log_skip

# === Remove Bloatware ===
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
enigma2-plugin-systemplugins-videomode
enigma2-plugin-systemplugins-videotune
enigma2-plugin-systemplugins-mphelp
enigma2-plugin-systemplugins-videoenhancement"
for pkg in $BLOAT_PACKAGES; do
  log_action "$pkg"
  opkg remove --force-depends "$pkg" >/dev/null 2>&1 && log_done || log_skip
done

# === Feed Update & Install Core Plugins ===
log ""
log "==> Updating and Upgrading Image Feeds...."
opkg update >/dev/null 2>&1 && log_action "Feed update" && log_done
opkg upgrade >/dev/null 2>&1 && log_action "Feed upgrade" && log_done

# === Install Core Plugins ===
log ""
log "==> Installing Extensions...."
EXT_PACKAGES="
xz curl wget ntpd
transmission transmission-client
python3-transmission-rpc python3-beautifulsoup4
enigma2-plugin-extensions-tmdb
enigma2-plugin-extensions-cacheflush
enigma2-plugin-extensions-epgtranslator
enigma2-plugin-systemplugins-serviceapp"
for pkg in $EXT_PACKAGES; do
  log_action "$pkg"
  opkg install "$pkg" >/dev/null 2>&1 && log_done || log_skip
done

# === Install 3rd-Party Plugins ===
log ""
log "==> Installing 3rd-party plugins"
wget -q https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "XDREAMY Skin" && log_done
wget -q http://dreambox4u.com/dreamarabia/Transmission_e2/Transmission_e2.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "Transmission" && log_done
wget -q https://raw.githubusercontent.com/AMAJamry/AJPanel/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "AJPanel" && log_done
wget -q https://github.com/popking159/ssupport/raw/main/subssupport-install.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "SubSSupport" && log_done
wget -q https://raw.githubusercontent.com/levi-45/Manager/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "Levi Multicam Manager" && log_done
wget -q https://raw.githubusercontent.com/biko-73/Ncam_EMU/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "NCAM Emulator" && log_done
wget -q https://raw.githubusercontent.com/eliesat/eliesatpanel/main/installer.sh -O - | /bin/sh >/dev/null 2>&1 && log_action "EliSat Panel" && log_done

# === Apply Skin ===
log ""
log "==> Applying xDreamy as default skin"
init 4 && sleep 4 && log_action "Stopping Enigma2" && log_done
sed -i '/^config.skin.primary_skin=/d' "$SETTINGS_FILE"
echo "config.skin.primary_skin=xDreamy/skin.xml" >> "$SETTINGS_FILE"
log_action "XDREAMY Skin set to default"; log_done
init 3 && log_action "Starting Enigma2"; log_done

# === Done ===
log ""
log "✔ All tasks complete."
log "✔ Full log: $LOGFILE"
log "🎉 Congratulations, XDREAMY AiO setup finished!"

exit 0
