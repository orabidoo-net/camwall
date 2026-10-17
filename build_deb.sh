#!/bin/bash
# Bricht das Skript ab, falls ein Fehler auftritt
set -e

VERSION="1.8.0"
PKG="camwall"
ARCH="all"
BUILD_DIR="${PKG}_${VERSION}_${ARCH}"

echo "📦 Starte Build-Prozess für Camwall v${VERSION}..."

# 1. Temporäre Ordnerstruktur erstellen (wie das Wurzelverzeichnis von Linux)
mkdir -p ${BUILD_DIR}/DEBIAN
mkdir -p ${BUILD_DIR}/opt/camwall
mkdir -p ${BUILD_DIR}/usr/bin
mkdir -p ${BUILD_DIR}/usr/share/applications
mkdir -p ${BUILD_DIR}/etc/xdg/autostart

# 2. Die magische Control-Datei schreiben
echo "📄 Erstelle DEBIAN/control..."
cat <<CTRL_EOF > ${BUILD_DIR}/DEBIAN/control
Package: camwall
Version: ${VERSION}
Architecture: all
Maintainer: Carsten Brauckmann <dev@orabidoo.net>
Depends: python3, python3-gi, gir1.2-gtk-3.0, python3-cairo, mpv, yt-dlp
Description: Live-Stream Wallpaper Engine
 Camwall setzt Live-Streams als interaktive Desktop-Hintergründe.
 Inklusive Watchdog, Zeitplan-Steuerung und Sofort-Screenshot-Funktion.
CTRL_EOF

# 3. Programmdateien kopieren
echo "📂 Kopiere Python-Skripte und Module..."
cp *.py ${BUILD_DIR}/opt/camwall/
cp -r modules ${BUILD_DIR}/opt/camwall/

# Ausführbare Rechte setzen
chmod 755 ${BUILD_DIR}/opt/camwall/*.py

# 4. Systemweite Symlinks anlegen (damit man 'camwall-gui' von überall tippen kann)
echo "🔗 Erstelle Verknüpfungen..."
ln -s /opt/camwall/camwall-gui.py ${BUILD_DIR}/usr/bin/camwall-gui
ln -s /opt/camwall/camwall-apply.py ${BUILD_DIR}/usr/bin/camwall-apply
ln -s /opt/camwall/camwall-overlay.py ${BUILD_DIR}/usr/bin/camwall-overlay
ln -s /opt/camwall/camwall-watchdog.py ${BUILD_DIR}/usr/bin/camwall-watchdog

# 5. Startmenü-Eintrag für die GUI erstellen
echo "🖥️ Erstelle Startmenü-Eintrag..."
cat <<MENU_EOF > ${BUILD_DIR}/usr/share/applications/camwall.desktop
[Desktop Entry]
Name=Camwall
Comment=Live-Stream Wallpaper & Zeitplaner
Exec=/usr/bin/camwall-gui
Icon=camera-video
Terminal=false
Type=Application
Categories=AudioVideo;Video;Utility;
MENU_EOF
chmod 644 ${BUILD_DIR}/usr/share/applications/camwall.desktop

# 6. Autostart für den Watchdog einrichten (läuft unsichtbar im Hintergrund)
echo "🤖 Richte Watchdog-Autostart ein..."
cat <<AUTO_EOF > ${BUILD_DIR}/etc/xdg/autostart/camwall-watchdog.desktop
[Desktop Entry]
Name=Camwall Watchdog
Comment=Überwacht und steuert die Camwall Live-Streams
Exec=/usr/bin/camwall-watchdog
Terminal=false
Type=Application
NoDisplay=true
AUTO_EOF
chmod 644 ${BUILD_DIR}/etc/xdg/autostart/camwall-watchdog.desktop

# 7. Paket kompilieren
echo "🔨 Baue das finale Debian-Paket..."
dpkg-deb --build ${BUILD_DIR}

# 8. Arbeitsverzeichnis aufräumen
echo "🧹 Räume temporäre Dateien auf..."
rm -r ${BUILD_DIR}

echo "✅ Fertig! Das Paket liegt bereit: ${BUILD_DIR}.deb"
