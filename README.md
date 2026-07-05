# OSINT-OFDF — Pipeline de détection d'annonces suspectes

Pipeline OSINT conteneurisé d'aide à l'enquête, développé pour l'Office fédéral
de la douane et de la sécurité des frontières (OFDF). Il parcourt des plateformes
de petites annonces, en extrait les offres et produit pour chacune un **signal de
suspicion argumenté** (tabac, alcool, espèces protégées, viande, contrefaçon,
armes), ancré sur un corpus de règles douanières. Le système produit des signaux,
jamais des décisions : la validation reste à l'enquêteur, et chaque étape est tracée.

Version : 0.9.0

## Démarrage automatisé (recommandé)

Un script de démarrage prépare tout en une commande : création du `.env`,
construction et démarrage de la pile, attente de l'API, provisionnement du RAG,
puis vérification. Il ne dispense pas d'installer les prérequis (Docker ; Ollama
en mode local — voir ci-dessous).

```bash
# Windows (PowerShell, aucune dépendance) :
powershell -ExecutionPolicy Bypass -File .\start.ps1
#   ajouter -Dev pour inclure les marchés de démonstration

# Git Bash / Linux / macOS :
./start.sh          # ou ./start.sh --dev
```

La procédure manuelle détaillée ci-dessous reste valable pour qui veut
comprendre ou contrôler chaque étape.

## Prérequis logiciels

Installer et démarrer **avant** toute autre étape :

- **Docker Desktop** (fournit `docker` et `docker compose`), lancé et actif.
- **Selon le mode de modèle choisi** (voir la section « Choix du fournisseur de
  modèle » ci-dessous) :
  - *mode local* : **Ollama** installé sur l'hôte, avec le modèle `qwen3:8b`
    (`ollama pull qwen3:8b`, ~5 Go). Ollama doit tourner pendant l'utilisation.
  - *mode cloud* : une **clé d'API** du fournisseur (p. ex. Anthropic). Aucune
    installation d'Ollama requise.

## Choix du fournisseur de modèle (local ou cloud)

Le système fonctionne avec un modèle **local** (souveraineté des données, défaut)
ou **cloud** (aucune installation, plus rapide selon la machine). Ce choix se fait
dans `config.yaml`, champ `topologie`, et détermine ce qu'il faut préparer.

| Mode | `topologie` | À préparer | Données transmises à un tiers |
|---|---|---|---|
| **Local** (défaut) | `locale` | Ollama + `qwen3:8b` sur l'hôte | Aucune |
| **Cloud** | `cloud` | `LLM_API_KEY` dans `.env` | Oui — déclenche l'avis LPD |

Un modèle **différent par agent** est possible via le bloc `per_agent` de
`config.yaml` : par exemple LLM-SCORE en local et LLM-BROWSE en cloud.

> **Important (souveraineté / LPD).** Router ne serait-ce qu'**un seul agent**
> vers un fournisseur cloud (via `per_agent`) constitue déjà une transmission de
> données à un tiers, **même si `topologie` reste `locale`**. En contexte OFDF,
> toute bascule cloud doit être un choix conscient et journalisé. Pour une
> souveraineté totale, garder `topologie: locale` et aucun agent routé en cloud.

Basculer le système entier en cloud (p. ex. pour une démonstration) :

```yaml
# config.yaml
topologie: cloud     # au lieu de "locale"
```

et renseigner `LLM_API_KEY` dans `.env`. Toute modification de `config.yaml`
ou de `.env` exige de **recréer le conteneur** : `docker compose up -d app`.

## Installation pas à pas

