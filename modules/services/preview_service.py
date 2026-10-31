import subprocess


class PreviewService:
    def __init__(self, logger=None):
        self.log = logger
        self._proc: subprocess.Popen | None = None

    def preview_stream_direct(self, url: str) -> str:
        if self.log:
            self.log(f"Preview: direkter Stream für {url}")
        return url

    def preview_stream_with_cookies(self, url: str, browser: str | None = None) -> str:
        browser = browser or "firefox"
        if self.log:
            self.log(f"Preview: yt-dlp (mit Cookies, Browser={browser}) für {url}")
        return self._resolve_stream_url(url, browser)

    def preview_stream_without_cookies(self, url: str) -> str:
        if self.log:
            self.log(f"Preview: yt-dlp (ohne Cookies) für {url}")
        return self._resolve_stream_url(url, None)

    def build_mpv_command(self, url: str, title: str) -> list[str]:
        title_arg = f"--title={title}"
        return ["mpv", "--force-window=yes", title_arg, url]

    def stop_preview(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=1.0)
        except Exception:
            pass
        finally:
            self._proc = None

    def launch_mpv(self, args: list[str]) -> None:
        self.stop_preview()
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _resolve_stream_url(self, url: str, browser: str | None) -> str:
        cmd = self._build_yt_dlp_cmd(url, browser)
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0 or not (result.stdout or "").strip():
            stderr = (result.stderr or "").strip() or "unbekannter Fehler bei yt-dlp"
            raise RuntimeError(stderr)
        return result.stdout.strip().splitlines()[-1]

    def _build_yt_dlp_cmd(self, url: str, browser: str | None) -> list[str]:
        if browser:
            return ["yt-dlp", "-g", "--cookies-from-browser", browser, url]
        return ["yt-dlp", "-g", url]
