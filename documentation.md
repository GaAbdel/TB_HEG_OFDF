# Documentation technique — OSINT-OFDF

Document d'exploitation et d'architecture. Complète le `README.md` (démarrage
rapide). Destiné aux équipes qui déploient, exploitent ou étendent le système.

Version : 0.9.0

---

## 1. Principes de conception

Deux règles gouvernent chaque choix technique :

- **Stabilité avant autonomie, auditabilité avant intelligence brute.** Dans un
  contexte d'enquête, la valeur probante des signaux dépend de la traçabilité de
  leur obtention.
- **Signaux, pas décisions.** Le système attribue des scores de suspicion
  argumentés ; la décision revient toujours à un enquêteur.

Conséquences : mode local par défaut, validation humaine obligatoire avant toute
action, journalisation scellée de chaque étape, refus de générer ou d'exécuter du
code en production sans relecture.

## 2. Architecture

Quatre couches strictement séparées : **collecte**, **analyse**, **orchestration**,
**visualisation**, adossées à une **persistance** (PostgreSQL + Qdrant).

L'orchestration du pipeline est un **enchaînement Python explicite** (aucune
machine à états externe) : chaque étape est une fonction dédiée, exécutée dans une
transaction et consignée au journal. Ce choix privilégie la lisibilité et
l'auditabilité du déroulé à la flexibilité d'un orchestrateur générique.

### 2.1 Les cinq agents

| Agent | Rôle | Fonctionnement |
|---|---|---|
| LLM-EXPAND | Élargit la requête avant collecte | Passe simple |
| LLM-PARSE | Structure une annonce de site inconnu | Passe simple |
| LLM-SCORE | Attribue un score de suspicion (cœur métier) | Passe simple, avec RAG |
| LLM-CODE | Propose de nouveaux sélecteurs quand un extracteur casse | Candidat validé par l'admin |
| LLM-BROWSE | Pilote la navigation en Mode B | Boucle perception-action bornée |

### 2.2 Les deux modes de collecte

- **Mode A (surveillance)** : plateformes outillées, extracteurs déterministes.
  Déclenché à la demande (console) ou de façon planifiée (n8n).
- **Mode B (exploration)** : agent de navigation sur sites autorisés.
  - **B-1** (opérationnel) : sites pré-autorisés, exploration bornée par un budget
    de pas, chaque action consignée au journal scellé.
  - **B-2** (verrouillé) : recherche autonome de sites inconnus (voir §7).

### 2.3 Mémoire à trois niveaux

- **Sémantique** (Qdrant) : `customs_rules` (référentiel de qualification,
  statique) et `confirmed_suspicious` (cas validés, éligibles après validation).
- **Épisodique** (PostgreSQL) : annonces, scores, décisions, journal d'audit.
- **Procédurale** : `config.yaml` et prompts versionnés.

## 3. Carte du code

Vue par domaine, pour se repérer dans `src/osint/`.

