# OSINT-OFDF — Pipeline de détection d’annonces suspectes

Pipeline OSINT conteneurisé d’aide à l’enquête, développé pour l’Office fédéral
de la douane et de la sécurité des frontières (OFDF). Il collecte des annonces,
les structure, récupère le contexte réglementaire pertinent et produit un
**signal de suspicion argumenté**.

Le système produit des signaux, jamais des décisions : la validation reste à
l’enquêteur et chaque étape est tracée.

**Version : 0.10.0**

---

## 1. Parcours rapide pour l’évaluateur

### Prérequis

- Docker Desktop ou Docker Engine avec `docker compose`
- environ 16 Go de RAM recommandés pour la configuration de référence
- plusieurs gigaoctets de stockage disponibles pour les images Docker, le
  navigateur Playwright, le modèle local éventuel et le modèle d’embeddings
- selon la topologie :
  - **locale** : Ollama démarré sur l’hôte avec `qwen3:8b`
  - **cloud** : une clé API du fournisseur configuré

### Préparer l’environnement

```bash
cp .env.example .env
```

Éditer `.env` et renseigner au minimum :

```env
POSTGRES_PASSWORD=...
ADMIN_PASSWORD=...
```

En cloud, renseigner également :

```env
LLM_API_KEY=...
```

### Démarrer la démonstration

Git Bash, Linux ou macOS :

```bash
./start.sh --dev
```

Windows PowerShell :

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Dev
```

### Vérifier le déploiement

```bash
docker compose exec app python scripts/smoke_test.py
docker compose exec app python -m pytest -q
```

Résultat de référence de la suite de tests :

```text
169 passed
```

### Ouvrir l’application

- interface enquêteur : http://localhost:8000/ui
- console d’administration : http://localhost:8000/admin
- documentation de l’API : http://localhost:8000/docs
- marché fictif Mode A : http://localhost:8001
- marché fictif Mode B / LLM-CODE : http://localhost:8002

> Le profil `dev` est requis pour utiliser les marchés fictifs depuis
> l’interface. Il n’est pas nécessaire pour exécuter `pytest` ni
> `scripts/evaluate.py`.

---

## 2. Démarrage automatisé

Les scripts de démarrage :

1. créent `.env` à partir de `.env.example` s’il manque ;
2. construisent l’image applicative ;
3. démarrent PostgreSQL, Qdrant et l’application ;
4. attendent la disponibilité de l’API ;
5. créent les collections Qdrant ;
6. ingèrent le corpus réglementaire ;
7. exécutent le smoke test.

Git Bash, Linux ou macOS :

```bash
./start.sh
./start.sh --dev
```

Windows PowerShell :

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Dev
```

La procédure manuelle reste disponible ci-dessous.

---

## 3. Topologies de modèle

La topologie globale se règle dans `config.yaml` :

```yaml
topologie: locale
```

Valeurs disponibles :

| Topologie | Usage | Préparation | Transmission à un tiers |
|---|---|---|---|
| `locale` | Ollama sur l’hôte | `ollama pull qwen3:8b` | Non, sauf surcharge cloud par agent |
| `centrale` | Serveur interne compatible OpenAI | URL interne dans `config.yaml` | Non si l’infrastructure reste interne |
| `cloud` | Fournisseur externe | `LLM_API_KEY` dans `.env` | Oui |

### Basculer le pipeline en cloud

Dans `config.yaml` :

```yaml
topologie: cloud
```

Dans `.env` :

```env
LLM_API_KEY=...
```

Appliquer les deux modifications :

```bash
docker compose up -d --force-recreate app
```

### Important : routage actuel de LLM-BROWSE

La configuration livrée utilise une topologie globale locale, mais surcharge
actuellement l’agent `LLM-BROWSE` avec un modèle Anthropic :

```yaml
per_agent:
  LLM-BROWSE:
    model: anthropic/claude-sonnet-4-6
```

Conséquences :

- le Mode A et les agents non surchargés suivent la topologie globale ;
- le Mode B nécessite une clé `LLM_API_KEY` dans cette configuration ;
- utiliser le Mode B transmet des données au fournisseur cloud ;
- cette transmission déclenche le garde-fou LPD prévu par l’application.

