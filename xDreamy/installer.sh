#!/bin/bash
#
echo "------------------------------------------------------------------------"
echo "                            Welcome To XDREAMY                          "
echo "                         XDREAMY Skin By Inspiron                       "
echo "                       Don't Remove this Disclaimer                     "
echo "------------------------------------------------------------------------"
echo "         Experience Enigma2 skin like never before with XDREAMY         "
echo "------------------------------------------------------------------------"
sleep 2
echo " removing the previous version of XDREAMY Skin...      "
sleep 2;
if [ -d /usr/share/enigma2/xDreamy ] ; then
    opkg remove enigma2-plugin-skins-xDreamy
    rm -rf /usr/share/enigma2/xDreamy > /dev/null 2>&1
    echo 'Package removed.'
else
    echo "You do not have the previous version "
fi
echo ""

# Install curl if not already installed
opkg install curl
sleep 2

#
cd /tmp
echo "Downloading XDREAMY skin package..."
curl -s -k -L "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" -o /tmp/xDreamy.ipk
if [ $? -ne 0 ]; then
    echo "Error downloading the XDREAMY skin package."
    exit 1
fi
sleep 1

echo "Installing ...."
opkg install --force-overwrite /tmp/xDreamy.ipk
if [ $? -ne 0 ]; then
    echo "Error installing the XDREAMY skin."
    exit 1
fi

echo ""
echo ""
echo ""
sleep 1

# Clean up the temporary file
if [ -f /tmp/xDreamy.ipk ]; then
    rm -f /tmp/xDreamy.ipk
fi

echo "OK"
#
echo "------------------------------------------------------------------------"
echo "                            CONGRATULATIONS                             "
echo "                  XDREAMY Skin Installed Successfully                   "
echo "------------------------------------------------------------------------"
echo "   "
sleep 2
echo "Please wait to restart your GUI "
echo "   "
sleep 2
killall -9 enigma2
echo "   "
exit 0
