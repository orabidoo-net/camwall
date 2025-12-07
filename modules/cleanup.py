import os
from pathlib import Path

BASE = Path.home() / ".local" / "share" / "camwall"


def cleanup_recordings():
    """
    Entfernt abgebrochene Aufnahmedateien (*.mp4.part) im recordings-Verzeichnis
    und gibt (Liste_entfernter_Dateinamen, freigegebene_Bytes) zurück.
    """
    rec_dir = BASE / "recordings"
    removed = []
    freed = 0

    if rec_dir.exists():
        for f in rec_dir.glob("*.mp4.part"):
            try:
                size = f.stat().st_size
            except FileNotFoundError:
                continue
            freed += size
            removed.append(f.name)
            try:
                f.unlink()
            except OSError:
                # Wenn eine Datei aus irgendeinem Grund nicht gelöscht werden kann,
                # machen wir trotzdem mit den anderen weiter.
                continue

    return removed, freed