Pour une exécution entièrement locale, remplacer cette surcharge par :

```yaml
per_agent:
  LLM-BROWSE:
    model: ollama/qwen3:8b
    api_base: ${OLLAMA_BASE_URL}
```

La qualité de navigation peut être inférieure avec le modèle local selon la
machine et le site exploré.

---

## 4. Installation manuelle

### 4.1 Créer `.env`

```bash
cp .env.example .env
```

Sous Windows, vérifier que le fichier ne s’appelle pas `.env.txt` :

```bash
ls -la .env
```

### 4.2 Construire et démarrer le noyau

```bash
docker compose up -d --build
```

Le noyau comprend :

- `app`
- `postgres`
- `qdrant`

### 4.3 Provisionner le RAG

```bash
docker compose exec app python scripts/init_qdrant.py
docker compose exec app python scripts/ingest_rules.py
```

Le premier lancement télécharge le modèle d’embeddings. Cette étape peut durer
plusieurs minutes.

Le corpus réglementaire versionné se trouve dans :

```text
data/rules/
```

Il est visible dans le conteneur sous :

```text
/app/data/rules/
```

### 4.4 Vérifier le déploiement

```bash
docker compose exec app python scripts/smoke_test.py
```

Le smoke test vérifie :

- PostgreSQL
- Qdrant
- la topologie active
- la disponibilité du modèle lorsque la sonde est applicable

En topologie cloud avec une URL implicite gérée par LiteLLM, la sonde réseau du
modèle peut être volontairement ignorée.

---

## 5. Persistance des données

Le service `app` monte :

```yaml
- ./data:/app/data
```

Ce montage est en lecture-écriture. Il permet :

- de lire le corpus RAG dans `data/rules/`
- de persister les journaux du Mode B dans `data/audit/`
- de persister les résultats d’évaluation dans `data/eval/`
- de persister les propositions LLM-CODE dans
  `data/extractor_proposals/`

Ces fichiers survivent à la recréation du conteneur.

Les autres données persistantes utilisent des volumes Docker nommés :

- `postgres_data`
- `qdrant_data`
- `n8n_data`
- `models_cache`

### Permissions Linux

Le conteneur exécute l’application avec l’utilisateur UID `1000`. Sur Linux, en
cas de `Permission denied` lors d’une écriture dans `data/` :

```bash
sudo mkdir -p data/audit data/eval data/extractor_proposals
sudo chown -R 1000:1000 \
  data/audit \
  data/eval \
  data/extractor_proposals
```

Il n’est normalement pas nécessaire d’appliquer cette commande avec Docker
Desktop sous Windows.

---

## 6. Vérifier le RAG

Qdrant n’est pas publié sur l’hôte. La vérification s’effectue depuis
le conteneur `app` :

```bash
docker compose exec app python -c "from qdrant_client import QdrantClient; c=QdrantClient(host='qdrant', port=6333); print('points:', c.get_collection('customs_rules').points_count)"
```

Un nombre supérieur à zéro confirme que les règles ont été ingérées.

Vérifier les fichiers visibles dans le conteneur :

```bash
docker compose exec app ls -la /app/data/rules/
```

Sous Git Bash, si le chemin `/app/...` est converti en chemin Windows, utiliser :

```bash
MSYS_NO_PATHCONV=1 docker compose exec app ls -la /app/data/rules/
```

ou :

```bash
docker compose exec app ls -la //app/data/rules/
```

---

## 7. Prise en compte des modifications

| Élément modifié | Commande |
|---|---|
| `config.yaml` uniquement | `docker compose restart app` |
| `prompts/` | `docker compose restart app` |
| `.env` | `docker compose up -d --force-recreate app` |
| `docker-compose.yml` | `docker compose up -d --force-recreate app` |
| `src/` | `docker compose up -d --build app` |
| `scripts/` | `docker compose up -d --build app` |
| `docker/app.Dockerfile` | `docker compose up -d --build app` |
| `requirements.txt` | `docker compose up -d --build app` |
| `data/rules/` | relancer `scripts/ingest_rules.py` |
| `extractor_versions` (base) | aucune reconstruction — relu à chaque recherche |

