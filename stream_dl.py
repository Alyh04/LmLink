import asyncio
import sys
import os
import shutil
from urllib.parse import urlparse

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


async def main():
    url = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not url:
        print("Usage: python stream_dl.py <URL>")
        return

    from playwright.async_api import async_playwright

    print("Ouverture du navigateur... Cliquez sur PLAY dans le film.")
    print("Le téléchargement démarrera aussitôt et continuera même en pause.\n")

    m3u8 = []
    mp4s = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="fr-FR",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        def on_response(resp):
            try:
                u = resp.url
            except Exception:
                return

            def launch(u):
                if ".m3u8" in u and u not in m3u8:
                    m3u8.append(u)
                    asyncio.create_task(trigger(u, "m3u8"))
                elif (".mp4" in u or ".m4v" in u) and u not in mp4s and "googlevideo" not in u:
                    mp4s.append(u)
                    asyncio.create_task(trigger(u, "mp4"))

            try:
                launch(u)
            except Exception:
                pass

        async def trigger(u, kind):
            print(f"\n>>> FLUX DÉTECTÉ ({kind}). Lancement du téléchargement...")
            path = await asyncio.to_thread(download_stream, u)
            if path:
                print(f"\n>>> Téléchargement terminé : {path}\n")

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print("Chargement:", e)

        print("Navigateur ouvert. Jouez la vidéo, le téléchargement se lancera tout seul...")
        print("(Fermez la fenêtre du navigateur pour arrêter)\n")

        try:
            await page.wait_for_timeout(3600000)
        except Exception:
            pass

        await browser.close()


def download_stream(url):
    import yt_dlp

    title = ""
    parsed = urlparse(url)
    if ".m3u8" in url:
        name = parsed.path.rstrip("/").split("/")[-1]
        base = name.replace("master.m3u8", "").replace(".m3u8", "").strip("_")
        title = base if base else "stream"
    else:
        title = os.path.basename(parsed.path) or "video"

    title = title[:60] or "stream"

    ffmpeg = find_ffmpeg()
    opts = {
        "outtmpl": os.path.join(OUT_DIR, f"{title}.%(ext)s"),
        "merge_output_format": "mp4",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://french-stream.one/",
        },
        "retries": 5,
        "fragment_retries": 5,
        "noplaylist": True,
        "continuedl": True,
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    else:
        opts["downloader"] = "ffmpeg"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            print(f"Fichier : {info.get('title')}.{info.get('ext')}")
        return os.path.join(OUT_DIR, f"{title}.mp4")
    except Exception as e:
        print(f"Erreur téléchargement : {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
