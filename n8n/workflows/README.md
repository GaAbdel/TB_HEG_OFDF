# Workflows n8n — planification du Mode A

Ce dossier contient des workflows n8n **d'exemple** pour la surveillance
automatique (Mode A). Ils ne sont pas activés par défaut : Il faut les importer et les valider sois-même.

> ⚠️ Ces workflows n'ont pas pu être testés automatiquement

## Prérequis

Lancer la pile avec le profil `full` (qui inclut n8n) :

```bash
docker compose --profile full up -d
```

n8n est alors disponible sur `http://localhost:5678` (identifiants dans `.env` :
`N8N_USER` / `N8N_PASSWORD`).

## Importer le workflow

1. Ouvrir n8n → menu **⋮** → **Import from File**.
2. Choisir `surveillance_mode_a.json`.
3. Le workflow apparaît : un déclencheur planifié (toutes les 6 h) relié à un
   appel HTTP `POST http://app:8000/search`.

> Note réseau : n8n et l'API sont sur le même réseau Docker (`osint_net`), donc
> n8n appelle l'API par son nom de service `app:8000` — **pas** `localhost`.

## Adapter

Dans le nœud **« Déclencher une recherche »**, ajuste le corps JSON :

```json
{
  "seeds": ["cigarettes", "ivoire", "alcool fort"],
  "platform": "fake_market",
  "base_url": "http://fake_market:8000"
}
```

- `seeds` : les termes de veille (interprétés par LLM-EXPAND).
- `platform` / `base_url` : la plateforme cible.

Dans le nœud **« Toutes les 6 heures »**, ajuste l'intervalle.

## Valider

1. **Activer** le workflow (interrupteur en haut à droite).
2. Cliquer **Execute Workflow** pour un test immédiat.
3. Vérifier dans l'UI (`/ui`) qu'un nouveau run apparaît dans la file
   d'investigation, ou via `GET /runs`.

## Cadre (mémoire)

Ce workflow matérialise la **planification du Mode A** : la surveillance
déterministe et périodique, par opposition à la recherche à la demande
(déclenchée manuellement via l'UI). n8n n'orchestre pas la logique métier — il
ne fait que **déclencher** l'API à intervalle régulier ; toute l'intelligence
reste dans le pipeline. C'est cohérent avec la séparation des couches
(orchestration externe légère vs cœur applicatif).