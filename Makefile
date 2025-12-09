APP_NAME = camwall
VERSION ?= 1.7
PKG_DIR = $(HOME)/camwall-deb
BUILD_FILE = $(HOME)/$(APP_NAME)_$(VERSION)_amd64.deb

.PHONY: build clean install release

build: clean
	@echo "📦 Erzeuge Paketverzeichnis..."
	mkdir -p $(PKG_DIR)/DEBIAN
	mkdir -p $(PKG_DIR)/opt/$(APP_NAME)
	mkdir -p $(PKG_DIR)/usr/local/bin
	mkdir -p $(PKG_DIR)/usr/share/applications
	mkdir -p $(PKG_DIR)/usr/share/icons/hicolor/256x256/apps

	@echo "📄 Kopiere Programmdateien..."
	cp -r modules $(PKG_DIR)/opt/$(APP_NAME)/
	cp camwall-gui.py $(PKG_DIR)/opt/$(APP_NAME)/
	cp camwall-overlay.py $(PKG_DIR)/opt/$(APP_NAME)/
	cp camwall-apply.py $(PKG_DIR)/opt/$(APP_NAME)/

	@echo "⚙️ Erstelle Startskripte..."
	printf '#!/bin/bash\nexec python3 /opt/camwall/camwall-gui.py\n' > $(PKG_DIR)/usr/local/bin/camwall
	chmod +x $(PKG_DIR)/usr/local/bin/camwall

	printf '#!/bin/bash\nexec python3 /opt/camwall/camwall-overlay.py "$$@"\n' > $(PKG_DIR)/usr/local/bin/camwall-overlay
	chmod +x $(PKG_DIR)/usr/local/bin/camwall-overlay

	@echo "🖼 Copy Icon falls vorhanden..."
	@if [ -f assets/camwall.png ]; then cp assets/camwall.png $(PKG_DIR)/usr/share/icons/hicolor/256x256/apps/ ; fi

	@echo "📝 Erstelle Desktop-Datei..."
	printf "[Desktop Entry]\nType=Application\nName=Camwall\nExec=/usr/local/bin/camwall\nIcon=camwall\nTerminal=false\nCategories=Utility;\n" > $(PKG_DIR)/usr/share/applications/camwall.desktop

	@echo "🧾 Erstelle control-Datei..."
	printf "Package: $(APP_NAME)\nVersion: $(VERSION)\nArchitecture: amd64\nMaintainer: Carsten\nDescription: Live-Stream Wallpaper mit Aufnahme- und Overlay-Funktionen.\n" > $(PKG_DIR)/DEBIAN/control

	@echo "🔧 Erstelle postinst..."
	printf '#!/bin/bash\nupdate-desktop-database >/dev/null 2>&1 || true\ngtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true\n' > $(PKG_DIR)/DEBIAN/postinst
	chmod 755 $(PKG_DIR)/DEBIAN/postinst

	@echo "📦 Baue Deb-Paket..."
	dpkg-deb --build $(PKG_DIR) $(BUILD_FILE)

	@echo "✔️ Fertig: $(BUILD_FILE)"

clean:
	@echo "🧹 Entferne alte Build-Verzeichnisse..."
	rm -rf $(PKG_DIR)

install:
	sudo dpkg -i $(BUILD_FILE)

release:
	@$(MAKE) build VERSION=$(VERSION)
