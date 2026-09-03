import subprocess
import sys
import shutil
import os
import socket
import json
import asyncio
from urllib.request import urlopen
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


def _doh_resolve(hostname):
    try:
        url = "https://cloudflare-dns.com/dns-query?name=" + hostname + "&type=A&type=AAAA"
        req = urlopen(url, timeout=15)
        data = json.loads(req.read().decode())
        ips = [a["data"] for a in data.get("Answer", []) if a.get("data")]
        return ips
    except Exception:
        try:
            url = "https://dns.google/resolve?name=" + hostname + "&type=A"
            data = json.loads(urlopen(url, timeout=15).read().decode())
            return [a["data"] for a in data.get("Answer", []) if a.get("type") == 1 and a.get("data")]
        except Exception:
            return []


_original_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        ips = _doh_resolve(host)
        if not ips:
            raise
        results = []
        for ip in ips:
            try:
                results.extend(_original_getaddrinfo(ip, port, family, type, proto, flags))
            except Exception:
                continue
        if results:
            return results
        raise


def enable_doh():
    try:
        socket.getaddrinfo = _patched_getaddrinfo
        print("[+] Résolveur DNS alternatif (DoH) activé pour contourner les blocages.\n")
    except Exception as e:
        print(f"[!] Impossible d'activer DoH : {e}")


def clean_url(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ["list", "index", "start_radio"]:
        params.pop(key, None)
    cleaned = parsed._replace(query=urlencode(params, doseq=True))
    return urlunparse(cleaned)


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found

    print("[!] ffmpeg introuvable — tentative d'installation automatique...\n")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "imageio-ffmpeg"],
        )
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"[!] Échec de l'installation de ffmpeg : {e}")
        return None


