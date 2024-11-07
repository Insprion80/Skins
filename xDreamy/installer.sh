#!/bin/bash
#
echo "------------------------------------------------------------------------"
echo "                            Welcome To XDREAMY                          "
echo "                         XDREAMY Skin By Inspiron                       "
echo "                       Don't Remove this Disclaimer                     "
echo "------------------------------------------------------------------------"
echo "         Experience Enigma2 skin like never before with XDREAMY         "
echo "------------------------------------------------------------------------"
sleep 2
echo " removing previous version of xDreamy-FHD...      "
sleep 2;
if [ -d /usr/share/enigma2/xDreamy ] ; then
opkg remove enigma2-plugin-skins-xDreamy
rm -rf /usr/share/enigma2/xDreamy  > /dev/null 2>&1
echo 'Package removed.'
else
echo "You do not have previous version "
fi
echo ""
opkg install curl
sleep 2
#
cd /tmp
curl -s -k -Lbk -m 55532 -m 555104 "https://raw.githubusercontent.com/Insprion80/Skins/main/xDreamy/xDreamy.ipk" > /tmp/xDreamy.ipk
sleep 1
echo "installing ...."
cd /tmp
opkg install --force-overwrite xDreamy.ipk
echo ""
echo ""
echo ""
echo ""
sleep 1
cd
rm -f /tmp/xDreamy.ipk
echo "OK"
#
echo "----------------------------------------------------"
echo "                  CONGRATULATIONS                   "
echo "        XDREAMY Skin Installed Successfully         "
echo "----------------------------------------------------"
echo "   "
sleep 2
echo "Please wait to restart your GUI "
echo "   "
sleep 2
killall -9 enigma2
echo "   "
exit 0