```bash
# 1. Secrets et paramètres (jamais versionnés)
cp .env.example .env
#    Éditer .env : POSTGRES_PASSWORD et ADMIN_PASSWORD sont requis.
#    En mode cloud, renseigner aussi LLM_API_KEY (ex. clé Anthropic « sk-ant-... »,
#    sans guillemets). En mode local, LLM_API_KEY reste vide.
#    /!\  Sous Windows, vérifier que le fichier s'appelle bien « .env » et non
#    « .env.txt » : ls -la .env

# 2. Construction et démarrage du noyau (postgres + qdrant + app)
docker compose up -d --build
#    Le schéma PostgreSQL est créé automatiquement au premier démarrage.
#    Le premier build est long (dépendances Python + navigateur Playwright).

# 3. Provisionnement de la base vectorielle (RAG), une seule fois
docker compose exec app python scripts/init_qdrant.py    # crée les collections
docker compose exec app python scripts/ingest_rules.py   # charge data/rules/*.md
#    /!\  Au premier « ingest_rules », le modèle d'embeddings (~2,25 Go) se
#    télécharge : l'étape peut sembler figée plusieurs minutes. C'est normal,
#    laisser terminer. Le corpus de règles doit être présent dans data/rules/.

# 4. Vérification du déploiement
docker compose exec app python scripts/smoke_test.py
#    Doit afficher la topologie active et « OK » pour postgres, qdrant ET model.
#    Si « model » est KO : en local, vérifier qu'Ollama tourne (ollama list) ;
#    en cloud, vérifier LLM_API_KEY et que config.yaml est bien en « cloud »
#    (puis « docker compose up -d app » pour recharger).

# 5. Accès
#    Interface enquêteur      : http://localhost:8000/ui
#    Console d'administration : http://localhost:8000/admin   (ADMIN_PASSWORD requis)
#    Documentation d'API      : http://localhost:8000/docs
```

### Vérifier que le RAG est bien peuplé (recommandé)

Qdrant n'est pas exposé sur l'hôte (accessible uniquement sur le réseau Docker) :
la vérification se fait donc depuis le conteneur `app`.

```bash
docker compose exec app python -c "from qdrant_client import QdrantClient; c=QdrantClient(host='qdrant', port=6333); print('points:', c.get_collection('customs_rules').points_count)"
```

Un nombre de points supérieur à zéro confirme que les règles sont ingérées. S'il
vaut 0, relancer `ingest_rules.py` et vérifier le contenu de `data/rules/`.

### Prise en compte des modifications