### Pourquoi `restart` n’a pas appliqué le montage `data/`

```bash
docker compose restart app
```

redémarre le conteneur existant. Cette commande :

- relit les fichiers déjà montés ;
- ne recharge pas `.env` ;
- n’ajoute pas un nouveau volume ;
- n’applique pas un nouveau port ;
- ne reconstruit pas l’image.

Après une modification de `docker-compose.yml`, utiliser :

```bash
docker compose up -d --force-recreate app
```

Après une modification de code ou de script copié dans l’image, utiliser :

```bash
docker compose up -d --build app
```

En cas de doute et si le code a changé :

```bash
docker compose up -d --build --force-recreate app
```

---

## 8. Onboarding d’un site réel

Le Mode A distingue **deux familles d’extraction**. Le choix se fait après une
courte reconnaissance du site cible ; il détermine si l’ajout du site est une
simple opération de configuration ou un développement.

| Famille | Quand l’utiliser | Onboarding |
|---|---|---|
| **Sélecteurs déclaratifs** | La navigation et les champs peuvent être décrits par une configuration stable (sélecteurs CSS sur le DOM rendu) | Une ligne dans `extractor_versions` (aucun code) |
| **Extracteur codé** | Le site exige une logique ou un format de données propre — donnée hors du texte du DOM (ex. JSON-LD, API interne), navigation ou transformation particulière | Développement d’un extracteur, enregistrement dans le pipeline, reconstruction |

Le JSON-LD n’est pas une famille distincte : c’est une **technique** qu’un
extracteur codé peut employer. Anibis en est l’exemple (section 8.3).

La frontière entre les deux familles est un principe d’architecture : ce qui est
modifiable sans revue humaine (des sélecteurs) vit en base comme **donnée** ; ce
qui exige une revue (du code exécutable) vit dans `src/` sous contrôle de
version. Ce partage gouverne aussi la réparation assistée :

| Famille | Proposition LLM-CODE en cas de rupture | Application |
|---|---|---|
| Sélecteurs | Oui — un candidat de sélecteurs est déposé en base | Jamais automatique : validation en console admin |
| Extracteur codé | Possible sous forme de proposition de code | Jamais automatique : revue et déploiement manuels. Le déclenchement automatique sur panne d’un extracteur codé (ex. Anibis) n’est pas câblé à ce jour |

### 8.1 Reconnaissance (préalable, une fois par site)

Ouvrir le site, effectuer une recherche sur un terme cible, puis répondre par
observation directe (outils de développement du navigateur) :

1. **Le contenu est-il dans le HTML rendu ?** (afficher le code source, y
   rechercher le titre d’une annonce visible).
2. **Une annonce de la liste est-elle un lien suivable** (`<a href>`) vers une
   page de détail, ou une interaction JavaScript sans lien ?
3. **Comment passe-t-on à la page suivante ?** (lien/numéro de page, paramètre
   d’URL, ou défilement infini ?)

Ces critères **orientent** la décision, ils ne la déterminent pas mécaniquement :
contenu accessible, annonce en `<a href>`, pagination par lien ou paramètre
d’URL penchent vers les **sélecteurs** ; donnée structurée hors texte (JSON-LD),
logique d’interaction irréductible penchent vers l’**extracteur codé**. Le choix
final dépend aussi de la stabilité des éléments, des attentes de chargement
nécessaires, de la gestion du consentement, des transformations de données et
des interactions propres au site.

### 8.2 Site à sélecteurs — onboarding par configuration

L’ajout se fait par une seule ligne dans `extractor_versions` (version active).
Les clés préfixées `_` décrivent la navigation ; les autres sont les champs
d’extraction :

```sql
INSERT INTO extractor_versions (platform, selectors, status, source) VALUES
  ('exemple',
   '{
      "_list_path":     "/recherche?q=...",
      "_card_selector": "<sélecteur du lien d’annonce>",
      "_next_page":     "<sélecteur du lien suivant>",   -- OU _page_param
      "_page_param":    "?page=",                         -- pagination par URL
      "_max_pages":     "2",
      "_max_listings":  "8",
      "title":          "<sélecteur titre>",
      "price":          "<sélecteur prix>",
      "description":    "<sélecteur description>",
      "seller":         "<sélecteur vendeur>",
      "location":       "<sélecteur localité>"
    }'::jsonb,
   'active', 'manual');
```

