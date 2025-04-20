#!/bin/bash

# Exit immediately if any critical command fails
set -e

# Total steps in process
TOTAL_STEPS=5
CURRENT_STEP=0

# Function to display progress bar
display_progress_bar() {
    local percentage=$1
    local progress_bar="["
    local filled=$((percentage / 2))
    for ((i = 0; i < filled; i++)); do progress_bar+="="; done
    for ((i = filled; i < 50; i++)); do progress_bar+=" "; done
    progress_bar+="] ${percentage}%"
    echo -ne "\r$progress_bar"
}

# Function to log events
log_event() {
    local event="$1"
    echo -ne "$event\n"
}

# Clear terminal and set up UI
clear
echo -ne "\e[?25l"  # Hide cursor
display_progress_bar 0

# Step 1: Remove previous version
log_event "Removing previous version if exists..."
if [ -d "/usr/share/enigma2/xDreamy" ]; then
    rm -rf /usr/share/enigma2/xDreamy
    log_event "✔ Old version removed"
else
    log_event "✔ No previous version found"
fi
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 2: Check internet connection
log_event "Checking internet connection..."
if ! ping -c 1 github.com &> /dev/null; then
    log_event "❌ No internet connection!"
    exit 1
fi
log_event "✔ Internet connection OK"
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 3: Download the XDREAMY skin package
log_event "Downloading XDREAMY skin package..."
cd /tmp
if wget -q "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk"; then
    log_event "✔ Download completed"
else
    log_event "❌ Download failed!"
    exit 1
fi
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 4: Install the XDREAMY skin
log_event "Installing XDREAMY skin..."
if opkg install --force-overwrite /tmp/xDreamy.ipk; then
    log_event "✔ Installation completed"
else
    log_event "❌ Installation failed!"
    exit 1
fi
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 5: Finalize installation
log_event "Finalizing installation..."
rm -f /tmp/xDreamy.ipk
log_event "✔ Cleanup complete"
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Restore cursor
echo -ne "\e[?25h"

# Final message with automatic GUI restart
cat <<EOF

------------------------------------------------------------------------
                         🎉 CONGRATULATIONS 🎉                         
                  XDREAMY Skin Installed Successfully                   
------------------------------------------------------------------------

Restarting GUI in 3 seconds...
EOF

sleep 3
init 4 && sleep 2 && init 3
exit 0
