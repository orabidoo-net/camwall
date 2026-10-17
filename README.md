# Camwall

Live-Stream Wallpaper & Recorder für Linux (GTK3)

Camwall ist eine Linux-Anwendung, die beliebige Live-Streams als bewegtes Wallpaper auf einzelnen Monitoren anzeigen kann. Zusätzlich bietet Camwall eine integrierte Aufnahmefunktion (Video & Screenshots), ein Overlay zur schnellen Steuerung sowie eine flexible Verwaltung eigener Streams und automatisierte Sendepläne.

Camwall wurde für Multi-Monitor-Setups entwickelt und unterstützt transparente Overlays, MPV-basierte Hintergrundvideos, konfigurierbare Stream-Profile und eine modulare Architektur.

---

## 🚀 Hauptfunktionen

### 🤖 Automatisierung & Watchdog (NEU in v1.8.0)
* **Autonomer Watchdog:** Startet unsichtbar im Hintergrund und sorgt für absolute Ausfallsicherheit der Streams.
* **Zeitplan-Steuerung (Schedule):** Automatischer Stream-Wechsel (z. B. Tag/Nacht-Rhythmus) nach definierten Uhrzeiten.
* **Latenzfreie Steuerung:** Der Player (`mpv`) wird über Unix-Sockets ferngesteuert, ohne ihn bei Änderungen neu starten zu müssen.

### 🎥 Live-Streams als Wallpaper
* Unterschiedliche Streams pro Monitor
* MPV-Rendering im Hintergrund
* Persistente Konfiguration pro Monitor

### 🕹️ Overlay (Transparente Steuerleiste)
* Start/Stop Aufnahme
* **Sofort-Screenshot:** Ein einfacher Doppelklick ins Overlay erzeugt einen latenzfreien Screenshot inkl. Info-Stempel (Wetter, Ort, Uhrzeit via Cairo).
* Stream-Info & Monitor wechseln
* Hover-Effekt für volle Sichtbarkeit
* Kontextmenü per Rechtsklick

### 🎬 Stream-Verwaltung & GUI
* **GUI mit Tabs:** Monitore, Streams (CRUD + Vorschau), **Zeitplan (Schedule)** und Recorder.
* Interne Stream-Auflösung via `yt-dlp` (umgeht Werbung und extrahiert direkte URLs von YouTube & Co.).

---

## 📦 Installation

Die einfachste Methode ist die Installation über das fertige Debian-Paket (`.deb`).

### 1. Vorab-Abhängigkeit (WICHTIG)
Da das Tool `xwinwrap` nicht in den offiziellen Ubuntu/Mint-Paketquellen enthalten ist, muss es **vorab manuell installiert werden**, damit die Videos als Hintergrundbild gerendert werden können.

### 2. Debian-Paket installieren
Lade dir die aktuelle `.deb`-Datei aus den [Releases](../../releases/latest) herunter und installiere sie im Terminal:
```bash
sudo apt install ./camwall_1.8.0_all.deb
