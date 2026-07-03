# =============================================================================
#  docker/app.Dockerfile — image du conteneur `app` (API + sondes /health)
# =============================================================================
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1) Dépendances Python — couche mise en cache tant que requirements.txt ne bouge pas
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) Navigateur Playwright (Chromium) + dépendances système, lisibles par tous
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

# 3) Code applicatif
COPY src/ ./src/
COPY scripts/ ./scripts/
# config.yaml et prompts/ sont MONTÉS en lecture seule (cf. docker-compose),
# pas copiés : modifiables sans rebuild.

# 4) Utilisateur non privilégié
RUN useradd --create-home --uid 1000 appuser \
 && mkdir -p /app/models \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness : l'app est "vivante" si la racine répond (indépendante des dépendances)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/').status_code==200 else 1)"

CMD ["uvicorn", "osint.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

