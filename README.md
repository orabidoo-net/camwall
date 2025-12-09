# Camwall  
Live-Stream Wallpaper & Recorder für Linux (GTK3)

Camwall ist eine Linux-Anwendung, die beliebige Live-Streams als bewegtes Wallpaper
auf einzelnen Monitoren anzeigen kann. Zusätzlich bietet Camwall eine integrierte
Aufnahmefunktion (Video & Screenshots), ein Overlay zur schnellen Steuerung sowie
eine flexible Verwaltung eigener Streams.

Camwall wurde für Multi-Monitor-Setups entwickelt und unterstützt transparente
Overlays, MPV-basierte Hintergrundvideos, konfigurierbare Stream-Profile und
eine modulare Architektur (Tabs, Controller und Services).

---

## 🚀 Hauptfunktionen

### 🎥 Live-Streams als Wallpaper
- Unterschiedliche Streams pro Monitor  
- MPV-Rendering im Hintergrund  
- Persistente Konfiguration pro Monitor

### 📺 Overlay (Transparente Steuerleiste)
- Start/Stop Aufnahme  
- Screenshot  
- Stream-Info  
- Monitor wechseln  
- Hover-Effekt für volle Sichtbarkeit  
- Kontextmenü per Rechtsklick

### 🎬 Aufnahmefunktionen
- MP4-Videoaufnahmen  
- Screenshots (PNG/JPG)  
- Automatische Dateibenennung  
- Bereinigung unvollständiger Dateien  

### 📚 Stream-Verwaltung
- Streams hinzufügen / bearbeiten / löschen  
- Vorschau-Funktion  
- Zuordnung zu Monitoren  
- Interner Stream-Resolver

### 🖥️ GUI mit Tabs
- **Monitore** (Zuordnung & Autostart Overlay)  
- **Streams** (CRUD + Vorschau)  
- **Recorder** (Aufnahme, Screenshots, Medienliste)

---

## 📦 Installation

### Voraussetzungen
- Linux Mint / Ubuntu / Debian  
- Python 3.10+  
- GTK3 (`python3-gi`)  
- MPV (`mpv`)  
- ffmpeg  

Installation der Abhängigkeiten:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 mpv ffmpeg
