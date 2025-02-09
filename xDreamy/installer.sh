#!/bin/bash
#
echo "------------------------------------------------------------------------"
echo "                            Welcome To XDREAMY                          "
echo "                         XDREAMY Skin By Inspiron                       "
echo "                       Don't Remove this Disclaimer                     "
echo "------------------------------------------------------------------------"
echo "         Experience Enigma2 skin like never before with XDREAMY         "
echo "------------------------------------------------------------------------"
sleep 2

# Check for existing installation
if opkg list-installed | grep enigma2-plugin-skins-xDreamy &> /dev/null; then
    echo "Removing the previous version of XDREAMY Skin..."
    sleep 2;
    opkg remove enigma2-plugin-skins-xDreamy
    rm -rf /usr/share/enigma2/xDreamy > /dev/null 2>&1
    echo 'Package removed.'
else
    echo "You do not have the previous version"
fi
echo ""

# Install curl if not already installed
opkg install curl

# Download the XDREAMY skin package
cd /tmp
echo "Downloading XDREAMY skin package..."
curl -s -k -L "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" -o /tmp/xDreamy.ipk --progress-bar
if [ $? -ne 0 ]; then
    echo "Error downloading the XDREAMY skin package."
    exit 1
fi

# Install the package
echo "Installing ...."
opkg install --force-overwrite /tmp/xDreamy.ipk
if [ $? -ne 0 ]; then
    echo "Error installing the XDREAMY skin."
    exit 1
fi

# Clean up
echo ""
echo ""
echo ""
sleep 1
if [ -f /tmp/xDreamy.ipk ]; then
    rm -f /tmp/xDreamy.ipk
fi

echo "------------------------------------------------------------------------"
echo "                            CONGRATULATIONS                             "
echo "                  XDREAMY Skin Installed Successfully                   "
echo "------------------------------------------------------------------------"
echo "   "
sleep 2
echo "Please wait to restart your GUI "
echo "   "
sleep 2
init 4 && init 3
echo "   "
exit 0
