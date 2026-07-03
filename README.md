# OSINT-OFDF — Pipeline de détection d'annonces suspectes

Pipeline OSINT conteneurisé d'aide à l'enquête, développé pour l'Office fédéral
de la douane et de la sécurité des frontières (OFDF). Il parcourt des plateformes
de petites annonces, en extrait les offres et produit pour chacune un **signal de
suspicion argumenté** (tabac, alcool, espèces protégées, viande, contrefaçon,
armes), ancré sur un corpus de règles douanières. Le système produit des signaux,
jamais des décisions : la validation reste à l'enquêteur, et chaque étape est tracée.

Version : 0.9.0

## Prérequis

- Docker et Docker Compose
- Pour la topologie locale (par défaut) : Ollama installé sur l'hôte, avec le
  modèle `qwen3:8b` (`ollama pull qwen3:8b`). Les conteneurs l'atteignent via
  `host.docker.internal`.

## Démarrage rapide

```bash
# 1. Configuration des secrets (jamais versionnés)
cp .env.example .env
#    Renseigner dans .env : POSTGRES_PASSWORD, ADMIN_PASSWORD,
#    LLM_API_KEY (si topologie distante), APP_PORT, etc.

# 2. Construction et démarrage (profil par défaut : postgres, qdrant, app)
docker compose up -d --build
#    Le schéma PostgreSQL est créé automatiquement au premier démarrage
#    (sql/init.sql), lors de la création du volume postgres_data.

# 3. Provisionnement du RAG (obligatoire, une seule fois)
docker compose exec app python scripts/init_qdrant.py
docker compose exec app python scripts/ingest_rules.py

# 4. Accès
#    Interface enquêteur      : http://localhost:8000/ui
#    Console d'administration : http://localhost:8000/admin   (ADMIN_PASSWORD requis)
#    Documentation d'API      : http://localhost:8000/docs
```

> **Important.** Le code applicatif est intégré à l'image lors de sa construction
> (il n'est pas monté à chaud). Après toute modification de `src/`, reconstruire :
> `docker compose up -d --build app`. Seuls `config.yaml` et `prompts/` sont montés
> en lecture seule et prennent effet par simple `docker compose restart app`.

## Profils de déploiement

Le profil par défaut ne démarre que le cœur (`postgres`, `qdrant`, `app`).

```bash
# Environnements de démonstration (marchés fictifs, ports hôte 8001 et 8002)
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

## Évaluation

```bash
docker compose exec app python scripts/evaluate.py
```

Compare le pipeline (LLM + RAG) à une référence par mots-clés sur le jeu de
284 annonces annotées de `fake_market/`. Produit `data/eval/results.json` et
`data/eval/metrics.json`. Le graphique de séparation se régénère en local :
`python scripts/plot_scores.py`.

## Tests

```bash
PYTHONPATH=src pytest      # en local, depuis la racine
```

Couvrent extraction, garde-fous, validation de schéma, chaînage du journal
d'audit et points d'entrée de l'API, sur fixtures HTML statiques, sans réseau
ni appel de modèle.

## Structure du dépôt

```
src/osint/        Code applicatif
  collecte/         Extracteurs, garde-fous, session navigateur
  analyse/          Agents LLM (expand, parse, score, code, browse), RAG
  orchestration/    Pipeline (Mode A) et exploration (Mode B)
  persistance/      Accès PostgreSQL, journal d'audit
  api/              API FastAPI, console d'administration
  visualisation/    Interfaces HTML, rapports
prompts/          Prompts versionnés (un fichier par agent)
sql/init.sql      Schéma PostgreSQL (auto-exécuté au premier démarrage)
scripts/          Provisionnement, évaluation, démonstrations
fake_market/      Marché fictif + jeu d'évaluation annoté
mock_shop/        Marché fictif à sélecteurs (démo réparation)
n8n/workflows/    Workflows de planification
tests/            Suite de tests
docker/           Dockerfile de l'application
```

## Sécurité et confidentialité

- Secrets fournis par variables d'environnement (`.env`), jamais versionnés.
- Mode local par défaut : aucune donnée d'enquête ne quitte l'infrastructure.
- Journal d'audit scellé par chaînage de hachage : altération détectable.
- Console d'administration désactivée si `ADMIN_PASSWORD` n'est pas défini.

Architecture détaillée et exploitation : voir `DOCUMENTATION.md`.