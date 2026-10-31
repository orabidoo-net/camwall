import os
from pathlib import Path

BASE = Path.home() / ".local" / "share" / "camwall"


def cleanup_recordings():
    """
    Entfernt abgebrochene/temporäre Aufnahmedateien (*.mp4.part, *.temp.mp4,
    *.mp4.temp, *.ytdl) im recordings-Verzeichnis und gibt
    (Liste_entfernter_Dateinamen, freigegebene_Bytes) zurück.
    """
    rec_dir = BASE / "recordings"
    removed = []
    freed = 0

    if rec_dir.exists():
        patterns = ("*.mp4.part", "*.temp.mp4", "*.mp4.temp", "*.temp.mp4.part", "*.ytdl")
        for pattern in patterns:
            for f in rec_dir.glob(pattern):
                try:
                    size = f.stat().st_size
                except FileNotFoundError:
                    continue
                try:
                    f.unlink()
                    freed += size
                    removed.append(f.name)
                except OSError:
                    # Wenn eine Datei aus irgendeinem Grund nicht gelöscht werden kann,
                    # machen wir trotzdem mit den anderen weiter.
                    continue

    return removed, freed
