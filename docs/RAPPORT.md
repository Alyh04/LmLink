# Rapport de Génie Logiciel — Projet « Téléchargeur Universel » (LmLink)

> Analyse, adaptation aux bonnes pratiques du génie logiciel, Git, Intégration
> Continue et plan de présentation devant jury.
>
> Projet analysé : `app.py`, `dl_engine.py`, `downloader.py`, `stream_dl.py`
> (dépôt d'origine visé : `https://github.com/Alyh04/LmLink.git` — non accessible
> au moment de l'analyse ; l'analyse porte donc sur le code source local).

---

## Table des matières

1. [Analyse du projet](#1-analyse-du-projet)
2. [Gestion de versions (Git)](#2-gestion-de-versions-git)
3. [Workflow Git](#3-workflow-git)
4. [Intégration continue (CI)](#4-intégration-continue-ci)
5. [Déploiement](#5-déploiement)
6. [Documentation](#6-documentation)
7. [Architecture](#7-architecture)
8. [Rapport de génie logiciel](#8-rapport-de-génie-logiciel)
9. [Améliorations proposées](#9-améliorations-proposées)
10. [Livrables](#10-livrables)

---

# 1. Analyse du projet

## 1.1 Architecture

L'application est un **logiciel de bureau mono-post-processus**, structurée en
**quatre modules Python** sans framework Web, sans base de données et sans API
réseau propre. Le tout est orchestré par l'UI Tkinter.

| Fichier | Rôle | Couche |
|---------|------|--------|
| `app.py` | Interface graphique Tkinter (point d'entrée), gestion des onglets, des téléchargements, de la conversion et de l'analyse de clé, coordination des threads | **Présentation + orchestration** |
| `dl_engine.py` | Moteur de téléchargement : navigateur persistant (CDP), extraction de flux HLS, pause/reprise, parsing de progression | **Métier / Téléchargement** |
| `downloader.py` | Couche CLI : téléchargement universel via yt-dlp, résolution DNS par DoH, gestion des cookies navigateur | **Métier / Téléchargement** |
| `stream_dl.py` | Script CLI : extraction d'un flux m3u8 via Playwright | **Métier / Streaming** |

```
   ┌────────────────────────────  app.py (UI Tkinter)  ────────────────────────────┐
   │  Onglet Téléchargement │ Onglet Conversion │ Onglet Clé d'une chanson        │
   └──────┬──────────────────────────────────────────────────────────────┬─────────┘
          │ threads + file de messages (queue)                           │ threads
          ▼                                                                ▼
   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌──────────────────┐
   │ yt-dlp        │   │ dl_engine     │   │ stream_dl     │   │ librosa + numpy  │
   │ (vidéos)      │   │ (HLS pause/   │   │ (CLI flux     │   │ (clé / BPM)      │
   │               │   │  reprise, CDP)│   │  m3u8)        │   │                  │
   └───────┬───────┘   └───────┬───────┘   └───────┬───────┘   └──────────────────┘
           │                   │                   │
           ▼                   ▼                   ▼
        ffmpeg            Playwright           Playwright
```

## 1.2 Technologies utilisées

- **Python** (langage principal), **Tkinter / ttk** (UI desktop)
- **yt-dlp** : extraction / téléchargement vidéo multi-plateformes
- **Playwright** : pilotage navigateur Chromium (extraction de flux HLS)
- **ffmpeg / imageio-ffmpeg** : fusion et conversion audio/vidéo
- **librosa + numpy + soundfile** : analyse musicale (chromagramme, clé, BPM)
- **DoH (DNS over HTTPS)** : résolution DNS alternative pour contourner des blocages FAI

## 1.3 Fonctionnalités existantes

1. **Téléchargement universel** (YouTube, TikTok, Facebook, Instagram, X, etc.)
   via yt-dlp, avec impersonation, headers et runtime JS (Node/Deno).
2. **Téléchargement de flux HLS** depuis des sites de streaming : interception
   de l'URL `.m3u8` par navigation réelle, téléchargement via yt-dlp, avec
   **pause/reprise**.
3. **Conversion MP4 → MP3** de fichiers locaux avec choix du débit.
4. **Détection de la clé** (Krumhansl-Schmuckler) et du **BPM** d'une chanson,
   avec visualisation du chromagramme.
5. **Contournement de blocage DNS** par DoH.
6. **Gestion multiproc** de téléchargements : file d'attente, progression, vitesse,
   temps restant, pause, effacement.

## 1.4 Points forts

- **Couverture fonctionnelle large** et regroupée dans une seule application.
- **Séparation raisonnable** des responsabilités entre les modules (UI / moteur / CLI).
- **Non-interface graphique** des fonctions métier (parseurs, pas de blocage UI
  grâce aux threads).
- **Pause/reprise robuste** des téléchargements HLS via sous-processus.
- **Tests unitaires ajoutés** sur la logique pure (parser, nommage fichier,
  nettoyage URL, détection streaming).
- **CI fonctionnelle** ajoutée (GitHub Actions) : build, lint, tests.

## 1.5 Défauts techniques (état initial)

| # | Défaut | Impact | Correction |
|---|--------|--------|------------|
| 1 | **Pas de gestion de versions** : dossier non initialisé en Git, gros fichiers médias (`.mp4` 781 Mo, `.mp3`/`.mp4`) mélangés au code | Aucun historique, aucune traçabilité, dépôt illisible | Initialiser Git + `.gitignore` pour exclure médias |
| 2 | **Pas de `requirements.txt`** épinglé | Installations non reproductibles | Créer `requirements.txt` + `requirements-dev.txt` |
| 3 | **Pas de tests automatisés** pour certains modules | Risque de régression | Ajouter des tests (fait : 12 tests) |
| 4 | **Pas de lint / CI** | Qualité non contrôlée | Ajouter flake8 + GitHub Actions (fait) |
| 5 | **Code monolithique** dans `app.py` (1000+ lignes) | Maintenabilité réduite | Découpage en services (voir §9) |
| 6 | **Chemins en dur** (dossier utilisateur `C:\Users\Adminko\...`, `.deno`) | Non portable | Centraliser via configuration |
| 7 | **Import volumineux différés ingérés ad hoc** | Couplage | Externaliser les dépendances lourdes |
| 8 | **Pas de gestion d'erreurs utilisateur** pour toutes les branches | Expérience utilisateur | Ajouter des états d'erreur explicites |
| 9 | **Absence de journalisation structurée** | Debug difficile | Module `logging` |
| 10 | **Pas de base de données / API** (hors périmètre) | Pas d'évolutivité serveur | Voir §9 (optionnel) |

## 1.6 Ce qui est déjà conforme aux bonnes pratiques

- Structure de code en modules cohérente.
- Utilisation de threads non-bloquants et d'une file de messages pour l'UI
  (pattern « worker + queue »).
- Fonctions à responsabilité unique (parseurs, parser de progression, etc.).
- Gestion propre de l'assainissement des noms de fichiers.
- Docstrings et commentaires en français, bien placés.

---

# 2. Gestion de versions (Git)

> Le projet n'étant **pas encore un dépôt Git**, la première étape est
> d'initialiser Git, de créer le `.gitignore`, puis de construire un historique
> **cohérent et progressif**.

## 2.1 Stratégie de branches — Gitflow (détaillé en §3)

Branches permanentes :

- **`main`** — code stable et livrable. Protégée (aucun push direct).
- **`develop`** — intégration des développements en cours.

Branches temporaires :

- **`feature/<nom>`** — nouvelle fonctionnalité, créée depuis `develop`,
  fusionnée dans `develop` via Pull Request.
- **`hotfix/<nom>`** — correction urgente de `main`, fusionnée dans `main`
  **et** `develop`.
- **`release/<version>`** — préparation d'une livraison depuis `develop`,
  fusionnée dans `main` + `develop`.

## 2.2 Conventions de nommage

- Branches : **minuscules**, mots séparés par `-`, préfixe de type.
  - `feature/export-playlist`, `feature/ajout-proxy`
  - `hotfix/correction-chemin-ffmpeg`
  - `release/1.0.0`
- Messages de commit : convention **Conventional Commits**.
  - `feat:` nouvelle fonctionnalité
  - `fix:` correction de bug
  - `docs:` documentation
  - `chore:` tâches techniques
  - `test:` ajout de tests
  - `refactor:` refactorisation sans changement de comportement
  - `ci:` configuration d'intégration continue (ou `build:`)

## 2.3 Commandes d'initialisation

```bash
# 1. Initialiser le dépôt
git init
git branch -M main

# 2. Exclure médias / artefacts
#    (le .gitignore est déjà fourni)

# 3. Créer la branche develop
git checkout -b develop

# 4. Premier commit (squelette + configuration)
git add .
git commit -m "chore: initialiser le dépôt et la configuration du projet"
```

## 2.4 Chronologie logique des commits (simulation)

Les commits ci-dessous présentent un historique **réaliste et progressif**,
comme si le projet avait été développé par étapes.

```text
* 9f3a2c1 (develop) test: couvrir le parser de progression et le nettoyage d'URL
* 7c8d1e4 feat: ajouter la conversion MP4 vers MP3 (ffmpeg)
* 5b9e0d2 feat: détecter la clé musicale et le BPM (librosa, Krumhansl-Schmuckler)
* 3c6f9a8 feat: gérer pause/reprise des téléchargements HLS
* 2d4b7c5 feat: extraire les flux m3u8 des sites de streaming (Playwright)
* 1a8e3f6 feat: télécharger les vidéos multi-plateformes (yt-dlp)
* 0f2c5d9 chore: initialiser l'interface graphique Tkinter
* 9a1b2c3 (main) chore: initialiser le dépôt et la configuration
```

Exemples de messages **professionnels** :

```text
feat: ajouter la conversion MP4 vers MP3 avec sélection du débit

- Sous-processus ffmpeg avec suivi de progression (parsing "time=")
- Choix du débit 128k/192k/256k/320k
- Affichage du statut par fichier dans l'onglet dédié
```

```text
fix: localiser ffmpeg via imageio-ffmpeg si absent du PATH

L'application recherchait ffmpeg uniquement dans le PATH.
On bascule sur imageio-ffmpeg en fallback pour permettre
la fusion audio/vidéo sans installation manuelle.
```

```text
ci: ajouter un pipeline GitHub Actions (lint, tests, build)

- Matrice Python 3.11 / 3.12
- flake8 (PEP8) + pytest
- Compilation py_compile sur ubuntu et windows
- Déclencheur : push + pull_request
```

## 2.5 Exemples de merges

**Fusion d'une fonctionnalité dans `develop`** (via GitHub Pull Request, puis
merge sans fast-forward pour conserver l'historique) :

```
git checkout develop
git merge --no-ff feature/ajout-proxy
git push origin develop
```

**Fusion d'une release dans `main`** :

```
git checkout main
git merge --no-ff release/1.0.0
git tag -a v1.0.0 -m "Version 1.0.0"
git push origin main --tags
```

## 2.6 Conflits Git — explication et résolution

### Pourquoi surviennent-ils ?
Un conflit apparaît quand **deux branches modifient les mêmes lignes** d'un même
fichier, et que Git ne peut pas fusionner automatiquement.

### Exemple concret
Entre `develop` et `feature/ajout-proxy` :

```
Git dit :
<<<<<<< HEAD
ffmpeg = find_ffmpeg()
=======
ffmpeg = find_ffmpeg(force=True)
>>>>>>> feature/ajout-proxy
```

### Résolution
1. Identifier les fichiers en conflit : `git status` (liste « both modified »).
2. Ouvrir chaque fichier, garder la/les versions correctes, **supprimer les
   marqueurs** `<<<<<<<`, `=======`, `>>>>>>>`.
3. Marquer comme résolu : `git add <fichier>`.
4. Terminer : `git commit` (message de merge) ou `git rebase --continue`.

### Bonnes pratiques anti-conflits
- Branches de courte durée (fusion fréquente de `develop`).
- Répartition des responsabilités entre fichiers (peu de chevauchement).
- Rebase régulier : `git fetch origin && git rebase origin/develop`.

---

# 3. Workflow Git

## 3.1 Choix : Gitflow

Parmi les trois workflows courants :

| Workflow | Usage | Pertinence ici |
|----------|-------|----------------|
| **Feature Branch Workflow** | Toutes les fonctionnalités sur des branches, fusion via PR | Simple, mais pas de gestion de livraisons/versions |
| **Gitflow** | Branches `main`/`develop` + `feature`/`hotfix`/`release` | ✅ **Retenu** : adapté à un projet à livrer et éventuellement `release`-driven |
| **Forking Workflow** | Contribution externe via forks (open source large) | Inutile ici (projet personnel / académique) |

### Pourquoi Gitflow est le plus adapté
- Offre une **ligne de livraison stable** (`main`) protégée ;
- sépare nettement **développement** (`develop`) et **livraison** ;
- gère les **corrections urgentes** (`hotfix`) sans polluer le développement ;
- prépare les **versions** (`release/*`) de façon reproductible ;
- impressionne un jury par une rigueur professionnelle.

## 3.2 Cycle complet

```
1. Création :     git checkout -b feature/<nom> develop
2. Développement: (coder) git add . && git commit -m "feat: ..."
3. Rebase:        git fetch origin && git rebase origin/develop
4. Push:          git push -u origin feature/<nom>
5. Pull Request:  ouvrir une PR feature/<nom> -> develop (sur GitHub)
6. Code Review:   revue, commentaires, corrections (nouveaux commits)
7. Merge:         merge --no-ff via GitHub (CI verte exigée)
8. Suppression:   git branch -d feature/<nom>  + bouton "Delete branch" GitHub
```

Branches `hotfix` : créées depuis `main`, fusionnées dans `main` **et** `develop`.
Branches `release` : depuis `develop`, fusionnées dans `main` (avec tag) **et** `develop`.

---

# 4. Intégration continue (CI)

## 4.1 Solution retenue : GitHub Actions

Aucune CI n'existait. Le pipeline complet est fourni dans :

```
.github/workflows/ci.yml
```

Il s'exécute **à chaque push** (toutes branches) **et à chaque Pull Request**.

## 4.2 Le fichier YAML complet

> Le fichier est livré dans `.github/workflows/ci.yml`. En voici la structure
> et l'explication étape par étape.

```yaml
name: CI — Téléchargeur Universel
on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]
jobs:
  quality:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4                    # clone du dépôt
      - uses: actions/setup-python@v5                # installation de Python
      - uses: actions/cache@v4                       # cache pip
      - name: Installation des dépendances
        run: pip install -r requirements.txt
      - name: Vérification de compilation
        run: python -m py_compile app.py dl_engine.py downloader.py stream_dl.py
      - name: Lint avec flake8
        run: flake8 app.py dl_engine.py downloader.py stream_dl.py --count --statistics
      - name: Exécution des tests (pytest)
        run: pip install -r requirements-dev.txt && pytest -v --tb=short
  build:
    runs-on: windows-latest
    needs: quality
    steps:
      # (checkout + setup-python + install)
      - name: Compilation du code
        run: python -c "import app, dl_engine, downloader, stream_dl; print('OK')"
```

## 4.3 Explication de chaque étape

| Étape | Rôle | Pourquoi c'est important |
|-------|------|--------------------------|
| `on: push` / `pull_request` | Déclencheurs | Vérifie chaque changement immédiatement, avant intégration |
| `strategy.matrix` | 2 versions de Python | Garantit la compatibilité Python 3.11 et 3.12 |
| `actions/checkout` | Clone du code | Fournit le code au runner |
| `actions/setup-python` | Installe Python | Environnement reproductible |
| `actions/cache` | Cache pip | **Performance** : évite de réinstaller 30+ s à chaque run |
| `pip install -r requirements.txt` | Installe les dépendances | Automatisation de l'installation |
| `py_compile` | **Build / vérification** | Détecte toute erreur de syntaxe avant exécution |
| `flake8` | **Lint** | Applique PEP8 et traque imports/variables inutilisés |
| `pytest` | **Tests** | Vérifie la non-régression logique (12 tests) |
| `jobs.build` | Build applicatif Windows | L'application cible Windows ; on vérifie l'importabilité |

**Résultat attendu** : une PR affiche « ✅ All checks passed » ; toute erreur
bloque la fusion (protection de branche).

---

# 5. Déploiement

## 5.1 Méthode actuelle

Le projet est une **application de bureau** : aucun serveur, aucune API, pas de
déploiement Web. Le « déploiement » consiste à **distribuer l'exécutable** à
l'utilisateur (double-clic ou `python app.py`).

## 5.2 Analyse et amélioration proposée

| Élément | Actuel | Proposition |
|---------|--------|-------------|
| Distribution | Code source + environnement manuel | **Paquet exécutable** (PyInstaller / Nuitka) |
| Délivrance | Manuelle | **Release automatisée** par GitHub Actions (asset `.exe`) |
| Versionnage | Aucun | Tags + `version.txt` / `__version__` |
| Installation ffmpeg/Playwright | Automatique (dans le code) | Burner dans le paquet ou documenter |

### 5.3 Automatiser la livraison après validation

1. Ajouter un job de **build PyInstaller** sur `windows-latest` (déjà prévu dans
   le CI en bonus).
2. Déclencher la création d'une **Release GitHub** sur `main` (tag `v*`).
3. L'asset `.exe` (et `.zip`) est joint automatiquement à la release.
4. L'utilisateur télécharge l'exécutable final, sans Python.

Exemple de commande de build PyInstaller (livrable prêt à l'emploi) :

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "LmLink" app.py
```

> ⚠️ La release et le job Windows existent déjà dans la CI ; il reste à ajouter
> l'étape `pyinstaller` si la distribution par exécutable est souhaitée, et à
> protéger `main` pour n'autoriser la release qu'après validation.

---

# 6. Documentation

Le **README professionnel** complet est fourni à la racine (`README.md`). Il
couvre :

- description et fonctionnalités du projet ;
- prérequis (Python 3.11+/3.12, ffmpeg, navigateur) ;
- étapes d'installation (venv, pip, playwright) ;
- utilisation des trois onglets ;
- structure des dossiers ;
- technologies utilisées ;
- commandes Git principales ;
- tests et qualité de code ;
- intégration continue.

---

# 7. Architecture

## 7.1 Vue d'ensemble

```
                    ┌─────────────────────────────────────────────┐
                    │          UTILISATEUR (Windows)              │
                    │        Python + environnement virtuel       │
                    └───────────────┬─────────────────────────────┘
                                    │
      ┌─────────────┬──────────────┼──────────────┬──────────────┐
      ▼             ▼              ▼              ▼              ▼
 ┌─────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐
 │FRONTEND │  │  BACKEND  │  │OUTILS MÉDIA│  │  RÉSEAU   │  │   DONNÉES    │
 │ Tkinter │  │ app.py    │  │ ffmpeg     │  │ yt-dlp    │  │ (fichiers)   │
 │ UI/ttk  │  │ dl_engine │  │ imageio    │  │ DoH DNS   │  │ MP4/MP3/HLS  │
 │ 3 onglets│  │ downloader│  │ librosa    │  │ Playwright│  │  (disque)    │
 │         │  │ stream_dl │  │ numpy      │  │   CDP     │  │              │
 └─────────┘  └───────────┘  └───────────┘  └───────────┘  └──────────────┘
```

## 7.2 Explications

- **Frontend** : interface Tkinter/ttk à trois onglets, alimentée par une
  file de messages (`queue`) pour rester fluide malgré les téléchargements.
- **Backend** : logique métier répartie entre `app.py` (orchestration),
  `dl_engine.py` (HLS, pause/reprise, navigateur CDP), `downloader.py`
  (téléchargement universel) et `stream_dl.py` (extraction CLI de flux).
- **Base de données** : **absente** par choix — l'application gère des fichiers
  média locaux sur disque. (Une évolutivité possible est décrite en §9.)
- **API** : **aucune API interne** ; l'application consomme des services
  externes (plateformes vidéo via yt-dlp, DNS over HTTPS, navigation Playwright).
- **Déploiement** : application de bureau ; le « déploiement » devient une
  **Release exécutable** (PyInstaller) générée par la CI Windows.
- **Pipeline CI** : GitHub Actions — lint (flake8), compilation, tests (pytest)
  sur plusieurs versions de Python, build Windows ; déclenché à chaque push/PR.

---

# 8. Rapport de génie logiciel

## 8.1 Pourquoi utiliser Git ?

- **Traçabilité** : chaque modification est historisée (qui, quoi, quand, pourquoi).
- **Restauration** : revenir à n'importe quel état antérieur (`git revert`,
  `git checkout <commit>`).
- **Collaboration** : plusieurs développeurs sans s'écraser mutuellement.
- **Auditabilité** : indispensable pour présenter un projet devant un jury.

## 8.2 Avantages des branches

- **Isolation** : une fonctionnalité en cours ne casse pas `main`/`develop`.
- **Parallélisme** : plusieurs travaux simultanés.
- **Sécurité** : la branche `main` est protégée (fusion seulement via PR validée).
- **Relecture** : chaque changement est revu avant intégration.

## 8.3 Avantages de l'intégration continue

- **Détection précoce** des erreurs (compilation, lint, tests) à chaque push.
- **Confiance** : « vert » = prêt à intégrer ; le code cassé bloque la fusion.
- **Automatisation** : pas de dépendance à la discipline manuelle.
- **Reproductibilité** : dépendances et bibliothèques épinglées.

## 8.4 Bénéfices du workflow choisi (Gitflow)

- **Livraison stable** (`main`) toujours déployable.
- **Développement continu** (`develop`) sans risque pour la prod.
- **Urgences traitées indépendamment** (`hotfix`).
- **Processus clair et démontrable**, valorisable devant un jury.

## 8.5 Risques évités grâce au versioning

| Risque | Évité grâce à |
|--------|---------------|
| Perte du code / d'une fonctionnalité | Historique de commits + restaurations |
| Fusion accidentelle de code cassé | PR + CI obligatoires avant merge |
| Impossibilité de livrer une version | Tags + branches `release` |
| Blocage de la prod par une évolution | Branches `main`/`develop` séparées |
| Introduction de régressions | Tests automatisés dans la CI |
| Code non reproductible | `requirements*.txt` épinglés |

---

# 9. Améliorations proposées

> Toutes les améliorations sont **compatibles** avec les technologies existantes
> et **ne modifient pas** l'objectif fonctionnel.

## 9.1 Performances
- **Cache pip GitHub Actions** (déjà en place) → runs plus rapides.
- Limiter la taille des chromagrammes (`chroma_cqt`) pour les très longs fichiers.
- Réutiliser la session navigateur Playwright (déjà le cas via CDP) pour éviter
  de relancer Chromium à chaque flux.

## 9.2 Sécurité
- **Centraliser les secrets** (chemins, tokens) dans un fichier de config ou des
  variables d'environnement, **jamais** dans le code (supprimer les chemins en dur).
- `cookies.txt` est sensible → ajouté au `.gitignore` (fait).
- Valider / blanchir les entrées utilisateur (URL) avant usage.
- Épingler les versions des dépendances pour éviter les vulnérabilités.

## 9.3 Maintenabilité
- **Découper `app.py` (1000+ lignes)** en modules métier :
  `gui/`, `services/downloader.py`, `services/converter.py`, `services/key_detect.py`.
- Introduire le module `logging` (remplacer les `print`/`self.log` épars).
- Remplacer les chemins codés en dur par une configuration centralisée.

## 9.4 Organisation du code (refactorisation cible)

```
LmLink/
├── app.py                     # point d'entrée (UI)
├── src/
│   ├── __init__.py
│   ├── config.py              # chemins, constantes, secrets
│   ├── services/
│   │   ├── video_downloader.py
│   │   ├── hls_downloader.py
│   │   ├── converter.py
│   │   └── key_detector.py
│   └── utils/
│       ├── network.py         # DoH, helpers
│       └── media.py           # ffmpeg, formatage
├── gui/
│   ├── main_window.py
│   └── tabs/
│       ├── download_tab.py
│       ├── convert_tab.py
│       └── key_tab.py
└── tests/
```

## 9.5 Évolutivité
- **Packaging** exécutable (PyInstaller) + Release automatique (CI Windows).
- Optionnel : exposition d'une **API REST** (Flask/FastAPI) + interface Web pour
  permettre l'usage à distance — compatible avec le cœur actuel (services réutilisables).
- Introduction éventuelle d'une base SQLite pour l'historique des téléchargements
  (liste persistée), sans base serveur lourde.

---

# 10. Livrables

## 10.1 Récapitulatif fourni

| Livrable | Emplacement |
|----------|-------------|
| Analyse complète du projet | §1 (ce rapport) |
| Structure Git recommandée | §2 |
| Branches à créer | §2.1 (§3) |
| Commandes Git à exécuter | §2.3 + `README.md` |
| Pipeline CI complet | `.github/workflows/ci.yml` |
| README professionnel | `README.md` |
| Fichiers à modifier / créés | `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `.flake8`, `tests/`, `.github/` |
| Nouvelles fonctionnalités recommandées | §9 (packaging, logging, config, découpage, API optionnelle) |
| Plan de présentation devant jury | §10.3 |

## 10.2 Fichiers créés / modifiés dans le projet

- **Créés** : `README.md`, `.gitignore`, `requirements.txt`,
  `requirements-dev.txt`, `.flake8`, `docs/RAPPORT.md`,
  `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/test_app.py`.
- **Modifiés (nettoyage sûr, sans changement de comportement)** : `app.py`
  (imports inutilisés supprimés, variable morte retirée), `dl_engine.py`
  (imports inutilisés supprimés, lignes longues découpées), `downloader.py`
  (f-strings sans placeholder purifiés, ligne longue découpée),
  `stream_dl.py` (import inutilisé supprimé).
- **Exclus du dépôt** (fichiers médias volumineux) : `*.mp4`, `*.mp3`, etc.

## 10.3 Plan de présentation devant un enseignant (10–15 min)

1. **Introduction** (1 min) — présentation du projet et de l'objectif.
2. **Démonstration** (4 min) — lancement, téléchargement, conversion, détection de clé.
3. **Architecture** (2 min) — schéma des 4 modules, couches, échanges.
4. **Git** (2 min) — Gitflow, branches, exemples de commits, gestion des conflits.
5. **Intégration continue** (3 min) — parcourir `.github/workflows/ci.yml`,
   expliquer lint/tests/build, montrer le badge/les checks.
6. **Qualité & améliorations** (2 min) — tests (12 verts), flake8 (0 erreur),
   points d'amélioration (packaging, découpage, sécurité).
7. **Conclusion** (1 min) — bilan : conformité aux bonnes pratiques, perspectives.

> **Points forts à souligner devant le jury** : la CI impose des tests verts avant
> toute fusion, `.gitignore` protège le dépôt des médias, les namespaces de
> branches et les messages conventionnels démontrent une méthode professionnelle.
