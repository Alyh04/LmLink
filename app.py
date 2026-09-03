import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import os
import subprocess
import shutil
import socket
import json
import time
from urllib.request import urlopen
from urllib.parse import urlparse
import ssl

APP_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------- DNS DoH (contourne bloqueur FAI) ----------
def _doh_resolve(hostname):
    try:
        url = "https://cloudflare-dns.com/dns-query?name=" + hostname + "&type=A&type=AAAA"
        data = json.loads(urlopen(url, timeout=15).read().decode())
        return [a["data"] for a in data.get("Answer", []) if a.get("data")]
    except Exception:
        try:
            url = "https://dns.google/resolve?name=" + hostname + "&type=A"
            data = json.loads(urlopen(url, timeout=15).read().decode())
            return [a["data"] for a in data.get("Answer", []) if a.get("type") == 1 and a.get("data")]
        except Exception:
            return []


_orig_gai = socket.getaddrinfo


def _patched_gai(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _orig_gai(host, port, family, type, proto, flags)
    except socket.gaierror:
        ips = _doh_resolve(host)
        if not ips:
            raise
        out = []
        for ip in ips:
            try:
                out.extend(_orig_gai(ip, port, family, type, proto, flags))
            except Exception:
                continue
        if out:
            return out
        raise


socket.getaddrinfo = _patched_gai


# ---------- helpers ----------
def find_ffmpeg():
    f = shutil.which("ffmpeg")
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def is_streaming_site(url):
    return any(d in url for d in ["french-stream", "vidzy", "uqload", "voe", "netu", "streaming"])


# ---------- Gestionnaire de téléchargement ----------
class DownloadItem:
    def __init__(self, url, app):
        self.url = url
        self.app = app
        self.status = "En attente"
        self.progress = 0.0
        self.total = 0
        self.done = 0
        self.speed = 0
        self.eta = ""
        self.title = url
        self.out_file = ""
        self.downloader = None
        self.thread = None
        self.stream_paused = False
        self.hls = None


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        root.title("Téléchargeur Universel")
        root.geometry("860x600")
        root.minsize(700, 450)

        self.items = []
        self.queue = queue.Queue()
        self.active = {}

        import dl_engine
        self.browser_mgr = dl_engine.BrowserManager()

        self._build_ui()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        # Output folder reference (shared)
        self.dir_var = tk.StringVar(value=APP_DIR)

        # Notebook with tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self._build_download_tab()
        self._build_convert_tab()
        self._build_key_tab()

    def _build_download_tab(self):
        self.dl_tab = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.dl_tab, text="  Téléchargement  ")

        # Top: URL entry
        top = ttk.Frame(self.dl_tab)
        top.pack(fill="x")

        ttk.Label(top, text="URL:").pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.url_entry.bind("<Return>", lambda e: self.add_download())

        self.add_btn = ttk.Button(top, text="Télécharger", command=self.add_download)
        self.add_btn.pack(side="left")

        # Output folder display
        fo = ttk.Frame(self.dl_tab)
        fo.pack(fill="x", pady=(2, 5))
        ttk.Label(fo, text="Dossier de téléchargement :").pack(side="left")
        ttk.Label(fo, textvariable=self.dir_var, foreground="#555").pack(side="left", padx=6)

        # Progress area
        self.list_frame = ttk.Frame(self.dl_tab)
        self.list_frame.pack(fill="both", expand=True, pady=(0, 5))

        # tasks table
        cols = ("title", "status", "size", "speed", "progress", "eta")
        self.tree = ttk.Treeview(self.list_frame, columns=cols, show="headings", height=12)
        headings = {
            "title": ("Fichier", 320),
            "status": ("Statut", 110),
            "size": ("Taille", 90),
            "speed": ("Vitesse", 90),
            "progress": ("Progression", 110),
            "eta": ("Temps restant", 90),
        }
        for c, (t, w) in headings.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c == "title" else "center")
        self.tree.pack(side="left", fill="both", expand=True)

        # scrollbar
        sb = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        # progress bar global + status line
        self.prog_var = tk.DoubleVar(value=0)
        ttk.Progressbar(self.dl_tab, variable=self.prog_var, maximum=100).pack(fill="x", pady=(0, 3))
        self.status_var = tk.StringVar(value="Prêt")
        ttk.Label(self.dl_tab, textvariable=self.status_var, anchor="w").pack(fill="x")

        # buttons row
        btns = ttk.Frame(self.dl_tab)
        btns.pack(fill="x", pady=5)
        ttk.Button(btns, text="Supprimer sélection", command=self.remove_selected).pack(side="left")
        ttk.Button(btns, text="Effacer les terminés", command=self.clear_finished).pack(side="left", padx=6)
        ttk.Button(btns, text="Tout effacer", command=self.clear_all).pack(side="left")
        ttk.Button(btns, text="Pause / Reprendre", command=self.toggle_pause).pack(side="left", padx=6)
        ttk.Button(btns, text="Ouvrir le dossier", command=self.open_folder).pack(side="right")

        # log area
        self.log_box = scrolledtext.ScrolledText(self.dl_tab, height=8, state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(0, 5))

    def _build_convert_tab(self):
        self.cv_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.cv_tab, text="  Conversion MP4→MP3  ")

        head = ttk.Label(self.cv_tab,
                         text="Convertissez un fichier MP4 (ou tout autre fichier vidéo) en MP3 audio.",
                         font=("Segoe UI", 10))
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # Info + load file button
        self.file_var = tk.StringVar(value="Aucun fichier sélectionné")
        ttk.Label(self.cv_tab, text="Fichier vidéo :").grid(row=1, column=0, sticky="w")
        ttk.Label(self.cv_tab, textvariable=self.file_var, foreground="#555").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(self.cv_tab, text="Choisir...", command=self.choose_file).grid(row=1, column=2, sticky="e")

        # Bitrate selection
        self.bitrate_var = tk.StringVar(value="192k")
        ttk.Label(self.cv_tab, text="Qualité audio:").grid(row=2, column=0, sticky="w", pady=6)
        self.bitrate = ttk.Combobox(self.cv_tab, textvariable=self.bitrate_var, state="readonly", width=10,
                                    values=["128k", "192k", "256k", "320k"])
        self.bitrate.current(1)
        self.bitrate.grid(row=2, column=1, sticky="w", padx=6)

        # Convert button
        ttk.Button(self.cv_tab, text="Convertir en MP3", command=self.start_convert).grid(row=2, column=2, sticky="e")

        # Conversion progress
        ttk.Label(self.cv_tab, text="Progression :").grid(row=3, column=0, sticky="w", pady=(10, 2))
        self.cv_prog_var = tk.DoubleVar(value=0)
        self.cv_bar = ttk.Progressbar(self.cv_tab, variable=self.cv_prog_var, maximum=100, length=500)
        self.cv_bar.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.cv_status_var = tk.StringVar(value="Prêt")
        ttk.Label(self.cv_tab, textvariable=self.cv_status_var, foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w")

        # per-file progress table
        ttk.Label(self.cv_tab, text="Fichiers / Conversions :").grid(row=6, column=0, sticky="w", pady=(10, 2))
        cols = ("file", "status", "progress")
        self.cv_tree = ttk.Treeview(self.cv_tab, columns=cols, show="headings", height=6)
        self.cv_tree.heading("file", text="Fichier")
        self.cv_tree.heading("status", text="Statut")
        self.cv_tree.heading("progress", text="Progression")
        self.cv_tree.column("file", width=360)
        self.cv_tree.column("status", width=160)
        self.cv_tree.column("progress", width=120)
        self.cv_tree.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=5)

        # Note about output
        ttk.Label(self.cv_tab,
                  text="Le fichier MP3 sera enregistré dans : " + APP_DIR,
                  foreground="#888").grid(row=8, column=0, columnspan=3, sticky="w")

        self.cv_tab.columnconfigure(1, weight=1)

    # ---------- conversion ----------
    def choose_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Choisir un fichier vidéo",
            filetypes=[("Fichiers vidéo", "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.m4v"), ("Tous les fichiers", "*.*")],
            initialdir=APP_DIR,
        )
        if path:
            self.file_var.set(path)

    def start_convert(self):
        src = self.file_var.get()
        if src == "Aucun fichier sélectionné" or not os.path.isfile(src):
            messagebox.showwarning("Fichier manquant", "Veuillez choisir un fichier vidéo à convertir.")
            return
        threading.Thread(target=self._do_convert, args=(src,), daemon=True).start()

    def _do_convert(self, src):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.conv_log("ffmpeg introuvable.")
            self.cv_status_var.set("Erreur : ffmpeg introuvable")
            return

        out = os.path.join(APP_DIR, os.path.splitext(os.path.basename(src))[0] + ".mp3")
        bitrate = self.bitrate_var.get()

        basename = os.path.basename(src)
        if not self.cv_tree.exists("cv0"):
            self.cv_tree.insert("", "end", iid="cv0", values=(basename, "Conversion...", "0%"))
        else:
            self.cv_tree.item("cv0", values=(basename, "Conversion...", "0%"))

        self.cv_prog_var.set(0)
        self.cv_status_var.set(f"Conversion de {os.path.basename(src)}...")

        cmd = [ffmpeg, "-y", "-i", src, "-vn", "-acodec", "libmp3lame", "-b:a", bitrate, out]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, errors="replace")

        duration = None
        last = time.time()
        for line in proc.stdout:
            line = line.strip()
            if "Duration:" in line and duration is None:
                try:
                    d = line.split("Duration:")[1].split(",")[0].strip()
                    duration = self._parse_ts(d)
                except Exception:
                    duration = None
            if "time=" in line:
                try:
                    t = line.split("time=")[1].strip().split(" ")[0]
                    secs = self._parse_ts(t)
                    if duration and secs:
                        pct = min(secs / duration * 100, 99.0)
                        if time.time() - last > 0.3:
                            self.cv_prog_var.set(pct)
                            self.cv_tree.item("cv0", values=(basename, "Conversion...", f"{pct:.0f}%"))
                            last = time.time()
                except Exception:
                    pass
        proc.wait()

        if os.path.exists(out) and proc.returncode == 0:
            self.cv_prog_var.set(100)
            self.cv_tree.item("cv0", values=(basename, "Terminé", "100%"))
            self.cv_status_var.set(f"Terminé : {os.path.basename(out)}")
            self.log(f"Conversion terminée : {out}")
        else:
            self.cv_tree.item("cv0", values=(basename, "Erreur", "-"))
            self.cv_status_var.set("Erreur lors de la conversion.")

    def _parse_ts(self, s):
        try:
            parts = s.split(":")
            secs = 0
            for p in parts:
                secs = secs * 60 + float(p)
            return secs
        except Exception:
            return None

    def conv_log(self, msg):
        self.log(msg)

    # ---------- détection de clé ----------
    NOTE_NAMES = ["Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]
    # noms anglais (id + bémol) pour l'affichage demandé
    EN_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    EN_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    MAJOR_TONALITIES = ("C Major", "C# Major", "Db Major", "D Major", "Eb Major", "E Major",
                        "F Major", "F# Major", "Gb Major", "G Major", "Ab Major", "A Major",
                        "Bb Major", "B Major")
    MINOR_TONALITIES = ("A Minor", "A# Minor", "Bb Minor", "B Minor", "C Minor", "C# Minor",
                        "D Minor", "D# Minor", "Eb Minor", "E Minor", "F Minor", "F# Minor",
                        "G Minor", "G# Minor")

    def _build_key_tab(self):
        kt = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(kt, text="  Clé d'une chanson  ")

        head = ttk.Label(kt, text="Détectez la tonalité (majeure / mineure) d'un fichier audio ou vidéo.",
                         font=("Segoe UI", 10))
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # File selection
        self.key_file_var = tk.StringVar(value="Aucun fichier sélectionné")
        ttk.Label(kt, text="Fichier audio/vidéo :").grid(row=1, column=0, sticky="w")
        ttk.Label(kt, textvariable=self.key_file_var, foreground="#555").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(kt, text="Choisir...", command=self.choose_key_file).grid(row=1, column=2, sticky="e")

        # Analyze button + progress
        ttk.Button(kt, text="Analyser la clé", command=self.start_key_detect).grid(row=2, column=0, columnspan=2, sticky="w", pady=10)

        self.key_status_var = tk.StringVar(value="Prêt")
        ttk.Label(kt, textvariable=self.key_status_var, foreground="#555").grid(row=2, column=2, sticky="e")

        # Result display
        res = ttk.LabelFrame(kt, text="Résultat", padding=10)
        res.grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)

        toprow = ttk.Frame(res)
        toprow.pack(anchor="w")
        self.key_result_var = tk.StringVar(value="—")
        ttk.Label(toprow, text="Clé détectée : ", font=("Segoe UI", 11)).pack(side="left")
        ttk.Label(toprow, textvariable=self.key_result_var, font=("Segoe UI", 18, "bold")).pack(side="left")

        self.key_bpm_var = tk.StringVar(value="")
        ttk.Label(toprow, textvariable=self.key_bpm_var, font=("Segoe UI", 14, "bold"),
                  foreground="#2980b9").pack(side="left", padx=(20, 0))

        self.key_detail_var = tk.StringVar(value="")
        ttk.Label(res, textvariable=self.key_detail_var, foreground="#555").pack(anchor="w", pady=(4, 0))

        self.key_maj_var = tk.StringVar(value="Tonalités Majeures : …")
        self.key_min_var = tk.StringVar(value="Tonalités Mineures : …")
        ttk.Label(res, textvariable=self.key_maj_var, wraplength=680, justify="left", foreground="#27ae60").pack(anchor="w", pady=(6, 0))
        ttk.Label(res, textvariable=self.key_min_var, wraplength=680, justify="left", foreground="#8e44ad").pack(anchor="w", pady=(2, 0))

        # chroma distribution display
        ttk.Label(kt, text="Distribution des notes (chromagramme moyen) :").grid(row=4, column=0, sticky="w", pady=(8, 2))
        self.notes_canvas = tk.Canvas(kt, height=140, bg="white")
        self.notes_canvas.grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)
        self.notes_canvas.bind("<Configure>", lambda e: self._draw_chroma())

        kt.columnconfigure(1, weight=1)

    def choose_key_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Choisir un fichier audio ou vidéo",
            filetypes=[("Fichiers audio", "*.mp3;*.wav;*.flac;*.ogg;*.m4a;*.aac"),
                       ("Fichiers vidéo", "*.mp4;*.mkv;*.avi;*.mov;*.webm"),
                       ("Tous les fichiers", "*.*")],
            initialdir=APP_DIR,
        )
        if path:
            self.key_file_var.set(path)

    def start_key_detect(self):
        src = self.key_file_var.get()
        if src == "Aucun fichier sélectionné" or not os.path.isfile(src):
            messagebox.showwarning("Fichier manquant", "Veuillez choisir un fichier à analyser.")
            return
        self.key_status_var.set("Analyse en cours...")
        self.key_result_var.set("—")
        self.key_bpm_var.set("")
        self.key_detail_var.set("")
        self.key_maj_var.set("Tonalités Majeures : …")
        self.key_min_var.set("Tonalités Mineures : …")
        threading.Thread(target=self._do_key_detect, args=(src,), daemon=True).start()

    def _do_key_detect(self, src):
        try:
            import librosa
        except ImportError:
            self._key_finish("Erreur : librosa non installé. Lancez : pip install librosa soundfile")
            return
        try:
            self._key_finish_progress("Chargement du fichier...")
            y, sr = librosa.load(src, sr=22050, mono=True)
            self._key_finish_progress("Analyse spectrale...")
            # chromagramme (résolution 22050 = ~14 Hz par bin, ok pour chroma)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            self._key_finish_progress("Calcul de la clé (Krumhansl-Schmuckler)...")

            chroma_mean = chroma.mean(axis=1)  # (12,)
            self._key_finish_draw(chroma_mean)

            # profils de Krumhansl-Schmuckler
            maj = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
            min_ = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
            corr_maj_best, best_maj, corr_min_best, best_min = 0, 0, 0, 0
            for r in range(12):
                cm = sum(chroma_mean[(r + i) % 12] * maj[i] for i in range(12))
                cn = sum(chroma_mean[(r + i) % 12] * min_[i] for i in range(12))
                if cm > corr_maj_best:
                    corr_maj_best, best_maj = cm, r
                if cn > corr_min_best:
                    corr_min_best, best_min = cn, r

            maj_highlight = ""
            min_highlight = ""
            if corr_maj_best >= corr_min_best:
                key = self.EN_FLAT[best_maj] + " Major"
                score = corr_maj_best
                maj_highlight = self.EN_SHARP[best_maj] + " Major"
            else:
                key = self.EN_FLAT[best_min] + " Minor"
                score = corr_min_best
                min_highlight = self.EN_SHARP[best_min] + " Minor"

            total = corr_maj_best + corr_min_best
            conf = (score / total * 100) if total else 0
            detail = f"{self.NOTE_NAMES[best_maj]} majeur (score {corr_maj_best:.0f}) vs " \
                     f"{self.NOTE_NAMES[best_min]} mineur (score {corr_min_best:.0f}) · confiance ≈ {conf:.0f}%"

            # BPM adapté
            bpm = ""
            try:
                self._key_finish_progress("Détection du BPM...")
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                try:
                    bpm_val = float(tempo)
                except Exception:
                    bpm_val = float(tempo[0]) if hasattr(tempo, "__len__") and len(tempo) else 0.0
                if bpm_val and bpm_val > 0:
                    bpm = f"{round(bpm_val)} BPM"
            except Exception:
                bpm = ""

            self._key_finish(key, detail, bpm)
            self._key_finish_lists(maj_highlight, min_highlight)
        except Exception as e:
            self._key_finish(f"Erreur : {e}")

    def _key_finish_progress(self, msg):
        self.root.after(0, lambda: self.key_status_var.set(msg))

    def _key_finish(self, result, detail="", bpm=""):
        self.root.after(0, self._key_finish_gui, result, detail, bpm)

    def _key_finish_gui(self, result, detail, bpm=""):
        self.key_status_var.set("Terminé")
        self.key_result_var.set(result if result != "—" else "—")
        self.key_bpm_var.set(bpm)
        self.key_detail_var.set(detail)

    def _key_finish_lists(self, maj_highlight="", min_highlight=""):
        def go(maj_h, min_h):
            def mark(name, toms):
                items = list(toms)
                hl_maj = [i for i, t in enumerate(items) if t == maj_h]
                hl_min = [i for i, t in enumerate(items) if t == min_h]
                # on met les éléments sélectionnés en majuscules/parenthèses
                out = []
                for idx, t in enumerate(items):
                    if idx in hl_maj or idx in hl_min:
                        out.append("**" + t + "**")
                    else:
                        out.append(t)
                return ", ".join(out)
            self.key_maj_var.set("Tonalités Majeures : " + mark(maj_h, self.MAJOR_TONALITIES) + ".")
            self.key_min_var.set("Tonalités Mineures : " + mark(min_h, self.MINOR_TONALITIES) + ".")
        self.root.after(0, go, maj_highlight, min_highlight)

    def _key_finish_draw(self, chroma_mean):
        self.root.after(0, self._key_finish_draw_gui, chroma_mean)

    def _key_finish_draw_gui(self, chroma_mean):
        self._chroma = chroma_mean
        self._draw_chroma()

    def _draw_chroma(self):
        if not hasattr(self, "_chroma") or self._chroma is None:
            return
        c = self.notes_canvas
        c.delete("all")
        w = c.winfo_width() or 600
        h = c.winfo_height() or 140
        if w < 50:
            return
        vals = list(self._chroma)
        mx = max(vals) or 1
        gap = 8
        bar_w = (w - gap * 13) / 12
        for i, v in enumerate(vals):
            bh = (v / mx) * (h - 20)
            x = gap + i * (bar_w + gap)
            color = "#c0392b"
            c.create_rectangle(x, h - bh, x + bar_w, h, fill=color, outline="")
            c.create_text(x + bar_w / 2, h - 8, text=self.NOTE_NAMES[i], anchor="n", font=("Segoe UI", 8))

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---------- actions ----------
    def add_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Aucune URL", "Veuillez entrer une URL.")
            return
        item = DownloadItem(url, self)
        self.items.append(item)
        item.title = os.path.basename(urlparse(url).path) or url[:50]
        self._record(item)
        item.status = "Démarrage..."
        self._refresh_row(item)
        self.log(f"Ajouté : {url[:70]}")
        self.url_var.set("")

        threading.Thread(target=self._run, args=(item,), daemon=True).start()

    def _record(self, item):
        self.tree.insert("", "end", iid=id(item), values=(
            item.title[:40], item.status, "", "", "", ""), tags=(str(id(item)),))

    def _run(self, item):
        try:
            if is_streaming_site(item.url):
                self._run_streaming(item)
            else:
                self._run_ytdlp(item)
        except Exception as e:
            self._set_status(item, "Erreur")
            self.queue.put(("log", item, f"Erreur : {e}"))

    def _run_ytdlp(self, item):
        import yt_dlp
        from yt_dlp.networking.impersonate import ImpersonateTarget

        ffmpeg = find_ffmpeg()

        def hook(d):
            if d["status"] == "downloading":
                self._update_progress(item, d)
            elif d["status"] == "finished":
                self.queue.put(("log", item, "Téléchargement terminé."))

        opts = {
            "outtmpl": os.path.join(APP_DIR, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "impersonate": ImpersonateTarget.from_str("chrome"),
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
            "progress_hooks": [hook],
            "socket_timeout": 30,
            "retries": 3,
            "quiet": True,
            "no_warnings": True,
        }
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        if "youtube.com" in item.url or "youtu.be" in item.url:
            for exe in [r"C:\Users\Adminko\.deno\bin\deno.exe", shutil.which("deno"), shutil.which("node")]:
                if exe:
                    opts["js_runtimes"] = {exe: {}}
                    break

        self._set_status(item, "Résolution...")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(item.url, download=False)
            title = info.get("title") or item.title
            self.queue.put(("title", item, title))
            self._set_status(item, "Téléchargement")
            ydl.process_info(info)
            self._set_status(item, "Terminé")
            self.queue.put(("done", item, f"{info.get('title')}.{info.get('ext')}"))
            self.queue.put(("log", item, f"Terminé : {info.get('title')}.{info.get('ext')}"))

    def _run_streaming(self, item):
        import dl_engine

        ffmpeg = find_ffmpeg()

        # 1) Vérifier le navigateur persistant (port CDP) — onglets déjà ouverts
        try:
            self._set_status(item, "Vérification des onglets...")
            self.queue.put(("log", item, "Vérification des onglets déjà ouverts..."))
            stream, title, referer = self._find_existing_stream(dl_engine)
            if stream:
                self._start_hls(item, stream, title or item.title, referer or "https://french-stream.one/", ffmpeg)
                return
        except Exception as e:
            self.queue.put(("log", item, f"Vérification onglets : {e}"))
            self._set_status(item, "Nouveau navigateur")
            self.queue.put(("log", item, "Aucun flux actif trouvé dans les onglets ouverts."))

        # 2) Ouvrir la page dans le navigateur persistant (nouvel onglet, uniquement si aucun flux)
        self._open_in_persistent_browser(item, dl_engine, ffmpeg)

    def _find_existing_stream(self, dl_engine):
        """Renvoie (m3u8, title, referer) si un flux joue déjà dans un onglet ouvert."""
        if not self.browser_mgr.is_running():
            return None, "", ""

        p, browser = self.browser_mgr.connect()
        try:
            contexts = browser.contexts
            best_play = None
            best_title = ""
            best_url = ""
            for ctx in contexts:
                for page in ctx.pages:
                    try:
                        m3u8, playing, title = dl_engine.scan_page(page)
                    except Exception:
                        continue
                    if m3u8:
                        # préférer une page en cours de lecture
                        if playing:
                            return m3u8, title, page.url
                        if best_play is None:
                            best_play, best_title, best_url = m3u8, title, page.url
            # aucun en lecture active mais un flux existe déjà -> on le prend quand même
            if best_play:
                return best_play, best_title, best_url
            return None, "", ""
        finally:
            try:
                p.stop()
            except Exception:
                pass

    def _open_in_persistent_browser(self, item, dl_engine, ffmpeg):
        import asyncio
        from playwright.sync_api import sync_playwright

        self._set_status(item, "Ouverture navigateur...")

        def got_stream(u, title, referer):
            self.queue.put(("stream", item, (u, title, referer)))

        def worker():
            try:
                if not self.browser_mgr.ensure_running(headless=False):
                    self.queue.put(("log", item, "Impossible de démarrer le navigateur."))
                    self._set_status(item, "Erreur")
                    return
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{dl_engine.DEBUG_PORT}")
                    ctx = browser.contexts[0] if browser.contexts else browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        locale="fr-FR", viewport={"width": 1280, "height": 800})
                    page = ctx.new_page()
                    sent = set()

                    def on_resp(resp):
                        try:
                            u = resp.url
                        except Exception:
                            return
                        if ".m3u8" in u and ("master" in u or "chunk" in u or "index" in u) and u not in sent:
                            sent.add(u)
                            try:
                                _, _, t = dl_engine.scan_page(page)
                            except Exception:
                                t = ""
                            got_stream(u, t or item.title, item.url)

                    page.on("response", on_resp)
                    try:
                        page.goto(item.url, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        pass
                    self._set_status(item, "Cliquez sur PLAY si besoin...")
                    self.queue.put(("log", item, "Film ouvert dans un nouvel onglet — cliquez sur PLAY s'il ne se lance pas seul."))
                    # tenter de lancer automatiquement la lecture de la vidéo
                    try:
                        page.evaluate("""() => {
                          const v = [...document.querySelectorAll('video')].pop();
                          if (v) { v.muted = true; const pr = v.play(); if(pr && pr.catch) pr.catch(()=>{}); }
                          const btns = [...document.querySelectorAll('button')];
                          for (const b of btns) {
                            const t = (b.innerText||'').toLowerCase();
                            if (t.includes('play') || t === '▶' || t.includes('lecture') || (b.ariaLabel && b.ariaLabel.toLowerCase().includes('play'))) {
                              try { b.click(); } catch(e){}
                            }
                          }
                        }""")
                    except Exception:
                        pass
                    # surveiller en continu jusqu'à détection du flux (navigateur reste ouvert)
                    self._wait_for_stream(item, page, got_stream, sent)
            except Exception as e:
                self._set_status(item, "En attente de flux")
                self.queue.put(("log", item, f"Streaming: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _wait_for_stream(self, item, page, got_stream, sent, timeout=60 * 60 * 24):
        import dl_engine
        start = time.time()
        while time.time() - start < timeout:
            try:
                m3u8, _, title = dl_engine.scan_page(page)
            except Exception:
                m3u8, _, title = None, False, ""
            if m3u8 and m3u8 not in sent:
                sent.add(m3u8)
                got_stream(m3u8, title or item.title, item.url)
                return
            time.sleep(2)

    def _start_hls(self, item, stream, title, referer, ffmpeg):
        import dl_engine
        self._set_status(item, "Flux détecté")
        self.queue.put(("log", item, f"Titre détecté : {title}"))
        hls = dl_engine.HlsDownload(stream, title, referer, APP_DIR, ffmpeg)
        item.hls = hls
        hls.start()
        # surveiller la progression dans un thread séparé
        threading.Thread(target=self._monitor_hls, args=(item, hls), daemon=True).start()

    def _monitor_hls(self, item, hls):
        import dl_engine
        while True:
            time.sleep(0.4)
            for line in hls.read_lines():
                prog = dl_engine.parse_progress_line(line)
                if prog:
                    pct, speed, eta = prog
                    self.queue.put(("progress", item, (0, 0, 0, pct, eta)))
                    self.queue.put(("speed", item, speed))
            status = hls.poll_status()
            if status == "downloading":
                self._set_status(item, "Téléchargement")
                self.queue.put(("log", item, "Téléchargement en cours..."))
                break
            if status == "paused":
                self._set_status(item, "En pause")
                continue
            if status == "finished":
                title = hls.read_final_title()
                self.queue.put(("done", item, title))
                self.queue.put(("log", item, f"Terminé : {title}"))
                break
            if status == "error":
                self._set_status(item, "Erreur")
                if not hls.paused:
                    self.queue.put(("log", item, f"Erreur flux (code {hls.error})"))
                break
            # sinon attendre
        # continuer à surveiller la progression jusqu'à la fin
        while not hls.finished:
            time.sleep(0.4)
            for line in hls.read_lines():
                prog = dl_engine.parse_progress_line(line)
                if prog:
                    pct, speed, eta = prog
                    self.queue.put(("progress", item, (0, 0, 0, pct, eta)))
                    self.queue.put(("speed", item, speed))
            st = hls.poll_status()
            if st == "paused":
                self._set_status(item, "En pause")
            elif st == "finished":
                title = hls.read_final_title()
                self.queue.put(("done", item, title))
                self.queue.put(("log", item, f"Terminé : {title}"))
                break
            elif st == "error" and not hls.paused:
                self.queue.put(("log", item, f"Erreur flux (code {hls.error})"))
                break

    def toggle_pause(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Sélection", "Sélectionnez un téléchargement à mettre en pause.")
            return
        for i in self.items:
            if str(id(i)) in sel and getattr(i, "hls", None):
                hls = i.hls
                if i.stream_paused:
                    hls.resume()
                    i.stream_paused = False
                    i.status = "Téléchargement"
                else:
                    hls.pause()
                    i.stream_paused = True
                    i.status = "En pause"
                self._refresh_row(i)
                return
        messagebox.showinfo("Pause", "Aucun téléchargement de flux (m3u8) sélectionné.")

    def _on_close(self):
        try:
            self.browser_mgr.shutdown()
        except Exception:
            pass
        self.root.destroy()

    def _dl_stream(self, item, val):
        # remplacé par _start_hls ; conservé pour compatibilité
        if isinstance(val, tuple):
            stream, title, referer = val
        else:
            stream, title, referer = val, item.title, "https://french-stream.one/"
        self._start_hls(item, stream, title, referer, find_ffmpeg())

    # ---------- progress hooks ----------
    def _update_progress(self, item, d):
        try:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            if total:
                pct = done / total * 100
            else:
                pct = 0
            eta = d.get("eta") or ""
            self.queue.put(("progress", item, (total, done, speed, pct, eta)))
        except Exception:
            pass

    def _set_status(self, item, status):
        self.queue.put(("status", item, status))

    # ---------- UI update ----------
    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                item = msg[1]
                val = msg[2]

                if kind == "status":
                    item.status = val
                elif kind == "title":
                    item.title = val
                elif kind == "log":
                    self.log(val)
                elif kind == "done":
                    item.out_file = val
                    item.status = "Terminé"
                    item.progress = 100
                elif kind == "progress":
                    total, done, speed, pct, eta = val
                    item.progress = pct
                    item.done = done
                    item.total = total
                    item.speed = speed
                    item.eta = eta
                elif kind == "speed":
                    item.speed = val
                elif kind == "stream2":
                    pass
                elif kind == "hls_start":
                    pass
                elif kind == "stream":
                    if isinstance(val, tuple):
                        stream, title, referer = val
                    else:
                        stream, title, referer = val, item.title, "https://french-stream.one/"
                    item.title = title or item.title
                    self.queue.put(("log", item, f"Flux détecté. Téléchargement... Titre : {item.title}"))
                    threading.Thread(target=self._dl_stream, args=(item, (stream, title, referer)), daemon=True).start()

                self._refresh_row(item)
        except queue.Empty:
            pass

        # live progress
        self._refresh_progressbar()
        self.root.after(200, self._poll)

    def _refresh_row(self, item):
        if not self.tree.exists(id(item)):
            self._record(item)
        size = self._fmt_size(item.total) if item.total else ""
        speed = item.speed
        if speed and isinstance(speed, str):
            pass
        elif speed:
            speed = self._fmt_speed(speed)
        else:
            speed = ""
        prog = f"{item.progress:.1f}%" if item.progress else ""
        eta = item.eta if isinstance(item.eta, str) else ""
        self.tree.item(id(item), values=(
            item.title[:40], item.status, size, speed, prog, eta))

    def _refresh_progressbar(self):
        active = [i for i in self.items if i.status == "Téléchargement" and i.progress]
        if active:
            avg = sum(i.progress for i in active) / len(active)
        elif any(i.status == "Téléchargement" for i in self.items):
            avg = 0
        else:
            avg = 100 if any(i.status == "Terminé" for i in self.items) else 0
        self.prog_var.set(avg)
        self.status_var.set(f"{len([i for i in self.items if i.status == 'Téléchargement'])} en cours — "
                            f"{len([i for i in self.items if i.status == 'Terminé'])} terminés")

    # ---------- remove / clear ----------
    def _selected_items(self):
        sel = self.tree.selection()
        return [i for i in self.items if str(id(i)) in sel or (hasattr(i, 'title') and sel)]

    def remove_selected(self):
        sel = self.tree.selection()
        keep = []
        for i in self.items:
            if str(id(i)) in sel:
                self.tree.delete(id(i))
            else:
                keep.append(i)
        self.items = keep

    def clear_finished(self):
        keep = []
        for i in self.items:
            if i.status in ("Terminé", "Erreur"):
                self.tree.delete(id(i))
            else:
                keep.append(i)
        self.items = keep

    def clear_all(self):
        for i in list(self.items):
            if i.status in ("Terminé", "Erreur") or i.status == "En attente":
                self.tree.delete(id(i))
                self.items.remove(i)

    def open_folder(self):
        os.startfile(APP_DIR)

    # ---------- fmt ----------
    def _fmt_size(self, b):
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def _fmt_speed(self, b):
        return self._fmt_size(b) + "/s"


def main():
    root = tk.Tk()
    app = DownloaderApp(root)  # noqa: F841 — référence conservée pour la durée de vie de l'objet
    root.mainloop()


if __name__ == "__main__":
    main()
