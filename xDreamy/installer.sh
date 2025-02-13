#!/bin/bash

# Exit immediately if any critical command fails
set -e

# Total steps in process
TOTAL_STEPS=7
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
    local blink="$2"

    if [ "$blink" = "true" ]; then
        echo -ne "\e[5m$event\e[0m\n"  # Blinking effect
    else
        echo -ne "$event\n"
    fi
}

# Clear terminal and set up UI
clear
echo -ne "\e[?25l"  # Hide cursor
display_progress_bar 0

# Step 1: Remove previous version
log_event "Checking for existing XDREAMY installation..." true
if opkg list-installed | grep -q "enigma2-plugin-skins-xDreamy"; then
    log_event "Removing old version..." true
    opkg remove --force-depends enigma2-plugin-skins-xDreamy
    rm -rf /usr/share/enigma2/xDreamy
    log_event "✔ Previous version removed." false
else
    log_event "✔ No previous version found." false
fi
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 2: Check internet connection
log_event "Checking internet connection..." true
if ! ping -c 1 google.com &> /dev/null; then
    log_event "❌ No internet connection! Please check and try again." true
    exit 1
fi
log_event "✔ Internet connection OK." false
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 3: Ensure curl is installed
log_event "Checking for curl..." true
if ! command -v curl &> /dev/null; then
    log_event "Installing curl..." true
    opkg update
    opkg install curl
    if [ $? -ne 0 ]; then
        log_event "❌ Failed to install curl. Check your opkg settings." true
        exit 1
    fi
    log_event "✔ Curl installed successfully." false
else
    log_event "✔ Curl is already installed." false
fi
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 4: Download the XDREAMY skin package
log_event "Downloading XDREAMY skin package..." true
cd /tmp
curl -s -k -L "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" -o xDreamy.ipk --progress-bar
if [ $? -ne 0 ] || [ ! -f "xDreamy.ipk" ]; then
    log_event "❌ Download failed! Please try again later." true
    exit 1
fi
log_event "✔ Download completed." false
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 5: Install the XDREAMY skin
log_event "Installing XDREAMY skin..." true
opkg update
opkg install --force-overwrite /tmp/xDreamy.ipk
if [ $? -ne 0 ]; then
    log_event "❌ Error installing XDREAMY. Try manual installation." true
    exit 1
fi
log_event "✔ Installation completed successfully." false
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 6: Clean up
log_event "Cleaning up temporary files..." true
rm -f /tmp/xDreamy.ipk
log_event "✔ Cleanup complete." false
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Step 7: Restart the GUI
log_event "Restarting GUI in 3 seconds..." true
sleep 3
init 4 && sleep 2 && init 3
CURRENT_STEP=$((CURRENT_STEP + 1))
display_progress_bar $((CURRENT_STEP * 100 / TOTAL_STEPS))

# Restore cursor and finalize UI
echo -ne "\e[?25h"  # Show cursor
echo -ne "\e[0m"    # Reset text formatting

echo "------------------------------------------------------------------------"
echo "                         🎉 CONGRATULATIONS 🎉                         "
echo "                  XDREAMY Skin Installed Successfully                   "
echo "------------------------------------------------------------------------"
exit 0
