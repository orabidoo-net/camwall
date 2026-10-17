import subprocess

def resolve_stream(stream: dict, log) -> str:
    if not stream:
        return ""

    if "direct_url" in stream:
        return stream.get("direct_url", "") or ""

    url = (stream.get("url", "") or "").strip()
    if not url:
        return ""

    # Wir lesen jetzt den eingestellten Typ und Browser sauber aus!
    stype = stream.get("type", "youtube")
    browser = stream.get("browser", "firefox")

    if "youtube.com" in url or "youtu.be" in url:
        log(f"resolve_stream: starte yt-dlp für {url} (Typ: {stype})")
        
        # Standard-Befehl OHNE Cookies (für normale Webcams)
        cmd = ["yt-dlp", "-g", url]
        
        # Nur wenn explizit gewünscht, hängen wir die Cookies an
        if stype == "youtube_cookies" and browser:
            cmd = ["yt-dlp", "--cookies-from-browser", browser, "-g", url]

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            log(f"resolve_stream: yt-dlp Aufruf fehlgeschlagen: {e}")
            return ""

        if result.returncode != 0:
            err = (result.stderr or "").strip()
            log(f"resolve_stream: yt-dlp Fehler: {err}")
            return ""

        resolved = (result.stdout or "").strip().splitlines()
        final_url = resolved[0] if resolved else ""
        log(f"resolve_stream: yt-dlp URL = {final_url}")
        return final_url

    return url