Aucune reconstruction : la configuration est relue à chaque recherche. Le
périmètre réseau autorisé est dérivé du `base_url` de la plateforme dans la
table `platforms` (source de vérité), pas de la requête cliente.

### 8.3 Exemple : Anibis (extracteur codé, JSON-LD)

Les pages d’annonce observées lors de la reconnaissance exposaient un bloc
JSON-LD schema.org de type `Product` (titre, prix, devise, vendeur, localité,
description). L’extracteur utilise cette source lorsqu’elle est présente et
valide ; c’est un contrat plus robuste que des sélecteurs visuels sur un site à
classes CSS générées. Anibis relève donc de la famille **extracteur codé** :
`AnibisExtractor` est enregistré dans le pipeline (reconstruction requise), et
seule sa **configuration de recherche** vit en base — le pipeline lit cette
configuration (`get_active_selectors`) et l’injecte à l’extracteur au moment de
l’exécution.

Onboarding de la configuration de recherche (après reconstruction de l’image).
**Exemple à compléter après reconnaissance — ne pas exécuter tel quel avec la
valeur `<...>` :**

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
INSERT INTO extractor_versions (platform, selectors, status, source) VALUES (
  '\''anibis'\'',
  '\''{\"_list_path\":\"/fr/q/cherche/<blob-de-recherche>\",\"_max_pages\":\"2\",\"_max_listings\":\"8\"}'\''::jsonb,
  '\''active'\'', '\''manual'\''
);"'
```

Anibis n’expose pas d’URL de recherche en clair : le chemin `_list_path` est un
identifiant de recherche **opaque**, relevé depuis la barre d’adresse après une
recherche manuelle. Conséquence à connaître : cette URL correspond à une
recherche précise et figée ; elle **ne prend pas automatiquement** le mot-clé
saisi par l’enquêteur, et LLM-EXPAND ne la modifie pas — les termes enrichis
servent au filtrage de pertinence des résultats, pas à la construction de la
requête. Les plafonds `_max_pages` / `_max_listings` bornent la durée de collecte
(chaque annonce = une page de détail + un scoring).

Vérifier l’onboarding :

```bash
docker compose exec app curl -s localhost:8000/platforms | grep -i anibis
```

---

## 9. Démonstration — profil `dev`

Les services `fake_market` et `mock_shop` ne démarrent pas avec le profil par
défaut.

Démarrer le profil de démonstration :

```bash
docker compose --profile dev up -d --build
```

ou :

```bash
./start.sh --dev
```

Sans ce profil, une collecte visant un marché fictif peut échouer avec :

```text
net::ERR_NAME_NOT_RESOLVED
```

### Mode A — surveillance (marché fictif)

1. ouvrir http://localhost:8000/ui ;
2. sélectionner `fake_market` ;
3. lancer la recherche ;
4. consulter les annonces, les scores et le rapport.

### Mode A — surveillance (Anibis, site réel)

Après onboarding de la configuration Anibis (section 8.3) :

1. ouvrir http://localhost:8000/ui ;
2. sélectionner `anibis` ;
3. lancer la recherche ;
4. consulter les annonces extraites (via JSON-LD), les scores et le rapport.

### Mode B — exploration

1. vérifier que `LLM_API_KEY` est renseignée si `LLM-BROWSE` reste configuré sur
   Anthropic ;
2. sélectionner un site autorisé ;
3. saisir éventuellement une requête : elle **oriente l’exploration** de l’agent
   (focus) et la priorisation des résultats via LLM-EXPAND ;
4. lancer l’exploration ;
5. consulter les résultats et la trace d’audit.

> **Portée de l’exploration.** L’agent dispose d’actions génériques de
> navigation, de clic et de saisie (il révèle par exemple les numéros masqués
> derrière un bouton). En revanche, le prompt de la configuration livrée lui
> interdit de **soumettre un formulaire** : il n’utilise donc pas le moteur de
> recherche interne du site, et ne fait qu’explorer les pages atteignables par
> navigation. Cette contrainte est levable par le prompt (voir évolutions), sans
> modification de code.
>
> Conséquence : sur un site où le ciblage passe par la recherche interne,
> l’exploration peut ne remonter aucune annonce. Le Mode B vise les sites à
> structure inconnue ; pour une plateforme à structure connue (ex. Anibis), le
> Mode A reste l’outil adapté.

Les marchés restent consultables directement :

- http://localhost:8001 — `fake_market`
- http://localhost:8002 — `mock_shop`

---

## 10. Démonstration avec navigateur visible

La pile principale fonctionne dans Docker. Les scripts qui ouvrent une fenêtre
de navigateur visible doivent être lancés depuis l’hôte.

Créer l’environnement :

```bash
python -m venv .venv
```

Activer sous Windows / Git Bash :

```bash
source .venv/Scripts/activate
```

Activer sous Linux / macOS :

```bash
source .venv/bin/activate
```

Installer les dépendances :

```bash
pip install -r requirements.txt
playwright install chromium
```

Exporter la clé si LLM-BROWSE utilise le cloud :

```bash
export LLM_API_KEY=...
```

Lancer la démonstration :

```bash
PYTHONPATH=src python scripts/demo_soutenance.py
```

---

## 11. Évaluation

L’évaluation compare le pipeline LLM + RAG à une référence simple par mots-clés
sur 284 annonces annotées.

```bash
docker compose exec app python scripts/evaluate.py
```

Au premier lancement, le script copie automatiquement les entrées canoniques :

```text
/app/fake_market/listings.json
/app/fake_market/dataset_manifest.json
```

vers le répertoire de travail persistant :

```text
/app/data/eval/
```

Les sorties sont écrites sur l’hôte dans :

```text
data/eval/results.json
data/eval/metrics.json
```

L’évaluation est reprenable : `results.json` sert de point de reprise.

Pour recommencer depuis zéro :

```bash
rm -f data/eval/results.json data/eval/metrics.json
docker compose exec app python scripts/evaluate.py
```

> En topologie cloud, cette commande effectue jusqu’à 284 appels au fournisseur
> configuré et peut consommer des crédits API réels. Vérifier la clé, le modèle,
> les limites de débit et le budget avant de la lancer.

Après modification de `scripts/evaluate.py`, reconstruire l’image :

```bash
docker compose up -d --build app
```

---

## 12. Tests

```bash
docker compose exec app python -m pytest -q
```

Les tests couvrent notamment :

- extraction (sélecteurs, pagination, extracteur Anibis / JSON-LD)
- validation de schéma
- garde-fous
- corpus réglementaire
- journal d’audit
- points d’entrée de l’API
- logique pure de l’évaluation

Ils utilisent des fixtures locales et ne nécessitent pas le profil `dev`.

Résultat de référence :

```text
169 passed
```

---

## 13. Planification n8n — profil `full`

Démarrer le service :

```bash
docker compose --profile full up -d
```

Un workflow d’exemple est fourni dans :

```text
n8n/workflows/surveillance_mode_a.json
```

Il déclenche périodiquement l’API du Mode A. Le workflow n’est pas activé ni
importé automatiquement.

Le fichier d’exemple vise `fake_market`. Pour l’exécuter tel quel, démarrer
également le profil `dev` :

```bash
docker compose --profile full --profile dev up -d --build
```

La version actuelle du Compose ne publie pas l’interface n8n sur l’hôte. Le
workflow fourni constitue donc un exemple de planification à importer et valider
dans un déploiement où l’administration n8n est explicitement exposée ou gérée
sur le réseau d’administration.

n8n ne contient pas la logique métier : il appelle l’API de l’application à
intervalle régulier.

---

## 14. Profils Docker Compose

| Service | Profil | Rôle |
|---|---|---|
| `app` | défaut | API, pipeline, collecte et interfaces |
| `postgres` | défaut | mémoire relationnelle et audit |
| `qdrant` | défaut | mémoire vectorielle RAG |
| `fake_market` | `dev` | marché fictif Mode A |
| `mock_shop` | `dev` | démonstration Mode B / LLM-CODE |
| `n8n` | `full` | planification externe |

Commandes :

```bash
# Noyau
docker compose up -d --build

# Noyau + marchés fictifs
docker compose --profile dev up -d --build

# Noyau + n8n
docker compose --profile full up -d

# n8n + marchés fictifs
docker compose --profile full --profile dev up -d --build
```

---

## 15. Arrêt et réinitialisation

Arrêter les conteneurs sans supprimer les données :

```bash
docker compose down
```

Arrêter également les profils optionnels :

```bash
docker compose --profile dev --profile full down
```

Supprimer les conteneurs **et les volumes Docker nommés** :

```bash
docker compose down -v
```

> `down -v` supprime notamment PostgreSQL, Qdrant, le cache du modèle
> d’embeddings et les données n8n. Il faudra ensuite recréer les collections et
> réingérer le corpus. Le dossier hôte `data/` n’est pas supprimé par cette
> commande.
>
> La configuration d’onboarding d’un site (table `extractor_versions`) vit dans
> `postgres_data` : `down -v` la supprime. Après un tel reset, ré-exécuter
> l’onboarding (section 8) pour les sites concernés.

Réinitialiser uniquement les résultats d’évaluation :

```bash
rm -f data/eval/results.json data/eval/metrics.json
```

---

## 16. Résolution des problèmes courants

| Symptôme | Cause probable | Action |
|---|---|---|
| `.env not found` | `.env` absent | `cp .env.example .env` |
| `service "app" is not running` | pile non démarrée | `docker compose up -d --build` |
| `net::ERR_NAME_NOT_RESOLVED` | profil `dev` absent | `docker compose --profile dev up -d` |
| `Aucun fichier .md dans /app/data/rules` | corpus absent ou montage non appliqué | vérifier `data/rules/`, puis recréer `app` |
| `FileNotFoundError: /app/data/rules/...` dans pytest | volume `data/` non appliqué | `docker compose up -d --force-recreate app` |
| `FileNotFoundError: /app/data/eval/listings.json` | ancienne image de `evaluate.py` ou données non provisionnées | reconstruire `app`, puis relancer l’évaluation |
| collecte à `0` sur un site réel | extracteur non déployé, ou onboarding absent | vérifier l’enregistrement de l’extracteur et la ligne `extractor_versions` (section 8) |
| `model` KO en local | Ollama arrêté ou modèle absent | démarrer Ollama et vérifier `ollama list` |
| erreur de connexion Ollama en topologie cloud | configuration non relue | vérifier `topologie: cloud`, puis recréer `app` |
| `model` KO en cloud | clé absente ou environnement non rechargé | vérifier `LLM_API_KEY`, puis recréer `app` |
| changement de `config.yaml` sans effet | processus non redémarré | `docker compose restart app` |
| changement de `.env` sans effet | ancien environnement conservé | `docker compose up -d --force-recreate app` |
| nouveau volume ou port sans effet | ancien conteneur conservé | `docker compose up -d --force-recreate app` |
| modification de code ou script sans effet | image non reconstruite | `docker compose up -d --build app` |
| chemin `/app/...` converti en `C:/Program Files/Git/...` | conversion MSYS de Git Bash | préfixer `MSYS_NO_PATHCONV=1` ou utiliser `//app/...` |
| `Permission denied` sous Linux dans `data/` | UID hôte incompatible | corriger les droits des dossiers de sortie |

---

## 17. Sécurité et confidentialité

- les secrets sont fournis par `.env` et ne sont pas versionnés ;
- la topologie globale locale conserve les appels des agents non surchargés sur
  l’infrastructure locale ;
- `LLM-BROWSE` est actuellement surchargé vers Anthropic et implique donc un
  transfert lorsqu’il est utilisé ;
- tout recours au cloud est soumis au garde-fou de consentement prévu ;
- le périmètre réseau de collecte est borné par une liste d’autorisation dérivée
  du référentiel des plateformes ;
- les journaux du Mode B sont persistés dans `data/audit/` ;
- la console d’administration est protégée par `ADMIN_PASSWORD` ;
- les actions à autonomie élevée restent bornées et tracées.

---

## 18. Documentation complémentaire

Architecture et exploitation détaillées :

```text
documentation.md
```

Workflow n8n d’exemple :

```text
n8n/workflows/README.md
```


