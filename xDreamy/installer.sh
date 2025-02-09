#!/bin/bash

echo "------------------------------------------------------------------------"
echo "                          Welcome To XDREAMY                             "
echo "                       XDREAMY Skin By Inspiron                          "
echo "                    Don't Remove this Disclaimer                         "
echo "------------------------------------------------------------------------"
echo "         Experience Enigma2 skin like never before with XDREAMY          "
echo "------------------------------------------------------------------------"
sleep 2

# التحقق مما إذا كان XDREAMY مثبتًا مسبقًا
if opkg list-installed | grep -q "enigma2-plugin-skins-xDreamy"; then
    echo "Removing the previous version of XDREAMY Skin..."
    sleep 2
    opkg remove enigma2-plugin-skins-xDreamy
    rm -rf /usr/share/enigma2/xDreamy
    echo "✔ Previous version removed."
else
    echo "✔ No previous version found."
fi
echo ""

# التحقق مما إذا كان `curl` مثبتًا
if ! command -v curl &> /dev/null; then
    echo "Installing curl..."
    opkg install curl
    if [ $? -ne 0 ]; then
        echo "❌ Error installing curl. Please install it manually."
        exit 1
    fi
fi

# تنزيل حزمة XDREAMY
cd /tmp
echo "Downloading XDREAMY skin package..."
curl -s -k -L "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" -o xDreamy.ipk --progress-bar
if [ $? -ne 0 ] || [ ! -f "xDreamy.ipk" ]; then
    echo "❌ Error downloading the XDREAMY skin package."
    exit 1
fi
echo "✔ Download completed."

# تثبيت الحزمة
echo "Installing XDREAMY Skin..."
opkg install --force-overwrite /tmp/xDreamy.ipk
if [ $? -ne 0 ]; then
    echo "❌ Error installing the XDREAMY skin."
    exit 1
fi
echo "✔ XDREAMY Installed Successfully."

# تنظيف الملفات المؤقتة
rm -f /tmp/xDreamy.ipk

echo "------------------------------------------------------------------------"
echo "                         🎉 CONGRATULATIONS 🎉                           "
echo "                   XDREAMY Skin Installed Successfully                   "
echo "------------------------------------------------------------------------"
echo ""
sleep 2
echo "Restarting GUI in 3 seconds..."
sleep 3
init 4 && sleep 2 && init 3
exit 0
