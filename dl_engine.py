"""Moteur de téléchargement avec navigateur persistant (CDP) et pause/reprise."""

import os
import subprocess
import sys
import threading
import time
import collections
from urllib.request import urlopen

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_PORT = 9222

_PYTHON = os.path.join(APP_DIR, "venv", "Scripts", "python.exe")
if not os.path.isfile(_PYTHON):
    _PYTHON = sys.executable

JS_SCAN = r"""
() => {
  const urls = new Set();
  try {
    for (const e of performance.getEntriesByType('resource')) {
      if (/\.m3u8/i.test(e.name)) urls.add(e.name);
    }
  } catch (e) {}
  const vids = document.querySelectorAll('video, audio');
  for (const v of vids) {
    try { if (v.currentSrc && /\.m3u8/i.test(v.currentSrc)) urls.add(v.currentSrc); } catch (e) {}
    for (const s of v.querySelectorAll('source')) {
      try { if (s.src && /\.m3u8/i.test(s.src)) urls.add(s.src); } catch (e) {}
    }
  }
  let playing = false;
  for (const v of vids) {
    try { if (v.duration > 0 && !v.paused && !v.ended) { playing = true; } } catch (e) {}
  }
  const title = document.title || '';
  // tentative d'obtenir le titre "réel" du site
  let realTitle = '';
  try { realTitle = (document.querySelector('meta[property="og:title"]')||{}).content || ''; } catch (e) {}
  if (!realTitle) {
    try {
      const h1 = document.querySelector('h1');
      if (h1) realTitle = h1.textContent.trim();
    } catch (e) {}
  }
  return { urls: [...urls], playing, title, realTitle };
}
"""


def _cdp_version_timeout(port, timeout=1.5):
    try:
        return urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
    except Exception:
        return None


def _chromium_exe():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        for cand in [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]:
            if os.path.isfile(cand):
                return cand
    return None


class BrowserManager:
    """Gère un navigateur Chromium persistant accessible via le port CDP."""

    def __init__(self, port=DEBUG_PORT):
        self.port = port
        self.proc = None
        self.lock = threading.Lock()
        self.user_data = os.path.join(APP_DIR, ".browser_profile")

    def is_running(self):
        return _cdp_version_timeout(self.port) is not None

    def ensure_running(self, headless=False):
        if self.is_running():
            return True
        with self.lock:
            if self.is_running():
                return True
            exe = _chromium_exe()
            if not exe:
                return False
            os.makedirs(self.user_data, exist_ok=True)
            args = [
                exe,
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.user_data}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=Translate",
                "--lang=fr-FR",
                "--start-maximized",
            ]
            if headless:
                args.append("--headless=new")
            try:
                self.proc = subprocess.Popen(
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                return False
            # attendre que le port s'ouvre
            for _ in range(40):
                if self.is_running():
                    return True
                time.sleep(0.3)
            return self.is_running()

    def connect(self):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        except Exception:
            p.stop()
            raise
        return p, browser

    def shutdown(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None


def pick_m3u8(urls):
    if not urls:
        return None
    master = [u for u in urls if "master" in u.lower() or "index" in u.lower()]
    cand = master or urls
    # préférer les URLs les plus longues / complètes
    return sorted(set(cand), key=len)[-1]


def scan_page(page):
    """Renvoie (m3u8, playing, title) d'une page déjà ouverte."""
    m3u8 = None
    playing = False
    title = ""
    try:
        page_tab = page
        res = page_tab.evaluate(JS_SCAN)
    except Exception:
        return None, False, ""
    try:
        m3u8 = pick_m3u8(res.get("urls", []))
    except Exception:
        m3u8 = None
    playing = bool(res.get("playing"))
    title = (res.get("realTitle") or res.get("title") or "").strip()
    return m3u8, playing, title


class HlsDownload:
    """Téléchargement d'un flux m3u8 via yt-dlp en sous-processus (pause/reprise)."""

    def __init__(self, stream_url, title, referer, out_dir=APP_DIR, ffmpeg=None):
        self.stream_url = stream_url
        self.title = title
        self.referer = referer
        self.out_dir = out_dir
        self.ffmpeg = ffmpeg
        self.proc = None
        self.paused = False
        self.finished = False
        self.error = None
        self.lock = threading.RLock()
        self._lines = collections.deque()
        self._reader_thread = None
        self._run = True
        self.out_file = self._safe_name(title) + ".mp4"

    @staticmethod
    def _safe_name(name):
        name = (name or "").strip() or "stream"
        name = "".join(c for c in name if c not in '<>:"/\\|?*')
        name = name[:120]
        return name or "stream"

    def _reader(self):
        try:
            stream = self.proc.stdout
            for raw in iter(stream.readline, ""):
                if not self._run:
                    break
                self._lines.append(raw.strip())
        except Exception:
            pass

    def start(self):
        with self.lock:
            # attendre la fin d'un éventuel ancien processus avant d'en relancer un
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self._kill_tree(self.proc)
            self.paused = False
            cmd = [
                _PYTHON, "-m", "yt_dlp",
                "--newline",
                "--progress-template",
                "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|"
                "%(progress._downloaded_bytes_str)s|%(progress._total_bytes_estimate_str)s",
                "-o", os.path.join(self.out_dir, self._safe_name(self.title) + ".%(ext)s"),
                "--merge-output-format", "mp4",
                "--no-playlist", "--continue",
                "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "30",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ]
            if self.referer:
                cmd += ["--referer", self.referer]
            if self.ffmpeg:
                cmd += ["--ffmpeg-location", self.ffmpeg]
            cmd.append(self.stream_url)
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._lines.clear()
            self._run = True
            self._reader_thread = threading.Thread(target=self._reader, daemon=True)
            self._reader_thread.start()

    def pause(self):
        with self.lock:
            self.paused = True
            if self.proc is not None and self.proc.poll() is None:
                self._kill_tree(self.proc)

    def resume(self):
        with self.lock:
            if self.paused:
                self.paused = False
                self.start()

    @staticmethod
    def _kill_tree(proc):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                )
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def read_lines(self, timeout=0.2):
        """Renvoie les lignes de sortie disponibles (non bloquant)."""
        out = []
        try:
            while True:
                out.append(self._lines.popleft())
        except IndexError:
            return out

    def poll_status(self):
        if self.proc is None:
            return "stopped"
        rc = self.proc.poll()
        if rc is not None:
            if self.paused:
                return "paused"
            if rc == 0:
                self.finished = True
                return "finished"
            self.error = rc
            return "error"
        return "downloading"

    def read_final_title(self):
        # après fin, on devine le fichier réellement produit
        out = os.path.join(self.out_dir, self._safe_name(self.title) + ".mp4")
        if os.path.isfile(out):
            return os.path.basename(out)
        return self.out_file


def parse_progress_line(line):
    """Parse '12.3%|1.2MiB/s|00:05|...' -> (pct, speed, eta)."""
    parts = line.split("|")
    if len(parts) < 3:
        return None
    pct_s = parts[0].strip().rstrip("%") or "0"
    try:
        pct = float(pct_s)
    except Exception:
        pct = 0.0
    speed = parts[1].strip()
    eta = parts[2].strip()
    return pct, speed, eta