- **`collecte/`** — obtention des annonces. `base.py` (session navigateur
  Playwright), `guardrails.py` (garde-fous : allowlist, budget, interdictions),
  `selector_based_extractor.py` (extracteur générique piloté par sélecteurs,
  réparable), `fake_market_extractor.py` (extracteur figé de démonstration),
  `parsers.py` / `selector_extractor.py` (fonctions d'extraction).
- **`analyse/`** — logique d'analyse. `expander.py` (LLM-EXPAND), `parser_llm.py`
  (LLM-PARSE), `scorer.py` (LLM-SCORE), `retriever.py` / `embeddings.py` /
  `rules_corpus.py` (RAG), `browse.py` (LLM-BROWSE) et `browse_audit.py` (journal
  scellé du Mode B), `code_repair.py` (réparation de sélecteurs), `code_gen.py` +
  `code_sandbox.py` (génération de code verrouillée, voir §7).
- **`orchestration/`** — `pipeline.py` (Mode A, enchaînement explicite),
  `explore.py` (Mode B).
- **`persistance/`** — accès aux données. `repositories.py` (requêtes),
  `audit.py` (chaîne d'audit chaînée), `postgres.py` (connexion relationnelle),
  `qdrant.py` (accès vectoriel).
- **`api/`** — `main.py` (API FastAPI et console d'administration), `jobs.py`
  (exécutions en tâche de fond).
- **`visualisation/`** — `ui.py` (console enquêteur), `admin_ui.py` (console
  d'administration), `report.py` (rapports HTML/JSON).
- **`model/`** — `litellm_client.py` (appel de modèle abstrait, résolution par
  agent et par topologie).

Hors `src/` : `sql/init.sql` (schéma, auto-exécuté au premier démarrage),
`prompts/` (un prompt versionné par agent), `scripts/` (provisionnement,
évaluation, démonstrations), `tests/` (suite de tests), `fake_market/` et
`mock_shop/` (marchés fictifs), `n8n/workflows/` (workflows de planification).

### 3.1 Volumes montés dans le conteneur `app`

Trois éléments sont montés depuis l'hôte plutôt qu'intégrés à l'image, pour être
modifiables sans reconstruction et, pour `data/`, conservés d'un redémarrage à
l'autre :

- **`config.yaml`** et **`prompts/`** — en lecture seule ; leur modification prend
  effet par `docker compose restart app`.
- **`data/`** — en lecture-écriture. Contient le corpus de règles lu par
  `ingest_rules.py` (`data/rules/`) ainsi que les fichiers produits par
  l'application : journaux d'audit (`data/audit/`), propositions de LLM-CODE
  (`data/extractor_proposals/`) et résultats d'évaluation (`data/eval/`).

Sans le montage de `data/`, l'ingestion du RAG ne trouve aucun fichier de règles
et la chaîne d'audit ne peut être écrite : ce montage est donc nécessaire au
fonctionnement, pas seulement au confort.

## 4. Configuration (`config.yaml`)

- **`topologie`** : `locale` (défaut), `centrale` ou `cloud`. Chaque topologie
  définit `api_base` et `model` sous `topologies`.
- **`per_agent`** : surcharge du modèle par agent (facultatif) : par exemple un
  modèle spécialisé code pour LLM-CODE, un modèle plus capable pour LLM-BROWSE.
- **`code_repair`** : verrou de la réparation d'extracteurs de code (voir §7).

Prompts et `config.yaml` sont montés en lecture seule : leur modification prend
effet par `docker compose restart app`, sans reconstruction. Le code applicatif,
lui, est intégré à l'image : le modifier impose `docker compose up -d --build app`.
Une modification de `.env` (comme de `config.yaml`) exige de **recréer** le
conteneur : `docker compose up -d app`.

### 4.1 Topologie globale et surcharge par agent

La résolution du modèle pour un agent se fait en deux temps : le modèle par défaut
de la `topologie` active, puis, le cas échéant, la surcharge `per_agent`. Les deux
sont indépendants.

Conséquence importante pour la souveraineté : router **un seul agent** vers un
fournisseur cloud via `per_agent` suffit à transmettre des données à un tiers,
**même si `topologie` reste `locale`**. Toute bascule cloud, globale ou par agent,
doit donc être un choix conscient (voir §8).

## 5. Exploitation

### 5.1 Mise en service

1. `cp .env.example .env` et renseigner les secrets (voir §8). Sous Windows,
   vérifier que le fichier s'appelle bien `.env` et non `.env.txt`.
2. `docker compose up -d --build` (schéma SQL auto-créé au premier démarrage). Le
   premier build est long : dépendances Python et navigateur Playwright.
3. Choisir le fournisseur de modèle dans `config.yaml` (`topologie`) :
   - `locale` (défaut) : Ollama sur l'hôte, avec `qwen3:8b` — aucune donnée
     transmise à un tiers.
   - `cloud` : fournisseur externe ; renseigner `LLM_API_KEY` dans `.env`.
   Router un seul agent vers le cloud via `per_agent` suffit à transmettre des
   données à un tiers, même en topologie `locale` (voir §4.1 et §8).
4. Provisionnement du RAG (une fois) :
   `docker compose exec app python scripts/init_qdrant.py`
   puis `docker compose exec app python scripts/ingest_rules.py`. Au premier
   appel, le modèle d'embeddings (~2,25 Go) se télécharge : l'étape peut sembler
   figée plusieurs minutes, c'est normal.
5. Vérification : `docker compose exec app python scripts/smoke_test.py`. La sonde
   confirme la topologie active et l'état de PostgreSQL, Qdrant et du service de
   modèle.

Un script de démarrage (`start.sh`, `start.ps1`) automatise les étapes 1, 2, 4
et 5 (voir README).

### 5.2 Console d'administration (`/admin`)

Protégée par `ADMIN_PASSWORD` (désactivée si non défini). Sept blocs : validation
des extracteurs proposés par LLM-CODE et historique ; vue unifiée plateformes et
extracteurs ; journal d'audit ; export JSON des cas confirmés (fichier local) ;
réinitialisation ; vérification d'intégrité des journaux scellés ; réparation de
code (verrouillée).

### 5.3 Réinitialisation

Vide les données opérationnelles (runs, annonces, scores, feedback, audit) et
conserve la configuration, sauf option contraire. Repartir d'une base vierge :
`docker compose down -v` puis relancer. Après un `down -v`, le RAG doit être
provisionné de nouveau (§5.1, étape 4).

## 6. Étendre le système

### 6.1 Site simple (extraction par sélecteurs) — aucun code

```sql
INSERT INTO platforms (name, base_url, antibot_rating, default_mode)
VALUES ('exemple', 'https://www.exemple.ch', 2, 'A');

INSERT INTO extractor_versions (platform, selectors, status, source)
VALUES ('exemple',
  '{"title":"h1.titre","price":".prix","seller":".vendeur","location":".lieu","description":".desc"}',
  'active', 'manual');
```

Pris en compte immédiatement, sans redémarrage. Réparable par LLM-CODE.

### 6.2 Site complexe (extraction par code)

Écrire une classe dans `src/osint/collecte/`, l'enregistrer dans le registre
`EXTRACTORS` (`orchestration/pipeline.py`), déclarer la plateforme en base, puis
`docker compose up -d --build app`. Non réparable automatiquement.

### 6.3 Workflows n8n

Un nouveau workflow se conçoit dans l'interface n8n (profil `full`), puis
s'exporte en JSON dans `n8n/workflows/` pour être versionné avec le dépôt.

## 7. Fonctionnalités préparées et verrouillées

Certaines capacités sont **présentes dans le code mais désactivées par défaut**,
car elles franchissent une frontière d'auditabilité ou de sécurité. Leur
activation relève d'une décision de l'administrateur du mandant.

| Capacité | Verrou (config) | Emplacement | À l'activation |
|---|---|---|---|
| **Mode B-2** — recherche autonome de sites inconnus | `mode_b.autonomous_search_enabled: false` | `orchestration/explore.py`, `analyse/browse.py` | L'exploration peut sortir des sites pré-autorisés ; à encadrer juridiquement |
| **Réparation de code** — LLM-CODE propose un extracteur `.py` | `code_repair.enabled: false` | `analyse/code_gen.py`, `analyse/code_sandbox.py` | Le code proposé est déposé dans `data/extractor_proposals/`, **jamais exécuté** ; installation manuelle par un développeur |

La réparation de code intègre un harnais d'exécution isolée (sous-processus,
délai borné) qui vérifie qu'un code proposé se charge et respecte l'interface.
Ce n'est pas un bac à sable de sécurité : l'isolation forte relève d'une évolution
ultérieure.

## 8. Sécurité et confidentialité

- **Secrets** : `POSTGRES_PASSWORD`, `LLM_API_KEY`, `ADMIN_PASSWORD`, etc. dans
  `.env` (jamais versionné). Le gabarit `.env.example` documente la structure.
- **Souveraineté** : mode local par défaut ; toute bascule vers un fournisseur
  distant (globale via `topologie`, ou ciblée via `per_agent`) transmet des
  données à un tiers et doit être un choix conscient et journalisé.
- **Journal scellé** : les actions du Mode B et la chaîne d'audit intègrent
  l'empreinte de l'entrée précédente ; toute altération rompt la chaîne. La
  vérification s'exécute via `scripts/verify_browse_log.py` ou la console d'admin.
- **Corpus de règles** : si `data/rules/` contient des documents internes, il ne
  doit pas être publié ; en vérifier le contenu avant toute diffusion du dépôt.

## 9. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| `.env not found` au démarrage | Fichier de secrets non créé | `cp .env.example .env` |
| `service "app" is not running` | Pile non démarrée | `docker compose up -d --build` puis `docker compose ps` |
| `Aucun fichier .md dans /app/data/rules` | `data/` non monté ou corpus absent | Vérifier le montage `./data:/app/data` (compose) et le contenu de `data/rules/` |
| Score toujours nul, RAG vide | Provisionnement non effectué | `init_qdrant.py` puis `ingest_rules.py` ; vérifier `points_count` de `customs_rules` |
| Changements de `src/` sans effet | Code intégré à l'image | `docker compose up -d --build app` |
| Changements de `config.yaml`/`.env` sans effet | Conteneur non recréé | `docker compose up -d app` |
| `/admin` renvoie 503 | `ADMIN_PASSWORD` non défini | Le définir dans `.env` et recréer le conteneur |
| `evaluate.py` : fichier introuvable | Lancé sur l'hôte | Lancer via `docker compose exec app ...` |
| Modèle injoignable en local | Ollama non démarré sur l'hôte | Démarrer Ollama ; `ollama list` doit montrer `qwen3:8b` |
| Modèle injoignable en cloud | Clé absente ou config non rechargée | Vérifier `LLM_API_KEY` et `topologie: cloud`, puis `docker compose up -d app` |