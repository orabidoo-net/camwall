import subprocess
from pathlib import Path
from typing import List, Tuple

from modules.stream_recorder import RECORDINGS_DIR


class MediaService:
    def __init__(self, cleanup_func=None):
        self.cleanup_func = cleanup_func

    def list_recordings(self) -> List[Path]:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            (p for p in RECORDINGS_DIR.glob("*.mp4") if not p.name.endswith(".temp.mp4")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files

    def delete_recording(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError("Datei wurde nicht gefunden.")
        path.unlink()

    def cleanup_temp_recordings(self) -> Tuple[List[str], int]:
        if self.cleanup_func:
            return self.cleanup_func()
        return [], 0

    def open_recording(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError("Datei wurde nicht gefunden.")
        subprocess.Popen(["mpv", str(path)])

    def open_recording_folder(self) -> None:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(RECORDINGS_DIR)])

    def rename_recording(self, media_path: Path, new_name: str) -> Path:
        if not new_name:
            raise ValueError("Neuer Name darf nicht leer sein.")
        new_path = media_path.with_name(new_name)
        media_path.rename(new_path)
        return new_path

    def get_human_size(self, num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if num_bytes < 1024:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"
