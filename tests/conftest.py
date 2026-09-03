import os
import sys

# Ajoute la racine du projet dans le chemin d'import Python
# afin que les modules (app, dl_engine, downloader, stream_dl)
# puissent être importés par les tests.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
