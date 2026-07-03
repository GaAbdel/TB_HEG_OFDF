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
transaction et consignée au journal.

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

## 4. Configuration (`config.yaml`)

- **`topologie`** : `locale` (défaut), `centrale` ou `cloud`. Chaque topologie
  définit `api_base` et `model` sous `topologies`.
- **`per_agent`** : surcharge du modèle par agent (facultatif) : par exemple un
  modèle spécialisé code pour LLM-CODE, un modèle plus capable pour LLM-BROWSE.
- **`code_repair`** : verrou de la réparation d'extracteurs de code (voir §7).

Prompts et `config.yaml` sont montés en lecture seule : leur modification prend
effet par `docker compose restart app`, sans reconstruction. Le code applicatif,
lui, est intégré à l'image : le modifier impose `docker compose up -d --build app`.

## 5. Exploitation

### 5.1 Mise en service

1. `cp .env.example .env` et renseigner les secrets (voir §8).
2. `docker compose up -d --build` (schéma SQL auto-créé au premier démarrage).
3. Provisionnement du RAG (une fois) :
   `docker compose exec app python scripts/init_qdrant.py`
   puis `docker compose exec app python scripts/ingest_rules.py`.
4. Vérification : `docker compose exec app python scripts/smoke_test.py`.

### 5.2 Console d'administration (`/admin`)

Protégée par `ADMIN_PASSWORD` (désactivée si non défini). Sept blocs : validation
des extracteurs proposés par LLM-CODE et historique ; vue unifiée plateformes et
extracteurs ; journal d'audit ; export JSON des cas confirmés (fichier local) ;
réinitialisation ; vérification d'intégrité des journaux scellés ; réparation de
code (verrouillée).

### 5.3 Réinitialisation

Vide les données opérationnelles (runs, annonces, scores, feedback, audit) et
conserve la configuration, sauf option contraire. Repartir d'une base vierge :
`docker compose down -v` puis relancer.

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
  `.env` (jamais versionné). Deux gabarits documentent la structure.
- **Souveraineté** : mode local par défaut ; toute bascule vers un fournisseur
  distant déclenche un avertissement de consentement, évalué par agent.
- **Journal scellé** : les actions du Mode B et la chaîne d'audit intègrent
  l'empreinte de l'entrée précédente ; toute altération rompt la chaîne.
- **Corpus de règles** : si `data/rules/` contient des documents internes, il ne
  doit pas être publié ; en vérifier le contenu avant toute diffusion du dépôt.

## 9. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| Score toujours nul, RAG vide | Provisionnement non effectué | `init_qdrant.py` puis `ingest_rules.py` |
| Changements de `src/` sans effet | Code cuit dans l'image | `docker compose up -d --build app` |
| `/admin` renvoie 503 | `ADMIN_PASSWORD` non défini | Le définir dans `.env` et redémarrer |
| `evaluate.py` : fichier introuvable | Lancé sur l'hôte | Lancer via `docker compose exec app ...` |
| Modèle injoignable en local | Ollama non démarré sur l'hôte | Démarrer Ollama, vérifier `OLLAMA_BASE_URL` |