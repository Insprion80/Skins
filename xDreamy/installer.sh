#!/bin/bash
echo "Installing xDreamy Skin..."
rm -rf /usr/share/enigma2/xDreamy
wget -O /tmp/xDreamy.ipk "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk"
opkg install --force-overwrite /tmp/xDreamy.ipk
rm -f /tmp/xDreamy.ipk
echo "Restarting GUI..."
init 4 && init 3