def find_browser_cookies():
    cookies_txt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.isfile(cookies_txt):
        print("[+] Fichier cookies.txt trouvé — authentification activée.")
        return "cookies.txt"

    candidates = [
        ("chrome", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies")),
        ("edge", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies")),
        ("opera", os.path.expandvars(r"%APPDATA%\Opera Software\Opera Stable\Network\Cookies")),
        ("brave", os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies")),
        ("firefox", os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Mozilla", "Firefox", "Profiles")),
    ]

    for browser, path in candidates:
        if browser == "firefox":
            if os.path.isdir(path):
                import glob
                profs = glob.glob(os.path.join(path, "*.default*")) + glob.glob(os.path.join(path, "*.default-release"))
                if profs:
                    print("[+] Cookies Firefox trouvés — authentification activée.")
                    return browser
        elif os.path.isfile(path):
            print(f"[+] Cookies {browser.capitalize()} trouvés — authentification activée.")
            return browser

    return None


def detect_python_runtime(url):
    if "youtube.com" in url or "youtu.be" in url:
        for exe in [r"C:\Users\Adminko\.deno\bin\deno.exe",
                    shutil.which("deno"),
                    shutil.which("node"),
                    shutil.which("bun")]:
            if exe:
                return exe
    return None


def _is_french_stream(url):
    return "french-stream" in url or "french-stream.one" in url or "vidzy" in url


async def _extract_stream_french_stream(url):
    from playwright.async_api import async_playwright

    m3u8_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = await context.new_page()

        def on_response(resp):
            u = resp.url
            if ".m3u8" in u and u not in m3u8_urls:
                m3u8_urls.append(u)

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        try:
            await page.wait_for_selector("#seriePlayer", timeout=20000)
        except Exception:
            pass

        # attendre que le player charge le HLS
        for _ in range(6):
            if any(".m3u8" in u for u in m3u8_urls):
                break
            await page.wait_for_timeout(5000)

        await browser.close()

    # préférer master.m3u8
    master = [u for u in m3u8_urls if "master.m3u8" in u]
    return master[0] if master else (m3u8_urls[0] if m3u8_urls else None)


def download_from_platform(url, ffmpeg, browser):
    import yt_dlp
    from yt_dlp.networking.impersonate import ImpersonateTarget

    url = clean_url(url)
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": "%(title)s.%(ext)s",
        "noplaylist": True,
        "impersonate": ImpersonateTarget.from_str("chrome"),
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.google.com/",
        },
        "no_warnings": False,
        "ignoreerrors": False,
        "socket_timeout": 30,
        "retries": 3,
    }

    if browser:
        if browser == "cookies.txt":
            ydl_opts["cookiefile"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        else:
            ydl_opts["cookiesfrombrowser"] = (browser,)
            if browser == "firefox":
                import glob
                profs = glob.glob(os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Mozilla", "Firefox", "Profiles", "*.default*"))
                if profs:
                    ydl_opts["cookiesfrombrowser"] = (browser, profs[0])

    runtime = detect_python_runtime(url)
    if runtime:
        ydl_opts["js_runtimes"] = {runtime: {}}

    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg

    attempts = [ydl_opts]
    if browser:
        no_cookie_opts = dict(ydl_opts)
        no_cookie_opts.pop("cookiesfrombrowser", None)
        no_cookie_opts.pop("cookiefile", None)
        attempts.append(no_cookie_opts)

    last_err = None
    for attempt in attempts:
        try:
            ydl = yt_dlp.YoutubeDL(attempt)
        except Exception as e:
            last_err = e
            print(f"[!] Initialisation impossible ({e}) — nouvel essai sans cookies.\n")
            continue
        try:
            with ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "video")
                ext = info.get("ext", "mp4")
                print(f"\nTerminé ! Fichier sauvegardé : {title}.{ext}")
                return True
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            if "requested login" in str(e).lower() or "log in" in str(e).lower() or "certain audiences" in str(e).lower():
                print("[!] Connexion requise — nouvel essai avec les cookies du navigateur.\n")
                continue
            break
        except Exception as e:
            last_err = e
            break

    print("\nErreur de téléchargement : le lien est peut-être invalide, privé ou non supporté.")
    print(f"Détails : {last_err}")
    return False


def download_french_stream(url, ffmpeg):
    print("[*] Site de streaming détecté — extraction du flux via navigateur...")
    try:
        import playwright
    except ImportError:
        print("[!] Playwright non installé. Installation...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

    print("[*] Chargement de la page et extraction du flux vidéo...\n")
    stream = asyncio.run(_extract_stream_french_stream(url))

    if not stream:
        print("\nErreur : impossible d'extraire le flux vidéo de cette page.")
        return False

    try:
        import yt_dlp
        opts = {
            "outtmpl": "%(title)s.%(ext)s",
            "merge_output_format": "mp4",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Referer": "https://french-stream.one/",
            },
            "noplaylist": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        else:
            opts["downloader"] = "ffmpeg"

        print("[*] Flux extrait. Téléchargement en cours...\n")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(stream, download=True)
            title = info.get("title", "video")
            ext = info.get("ext", "mp4")
            print(f"\nTerminé ! Fichier sauvegardé : {title}.{ext}")
            return True
    except yt_dlp.utils.DownloadError as e:
        print(f"\nErreur de téléchargement du flux : {e}")
        return False


def download_video(url):
    ffmpeg = find_ffmpeg()
    browser = find_browser_cookies()

    if _is_french_stream(url):
        return download_french_stream(url, ffmpeg)
    return download_from_platform(url, ffmpeg, browser)


def main():
    enable_doh()

    url = input(
        "=== Téléchargement de vidéos universel ===\n"
        "Plateformes : YouTube, TikTok, Facebook, Instagram, X, sites de streaming\n"
        "\nEntrez l'URL : "
    ).strip()

    if not url:
        print("Aucune URL fournie. Abandon.")
        sys.exit(1)

    print(f"\nTéléchargement en cours depuis :\n  {url}\n")
    ok = download_video(url)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
