import subprocess

def resolve_stream(stream: dict, log=None) -> str | None:
    """
    Ermittelt aus einem Stream-Config-Eintrag die finale URL.
    Unterstützte Typen:
      - direct            -> URL direkt verwenden
      - youtube_cookies   -> yt-dlp -g --cookies-from-browser BROWSER URL
      - youtube           -> yt-dlp -g URL
    """
    def _log(msg: str):
        if log:
            log(msg)
        else:
            print(f"[stream_resolver] {msg}")

    stype = stream.get("type")
    url = stream.get("url")

    if not url:
        _log("Stream hat keine URL.")
        return None

    # Einfacher Fall: fertige URL (z.B. .m3u8)
    if stype == "direct":
        _log(f"Verwende direkte URL für Stream '{stream.get('name', '')}': {url}")
        return url

    # YouTube ohne Cookies
    if stype == "youtube":
        _log(f"Hole Stream-URL via yt-dlp für {url}")
        try:
            result = subprocess.run(
                ["yt-dlp", "-g", url],
                check=True,
                capture_output=True,
                text=True
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if not lines:
                _log("yt-dlp hat keine URL geliefert.")
                return None
            final_url = lines[-1]
            _log(f"yt-dlp URL: {final_url}")
            return final_url
        except subprocess.CalledProcessError as e:
            _log(f"yt-dlp Fehler: {e}\nSTDERR: {e.stderr}")
            return None

    # YouTube mit Browser-Cookies (z.B. Santa, Hush Bar)
    if stype == "youtube_cookies":
        browser = stream.get("browser", "firefox")
        _log(f"Hole Stream-URL via yt-dlp (Browser={browser}) für {url}")
        try:
            result = subprocess.run(
                ["yt-dlp", "-g", "--cookies-from-browser", browser, url],
                check=True,
                capture_output=True,
                text=True
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if not lines:
                _log("yt-dlp hat keine URL geliefert.")
                return None
            final_url = lines[-1]
            _log(f"yt-dlp URL: {final_url}")
            return final_url
        except subprocess.CalledProcessError as e:
            _log(f"yt-dlp Fehler: {e}\nSTDERR: {e.stderr}")
            return None

    _log(f"Unbekannter Stream-Typ: {stype}")
    return None
