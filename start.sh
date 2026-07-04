#!/usr/bin/env bash
# =============================================================================
#  start.sh — Démarrage tout-en-un (Git Bash / Linux / macOS)
# -----------------------------------------------------------------------------
#  Crée le .env s'il manque, démarre la pile, attend que l'API réponde,
#  provisionne le RAG, puis vérifie le déploiement. Idempotent : peut être
#  relancé sans risque.
#
#  Usage :
#    ./start.sh            # démarrage standard (mode défini dans config.yaml)
#    ./start.sh --dev      # ajoute les marchés de démonstration (fake_market, mock_shop)
# =============================================================================
set -euo pipefail

PROFILE_ARGS=()
[[ "${1:-}" == "--dev" ]] && PROFILE_ARGS=(--profile dev)

echo "== 1/5  Fichier de secrets (.env) =="
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "   .env créé depuis .env.example — pensez à renseigner les mots de passe"
  echo "   (POSTGRES_PASSWORD, ADMIN_PASSWORD ; LLM_API_KEY si topologie cloud)."
else
  echo "   .env déjà présent — conservé."
fi

echo "== 2/5  Construction et démarrage de la pile =="
docker compose "${PROFILE_ARGS[@]}" up -d --build

echo "== 3/5  Attente de l'API (peut prendre un moment au premier démarrage) =="
for i in $(seq 1 60); do
  if docker compose exec -T app python -c \
      "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/').status_code==200 else 1)" \
      >/dev/null 2>&1; then
    echo "   API prête."
    break
  fi
  [[ $i -eq 60 ]] && { echo "   ERREUR : l'API ne répond pas. Voir : docker compose logs app"; exit 1; }
  sleep 2
done

echo "== 4/5  Provisionnement du RAG (collections + corpus de règles) =="
docker compose exec -T app python scripts/init_qdrant.py
echo "   Ingestion des règles (le modèle d'embeddings ~2,25 Go se télécharge au"
echo "   premier appel : cela peut sembler figé plusieurs minutes, c'est normal)."
docker compose exec -T app python scripts/ingest_rules.py

echo "== 5/5  Vérification du déploiement =="
docker compose exec -T app python scripts/smoke_test.py || {
  echo ""
  echo "   Le smoke test signale un problème. Causes fréquentes :"
  echo "   - modèle KO en local  : Ollama n'est pas lancé (ollama list / ollama pull qwen3:8b)"
  echo "   - modèle KO en cloud  : LLM_API_KEY absente ou config.yaml pas en 'cloud'"
  echo "     (après correction : docker compose up -d app)"
  exit 1
}

echo ""
echo "Terminé. Interface : http://localhost:8000/ui   |   API : http://localhost:8000/docs"
