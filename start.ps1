# =============================================================================
#  start.ps1 — Démarrage tout-en-un (Windows PowerShell, sans dépendance)
# -----------------------------------------------------------------------------
#  Équivalent Windows de start.sh. Ne nécessite ni make ni Git Bash : PowerShell
#  est présent nativement sur Windows. Crée le .env s'il manque, démarre la pile,
#  attend l'API, provisionne le RAG, vérifie le déploiement.
#
#  Usage (depuis le dossier du projet) :
#    powershell -ExecutionPolicy Bypass -File .\start.ps1
#    powershell -ExecutionPolicy Bypass -File .\start.ps1 -Dev   # + marchés de démo
# =============================================================================
param([switch]$Dev)
$ErrorActionPreference = "Stop"

$profileArgs = @()
if ($Dev) { $profileArgs = @("--profile","dev") }

Write-Host "== 1/5  Fichier de secrets (.env) =="
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "   .env cree depuis .env.example — renseignez les mots de passe"
    Write-Host "   (POSTGRES_PASSWORD, ADMIN_PASSWORD ; LLM_API_KEY si topologie cloud)."
} else {
    Write-Host "   .env deja present — conserve."
}

Write-Host "== 2/5  Construction et demarrage de la pile =="
docker compose @profileArgs up -d --build

Write-Host "== 3/5  Attente de l'API (peut prendre un moment au premier demarrage) =="
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    docker compose exec -T app python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/').status_code==200 else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true; Write-Host "   API prete."; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Host "   ERREUR : l'API ne repond pas. Voir : docker compose logs app"; exit 1 }

Write-Host "== 4/5  Provisionnement du RAG (collections + corpus de regles) =="
docker compose exec -T app python scripts/init_qdrant.py
Write-Host "   Ingestion des regles (le modele d'embeddings ~2,25 Go se telecharge au"
Write-Host "   premier appel : cela peut sembler fige plusieurs minutes, c'est normal)."
docker compose exec -T app python scripts/ingest_rules.py

Write-Host "== 5/5  Verification du deploiement =="
docker compose exec -T app python scripts/smoke_test.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "   Le smoke test signale un probleme. Causes frequentes :"
    Write-Host "   - modele KO en local : Ollama n'est pas lance (ollama list / ollama pull qwen3:8b)"
    Write-Host "   - modele KO en cloud : LLM_API_KEY absente ou config.yaml pas en 'cloud'"
    Write-Host "     (apres correction : docker compose up -d app)"
    exit 1
}

Write-Host ""
Write-Host "Termine. Interface : http://localhost:8000/ui   |   API : http://localhost:8000/docs"