| Fichier modifié | Commande pour appliquer |
|---|---|
| `config.yaml` | `docker compose restart app` (relit la config montée en volume) |
| `.env` | `docker compose up -d app` (recrée le conteneur, recharge l'environnement) |
| `prompts/` | `docker compose restart app` |
| `src/` (code) | `docker compose up -d --build app` (reconstruit l'image) |
| `data/rules/` | `docker compose exec app python scripts/ingest_rules.py` |

> **Pourquoi deux commandes différentes ?** `up -d` compare la *définition* du
> service (image, variables du `.env`, montages) et ne recrée le conteneur que
> si elle a changé — le **contenu** d'un fichier monté en volume lui est
> invisible : modifier `config.yaml` puis `up -d app` ne fait donc **rien**.
> `restart` redémarre le processus, qui relit sa configuration — mais sans
> recharger le `.env`. En cas de doute :
> `docker compose up -d --force-recreate app` couvre les deux cas.

## Démonstration sur les marchés fictifs (profil `dev`)

Les plateformes de test `fake_market` et `mock_shop` ne font **pas** partie du
cœur de production : elles sont isolées dans le profil `dev`. Toute recherche de
démonstration qui les vise exige donc de démarrer la pile avec ce profil :

```bash
docker compose --profile dev up -d --build
```

Sans ce profil, une recherche Mode A sur `fake_market` (ou `mock_shop`) échoue
avec `net::ERR_NAME_NOT_RESOLVED` : le conteneur du marché fictif n'est pas
démarré, son nom d'hôte n'est donc pas résolu sur le réseau Docker.

En Git Bash / Linux / macOS, le script `./start.sh --dev` réalise ce démarrage
en une commande.

### Dérouler la démonstration

Une fois la pile démarrée avec le profil `dev`, ouvrir l'interface enquêteur :
**http://localhost:8000/ui**

- **Mode A (surveillance)** : la plateforme `fake_market` est présélectionnée
  dans la liste — cliquer « Lancer la recherche », puis observer les annonces
  collectées, leurs scores argumentés et le rapport généré.
- **Mode B (exploration)** : cocher un site autorisé, saisir éventuellement une
  requête ciblée (ex. « cigarettes » — LLM-EXPAND en dérive des formulations
  voisines transmises à l'agent de navigation). Un champ **vide** déclenche une
  exploration **libre** : tout est relevé, le tri se fait au score seul.

Les marchés fictifs restent consultables directement dans un navigateur :
**http://localhost:8001** (`fake_market`) et **http://localhost:8002**
(`mock_shop`) — utile pour comparer ce que voit l'humain et ce que relève le
pipeline.

> **Note.** La suite de tests (`docker compose exec app python -m pytest -q`)
> ne nécessite **pas** le profil `dev` : les fixtures HTML et les marchés
> fictifs sont embarqués dans l'image au build, la suite s'exécute hors ligne
> sur le cœur seul.

## Exécution hôte (démonstration LLM-BROWSE en navigateur visible)

La quasi-totalité du système tourne dans Docker : aucun environnement Python
local n'est requis. **Seule exception** : les scripts qui ouvrent un navigateur
*visible* (`scripts/demo_soutenance.py`, `scripts/browse_demo.py`) doivent
s'exécuter sur l'hôte, car le conteneur `app` n'a pas d'affichage graphique.

Préparer l'environnement hôte une seule fois :

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows / Git Bash ; Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export LLM_API_KEY=...              # LLM-BROWSE peut viser un fournisseur cloud
```

Puis, environnement activé :

```bash
PYTHONPATH=src python scripts/demo_soutenance.py
```

## Profils de déploiement

Le profil par défaut ne démarre que le cœur (`postgres`, `qdrant`, `app`). Les
marchés fictifs et la planification sont isolés dans des profils séparés, pour
ne jamais tourner en production sans décision explicite.

```bash
# Cœur seul (production)
docker compose up -d --build

# Démonstration : cœur + marchés fictifs (ports hôte 8001 et 8002)
docker compose --profile dev up -d --build

# Planification par n8n
docker compose --profile full up -d
```

| Service | Profil | Rôle |
|---|---|---|
| app | (défaut) | API, pipeline d'analyse, extracteurs, interfaces |
| postgres | (défaut) | Mémoire épisodique, scores, journal d'audit |
| qdrant | (défaut) | Base vectorielle (RAG) |
| n8n | full | Planification des exécutions périodiques |
| fake_market | dev | Marché fictif déterministe (évaluation), port 8001 |
| mock_shop | dev | Marché fictif à sélecteurs (démo LLM-CODE), port 8002 |

## Topologies de modèle

La topologie est un paramètre de `config.yaml` (`topologie: locale | centrale | cloud`),
sans modification de code :

- **locale** : Ollama sur l'hôte, aucun transfert à un tiers (défaut).
- **centrale** : serveur d'inférence interne compatible OpenAI, via `api_base`.
- **cloud** : fournisseur externe ; toute transmission déclenche un avertissement
  de consentement, évalué par agent.

Un modèle distinct peut être attribué à chaque agent via le bloc `per_agent`.

## Résolution des problèmes courants

| Symptôme | Cause probable | Action |
|---|---|---|
| `.env not found` au `up` | Étape 1 non faite | `cp .env.example .env` |
| `service "app" is not running` | Pile non démarrée | `docker compose up -d --build` puis `docker compose ps` |
| `net::ERR_NAME_NOT_RESOLVED` sur `fake_market`/`mock_shop` | Marché fictif non démarré (profil `dev`) | `docker compose --profile dev up -d` |
| `Aucun fichier .md dans /app/data/rules` | `data/` non monté ou corpus absent | Vérifier le montage `./data:/app/data` (compose) et le contenu de `data/rules/` |
| `model` KO, `topologie=locale` | Ollama non démarré | Lancer Ollama, `ollama list` doit montrer `qwen3:8b` |
| `model` KO en cloud | Clé absente / config non rechargée | Vérifier `LLM_API_KEY` et `topologie: cloud`, puis `docker compose up -d app` |
| `'ascii' codec can't encode` à l'appel du modèle | Clé d'API absente ou caractère parasite dans `.env` | Vérifier `LLM_API_KEY` (`grep LLM_API_KEY .env`) |
| Score toujours nul | RAG vide | `ingest_rules.py` ; vérifier `points_count` |
| Changement de `config.yaml` sans effet | Conteneur non recréé | `docker compose up -d app` |

## Évaluation

```bash
docker compose exec app python scripts/evaluate.py
```

Compare le pipeline (LLM + RAG) à une référence par mots-clés sur le jeu de
284 annonces annotées. Produit `data/eval/results.json` et `data/eval/metrics.json`.

## Tests

```bash
docker compose exec app python -m pytest -q
```

Couvrent extraction, garde-fous, validation de schéma, chaînage du journal
d'audit et points d'entrée de l'API, sur fixtures HTML statiques, sans réseau
ni appel de modèle.

## Sécurité et confidentialité

- Secrets fournis par variables d'environnement (`.env`), jamais versionnés.
- Mode local par défaut : aucune donnée d'enquête ne quitte l'infrastructure.
- Journal d'audit scellé par chaînage de hachage : altération détectable.
- Console d'administration désactivée si `ADMIN_PASSWORD` n'est pas défini.

Architecture détaillée et exploitation : voir `documentation.md`.