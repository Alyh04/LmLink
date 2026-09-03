# Téléchargeur Universel (LmLink)

Application de bureau **Python / Tkinter** permettant de télécharger des vidéos
et de l'audio depuis de nombreuses plateformes (YouTube, TikTok, Facebook,
Instagram, X, sites de streaming…), de **convertir** des fichiers vidéo en MP3,
et de **détecter la tonalité (clé)** et le **BPM** d'une chanson.

> 🇫🇷 Interface en français · Disponible sur Windows.

---

## Sommaire

1. [Description du projet](#description-du-projet)
2. [Fonctionnalités](#fonctionnalités)
3. [Prérequis](#prérequis)
4. [Installation](#installation)
5. [Utilisation](#utilisation)
6. [Structure des dossiers](#structure-des-dossiers)
7. [Technologies utilisées](#technologies-utilisées)
8. [Commandes Git principales](#commandes-git-principales)
9. [Tests & Qualité de code](#tests--qualité-de-code)
10. [Intégration continue](#intégration-continue)

---

## Description du projet

**LmLink — Téléchargeur Universel** est un outil graphique qui centralise :

- le **téléchargement de vidéos** et d'audio depuis de nombreuses plateformes,
  y compris les sites de streaming protégés (extraction du flux HLS `.m3u8`
  via navigation réelle) ;
- la **conversion** de fichiers vidéo (`.mp4`, `.mkv`, …) en audio MP3 ;
- la **détection de la clé musicale** (majeure/mineure via l'algorithme de
  Krumhansl-Schmuckler) et du **BPM** d'un fichier audio/vidéo.

L'application contourne également certains blocages de fournisseurs d'accès à
Internet grâce à une résolution DNS alternative par **DoH** (DNS over HTTPS).

---

## Fonctionnalités

| Module | Fonctionnalités |
|--------|----------------|
| **Téléchargement** | Téléchargement multi-plateformes (yt-dlp), flux HLS des sites de streaming, téléchargements multiples simultanés, progression en temps réel, vitesse, temps restant, pause/reprise des flux, gestion de la liste (supprimer, effacer les terminés) |
| **Conversion** | Conversion de tout fichier vidéo en MP3 (ffmpeg), choix du débit (128k–320k), suivi de progression par fichier |
| **Clé d'une chanson** | Détection de la tonalité majeure/mineure, affichage du BPM, visualisation du chromagramme, % de confiance |

---

## Prérequis

- **Système** : Windows (l'interface Tkinter est disponible nativement).
- **Python** : 3.11 ou 3.12 recommandé (testé jusqu'à 3.14). *Tkinter est inclus.*
- **ffmpeg** : optionnel mais fortement recommandé (fusion audio/vidéo,
  conversion MP3). L'application tente de l'installer ou de le localiser
  automatiquement via `imageio-ffmpeg`.
- **Navigateur** : Chrome / Edge (pour les fonctionnalités de streaming et la
  connexion aux sites protégés via Playwright).

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/Alyh04/LmLink.git
cd LmLink
```

### 2. Créer un environnement virtuel (recommandé)

```bash
python -m venv venv
# Windows — activation :
venv\Scripts\activate
# Linux / macOS :
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Installer le navigateur Playwright (bonus streaming)

```bash
playwright install chromium
```

### 5. Lancer l'application

```bash
python app.py
```

---

## Utilisation

1. **Onglet « Téléchargement »** : collez une URL, appuyez sur *Télécharger*.
   Le lien est analysé, puis téléchargé. Pour les sites de streaming, un
   navigateur s'ouvre : cliquez sur **PLAY** et le flux est intercepté et
   téléchargé (pause/reprise possible).
2. **Onglet « Conversion MP4→MP3 »** : choisissez une vidéo, sélectionnez la
   qualité et lancez la conversion.
3. **Onglet « Clé d'une chanson »** : choisissez un fichier audio/vidéo et
   lancez l'analyse de la tonalité et du BPM.

Les fichiers sont enregistrés dans le dossier de l'application (bouton
*Ouvrir le dossier*).

---

## Structure des dossiers

```
LmLink/
├── app.py                  # Interface graphique Tkinter (point d'entrée)
├── dl_engine.py            # Moteur de téléchargement (navigateur persistant CDP, HLS, pause/reprise)
├── downloader.py           # Couche CLI : téléchargement universel via yt-dlp
├── stream_dl.py            # Script CLI : extraction d'un flux m3u8 via Playwright
├── requirements.txt        # Dépendances de production
├── requirements-dev.txt    # Dépendances de développement (tests, lint)
├── .flake8                 # Configuration du linter flake8
├── .gitignore              # Fichiers exclus du dépôt
├── tests/                  # Tests unitaires
│   ├── conftest.py
│   └── test_app.py
└── .github/
    └── workflows/
        └── ci.yml          # Pipeline d'intégration continue (GitHub Actions)
```

---

## Technologies utilisées

| Technologie | Rôle |
|-------------|------|
| **Python** | Langage principal |
| **Tkinter / ttk** | Interface graphique de bureau |
| **yt-dlp** | Extraction et téléchargement vidéo multi-plateformes |
| **Playwright** | Automatisation navigateur (extraction de flux HLS sur sites streaming) |
| **ffmpeg / imageio-ffmpeg** | Fusion audio/vidéo et conversion MP4→MP3 |
| **librosa + numpy** | Analyse audio (chromagramme, détection de clé, BPM) |
| **soundfile** | Lecture de fichiers audio pour l'analyse |
| **Git / GitHub Actions** | Gestion de versions et intégration continue |

---

## Commandes Git principales

> Le projet suit le workflow **Gitflow** (voir le rapport). Les commandes
> typiques sont listées ci-dessous.

```bash
# Créer et basculer sur une branche de fonctionnalité
git checkout -b feature/ajout-export-playlist develop

# Travailler : ajouter puis valider
git add .
git commit -m "feat: ajouter l'export de la liste de téléchargement"

# Publier la branche et ouvrir une Pull Request
git push -u origin feature/ajout-export-playlist

# Rebaser sur develop pour intégrer les dernières évolutions
git fetch origin
git rebase develop

# Fusionner après validation de la PR (via GitHub)
# puis supprimer la branche locale
git branch -d feature/ajout-export-playlist
```

---

## Tests & Qualité de code

```bash
# Installer les dépendances de dev
pip install -r requirements-dev.txt

# Exécuter les tests unitaires
pytest -v

# Lancer le linter
flake8 app.py dl_engine.py downloader.py stream_dl.py
```

Résultat actuel : **12 tests, tous verts** · **flake8 : 0 erreur**.

---

## Intégration continue

Un pipeline **GitHub Actions** (`.github/workflows/ci.yml`) s'exécute à chaque
**push** et **Pull Request** :

1. **Checkout** du code ;
2. Configuration **Python** (matrice 3.11 / 3.12) ;
3. **Cache pip** pour accélérer ;
4. **Installation automatique des dépendances** ;
5. **Vérification de compilation** (`py_compile`) ;
6. **Lint** (flake8, conventions PEP8) ;
7. **Tests unitaires** (pytest) ;
8. **Build applicatif** sur `windows-latest`.

---

## Licence

Voir le fichier de licence du projet (à définir selon le souhait de l'auteur).
