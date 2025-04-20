#!/bin/bash

# Force remove existing version
echo "Removing current xDreamy..."
rm -rf /usr/share/enigma2/xDreamy
opkg remove --force-depends enigma2-plugin-skins-xDreamy

# Download fresh copy
echo "Downloading xDreamy..."
wget -q --no-check-certificate "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" -O /tmp/xDreamy_new.ipk

# Force install (ignore version checks)
echo "Installing..."
opkg install --force-reinstall --force-overwrite /tmp/xDreamy_new.ipk

# Cleanup
rm -f /tmp/xDreamy_new.ipk
echo "Restarting GUI..."
init 4 && init 3
