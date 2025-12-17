import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path | None:
    p = start.resolve()
    while True:
        if (p / ".git").exists():
            return p
        if p.parent == p:
            return None
        p = p.parent


def runtime_summary() -> dict:
    cwd = Path.cwd().resolve()

    argv0 = Path(sys.argv[0])
    try:
        script = argv0.resolve()
    except Exception:
        script = argv0

    repo_root = _find_repo_root(cwd)

    return {
        "cwd": str(cwd),
        "argv0": str(argv0),
        "script": str(script),
        "argv0_base": argv0.name,
        "repo_root": str(repo_root) if repo_root else None,
        "cwd_in_repo": repo_root is not None,
        "script_in_repo": (repo_root is not None and str(script).startswith(str(repo_root))),
    }


def in_repo_but_not_running_repo_gui(summary: dict) -> bool:
    # Du stehst im Repo, aber das gestartete Script kommt NICHT aus dem Repo
    return bool(summary.get("cwd_in_repo")) and not bool(summary.get("script_in_repo"))


def show_gtk_warning(summary: dict) -> None:
    # GTK nur laden, wenn wir wirklich warnen (und wenn es verfügbar ist)
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception:
        # Fallback: nur stderr
        sys.stderr.write(
            "Camwall-Warnung: Du bist im Repo, aber startest offenbar eine andere Version.\n"
        )
        sys.stderr.write(f"cwd={summary.get('cwd')}\nscript={summary.get('script')}\n")
        return

    msg = (
        "Du befindest dich im Camwall-Repository,\n"
        "aber gestartet wurde offenbar NICHT die Repo-Version.\n\n"
        f"cwd:   {summary.get('cwd')}\n"
        f"script:{summary.get('script')}\n\n"
        "Tipp:\n"
        "  Repo-GUI:    python3 ./camwall-gui.py\n"
        "  Repo-Apply:  python3 ./camwall-apply.py\n"
    )

    dlg = Gtk.MessageDialog(
        modal=True,
        message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.OK,
        text="Camwall: Versions-Mix erkannt",
    )
    dlg.format_secondary_text(msg)
    dlg.run()
    dlg.destroy()
