"""Tests unitaires des fonctions "pures" du projet.

Ces tests ne nécessitent ni réseau, ni interface graphique (Tkinter),
ni navigateur (Playwright), ni sous-processus. Ils vérifient la logique
métier isolée pour garantir la non-régression lors des refactorisations.

Exécution :
    pytest -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))


# ---------------------------------------------------------------------------
# dl_engine — parse_progress_line
# ---------------------------------------------------------------------------
class TestParseProgressLine:
    """Vérification du parser des lignes de progression yt-dlp."""

    def test_ligne_valide(self):
        from dl_engine import parse_progress_line
        result = parse_progress_line("42.5%|1.2MiB/s|00:05|...|...")
        assert result is not None
        pct, speed, eta = result
        assert pct == pytest.approx(42.5)
        assert speed == "1.2MiB/s"
        assert eta == "00:05"

    def test_ligne_invalide_pas_assez_de_segments(self):
        from dl_engine import parse_progress_line
        assert parse_progress_line("trop|court") is None

    def test_pourcentage_invalide_tombe_a_zero(self):
        from dl_engine import parse_progress_line
        pct, speed, eta = parse_progress_line("abc|1MiB/s|00:01|x")
        assert pct == 0.0

    def test_valeur_vide_gere(self):
        from dl_engine import parse_progress_line
        result = parse_progress_line("|1MiB/s|00:01|x")
        assert result is not None
        assert result[0] == 0.0


# ---------------------------------------------------------------------------
# dl_engine — HlsDownload._safe_name (méthode statique)
# ---------------------------------------------------------------------------
class TestSafeName:
    """Vérification de l'assainissement des noms de fichiers."""

    def test_caracteres_invalides_retires(self):
        from dl_engine import HlsDownload
        name = HlsDownload._safe_name('film:partie"1"<HD>')
        # Aucun des caractères interdits sous Windows ne doit subsister.
        for bad in '<>:"/\\|?*':
            assert bad not in name

    def test_valeur_vide_retourne_stream(self):
        from dl_engine import HlsDownload
        assert HlsDownload._safe_name("") == "stream"
        assert HlsDownload._safe_name(None) == "stream"

    def test_longueur_limitee(self):
        from dl_engine import HlsDownload
        long_name = "x" * 500
        assert len(HlsDownload._safe_name(long_name)) <= 120


# ---------------------------------------------------------------------------
# downloader — clean_url
# ---------------------------------------------------------------------------
class TestCleanUrl:
    """Vérification du nettoyage d'URL (retrait des paramètres de playlist)."""

    def test_retire_parametre_list(self):
        from downloader import clean_url
        cleaned = clean_url("https://youtube.com/watch?v=abc&list=PL123&index=2")
        assert "list=" not in cleaned
        assert "index=" not in cleaned
        assert cleaned.startswith("https://youtube.com/watch?v=abc")

    def test_url_sans_parametre_inchangee(self):
        from downloader import clean_url
        url = "https://youtube.com/watch?v=abc"
        assert clean_url(url) == url


# ---------------------------------------------------------------------------
# app — helpers de formatage
# ---------------------------------------------------------------------------
class TestUrlStreamingDetection:
    """Vérification de la détection des sites de streaming."""

    def test_site_streaming_reconnu(self):
        from app import is_streaming_site
        assert is_streaming_site("https://example.com/french-stream/serie/1")
        assert is_streaming_site("https://vidzy.net/video/abc")
        assert is_streaming_site("https://uqload.org/embed/xyz")

    def test_site_standard_non_reconnu(self):
        from app import is_streaming_site
        assert not is_streaming_site("https://youtube.com/watch?v=abc")
        assert not is_streaming_site("https://twitter.com/user/status/1")


class TestFindFfmpeg:
    """find_ffmpeg doit toujours renvoyer une chaîne ou None sans lever."""

    def test_retour_type_correct(self):
        from app import find_ffmpeg
        result = find_ffmpeg()
        assert result is None or isinstance(result, str)
