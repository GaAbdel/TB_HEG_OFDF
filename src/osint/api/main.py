"""Point d'entrée de l'API FastAPI.

Expose la pile complète du pipeline :
- /health : sonde de disponibilité (PostgreSQL, Qdrant, modèle) ;
- /listings, /listings/{id} : file d'investigation (filtrable par score et run) ;
- /runs : liste des runs (pour filtrer la file) ;
- /search (POST) + /search/{job_id} : recherche asynchrone (EXPAND -> collecte
  -> scoring), suivie par identifiant de job ;
- /reports/{run_id} : rapport d'un run (HTML ou JSON) ;
- /ui : console d'analyse (interface enquêteur).

Le « lecteur » de données est injecté par dépendance, ce qui rend les routes
testables sans base (faux lecteur en test).
"""

from __future__ import annotations

import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from osint import __version__
from osint.config import get_config
from osint.model import litellm_client
from osint.persistance import postgres, qdrant

app = FastAPI(
    title="OSINT Douane — API",
    description="Pipeline de détection d'annonces suspectes pour enquêtes douanières (OFDF)",
    version=__version__,
)


@app.get("/health")
def health() -> JSONResponse:
    """Sonde de disponibilité agrégée.

    Renvoie 200 si toutes les dépendances sont saines, 503 sinon. Chaque
    dépendance est sondée indépendamment et son détail est reporté.
    """
    cfg = get_config()

    checks: dict[str, dict[str, str | bool]] = {}
    for name, fn in (
        ("postgres", postgres.ping),
        ("qdrant", qdrant.ping),
        ("model", litellm_client.ping),
    ):
        ok, detail = fn(cfg)
        checks[name] = {"ok": ok, "detail": detail}

    all_ok = all(c["ok"] for c in checks.values())
    payload = {
        "status": "ok" if all_ok else "degraded",
        "topologie": cfg.topologie,
        "checks": checks,
    }
    return JSONResponse(status_code=200 if all_ok else 503, content=payload)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "osint-ofdf", "version": __version__, "health": "/health"}


# --- Lecture des annonces ---------------------------------------------------
# Le « lecteur » est injecté via une dépendance : en production il s'appuie sur
# une transaction PostgreSQL ; en test il est remplacé par un faux lecteur, ce
# qui rend les routes testables sans base.
class _DbReader:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list_listings(self, *, limit: int, offset: int, min_score: float | None,
                      run_id: int | None = None, category: str | None = None):
        from osint.persistance import repositories
        return repositories.list_listings(self.conn, limit=limit, offset=offset,
                                           min_score=min_score, run_id=run_id, category=category)

    def list_runs(self):
        from osint.persistance import repositories
        return repositories.list_runs(self.conn)

    def list_platforms(self):
        from osint.persistance import repositories
        return repositories.list_platforms(self.conn)

    def list_extractor_candidates(self, status="pending"):
        from osint.persistance import repositories
        return repositories.list_extractor_candidates(self.conn, status=status)

    def approve_extractor_candidate(self, candidate_id, decided_by):
        from osint.persistance import repositories
        return repositories.approve_extractor_candidate(
            self.conn, candidate_id, decided_by=decided_by)

    def reject_extractor_candidate(self, candidate_id, decided_by):
        from osint.persistance import repositories
        return repositories.reject_extractor_candidate(
            self.conn, candidate_id, decided_by=decided_by)

    def list_extractor_history(self):
        from osint.persistance import repositories
        return repositories.list_extractor_history(self.conn)

    def list_audit_log(self, limit=100):
        from osint.persistance import repositories
        return repositories.list_audit_log(self.conn, limit=limit)

    def export_confirmed_cases(self):
        from osint.persistance import repositories
        return repositories.export_confirmed_cases(self.conn)

    def reset_operational_data(self, reset_extractors=False):
        from osint.persistance import repositories
        return repositories.reset_operational_data(self.conn, reset_extractors=reset_extractors)

    def get_active_selectors(self, platform):
        from osint.persistance import repositories
        return repositories.get_active_selectors(self.conn, platform)

    def list_selector_platforms(self):
        from osint.persistance import repositories
        return repositories.list_selector_platforms(self.conn)

    def verify_audit_chain(self):
        from osint.persistance import audit
        return audit.verify_db_chain(self.conn)

    def get_listing(self, listing_id: int):
        from osint.persistance import repositories
        return repositories.get_listing_detail(self.conn, listing_id)

    def get_run_report(self, run_id: int):
        from osint.persistance import repositories
        return repositories.get_run_report(self.conn, run_id)

    def add_review(self, *, listing_id, decision, investigator_ref, comment=None, category_corrected=None):
        from osint.persistance import repositories
        return repositories.add_feedback(
            self.conn, listing_id=listing_id, investigator_ref=investigator_ref,
            decision=decision, comment=comment, category_corrected=category_corrected,
        )


def get_reader():
    from osint.persistance.db import transaction  # import paresseux : pas de pool à l'import
    with transaction() as conn:
        yield _DbReader(conn)


@app.get("/listings")
def list_listings_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    run_id: int | None = Query(default=None, ge=1),
    category: str | None = Query(default=None),
    reader=Depends(get_reader),
) -> dict:
    """Liste les annonces collectées avec leur dernier score (file d'enquête).

    Avec `run_id`, restreint aux annonces scorées par ce run ; avec `category`,
    restreint à une catégorie de risque.
    """
    items = reader.list_listings(limit=limit, offset=offset, min_score=min_score,
                                 run_id=run_id, category=category)
    return {"count": len(items), "items": [dict(it) for it in items]}


@app.get("/runs")
def list_runs_endpoint(reader=Depends(get_reader)) -> dict:
    """Liste les runs récents (pour filtrer la file d'investigation)."""
    runs = reader.list_runs()
    return {"count": len(runs), "items": [dict(r) for r in runs]}


@app.get("/platforms")
def list_platforms_endpoint(reader=Depends(get_reader)) -> dict:
    """Plateformes disponibles en Mode A, avec l'indication de celles qui
    disposent d'un extracteur déterministe (les autres sont à construire)."""
    from osint.orchestration.pipeline import EXTRACTORS
    plats = reader.list_platforms()
    outillees = set(EXTRACTORS) | set(reader.list_selector_platforms())
    items = [
        {
            "name": p["name"],
            "base_url": p["base_url"],
            "extractor_available": p["name"] in outillees,
        }
        for p in plats
    ]
    return {"count": len(items), "items": items}


@app.get("/listings/{listing_id}")
def get_listing_endpoint(listing_id: int, reader=Depends(get_reader)) -> dict:
    """Détail d'une annonce et de son dernier score."""
    detail = reader.get_listing(listing_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    return detail


_VALID_DECISIONS = {"confirme", "rejete", "incertain"}


class ReviewRequest(BaseModel):
    decision: str                              # confirme | rejete | incertain
    investigator_ref: str = "enqueteur"
    comment: str | None = None
    category_corrected: str | None = None


@app.post("/listings/{listing_id}/review", status_code=201)
def review_listing_endpoint(listing_id: int, body: ReviewRequest, reader=Depends(get_reader)) -> dict:
    """Enregistre une décision enquêteur (confirme/rejete/incertain).

    L'écriture est tracée dans la chaîne d'audit (via add_feedback) : qui a
    décidé quoi, et quand, de façon inviolable.
    """
    if body.decision not in _VALID_DECISIONS:
        raise HTTPException(status_code=422, detail="décision invalide (confirme/rejete/incertain)")
    feedback_id = reader.add_review(
        listing_id=listing_id, decision=body.decision,
        investigator_ref=body.investigator_ref, comment=body.comment,
        category_corrected=body.category_corrected,
    )
    return {"feedback_id": feedback_id, "listing_id": listing_id, "decision": body.decision}


# --- Recherche asynchrone (POST /search, Mode B à la demande) ----------------
# Une collecte dure plusieurs minutes : on la traite en arrière-plan. POST crée
# un job et répond 202 + job_id ; le client suit l'avancement via GET.
from osint.api.jobs import JobStore  # noqa: E402

_jobs = JobStore()


class SearchRequest(BaseModel):
    seeds: list[str]
    platform: str = "fake_market"
    # Optionnel : l'URL canonique vient du référentiel `platforms` (base).
    # Une valeur explicite n'est acceptée que si elle coïncide avec lui.
    base_url: str | None = None
    max_terms: int | None = None


async def _default_search_runner(params: dict) -> dict:
    """Exécute le vrai pipeline (EXPAND -> collecte -> scoring)."""
    from osint.config import get_config
    from osint.orchestration.pipeline import run_search_pipeline
    cfg = get_config()
    return await run_search_pipeline(
        cfg,
        seeds=params["seeds"],
        platform=params.get("platform", "fake_market"),
        base_url=params.get("base_url"),
        max_terms=params.get("max_terms"),
    )


def get_search_runner():
    """Dépendance injectable : remplacée par un faux runner dans les tests."""
    return _default_search_runner


async def _execute_job(job_id: str, params: dict, runner) -> None:
    _jobs.mark_running(job_id)
    try:
        # Le pipeline contient des appels BLOQUANTS (LLM, base) : on l'exécute
        # dans un thread dédié pour garder l'API réactive pendant l'analyse
        # (sinon la boucle d'évènements est monopolisée et l'UI gèle).
        import asyncio
        result = await asyncio.to_thread(lambda: asyncio.run(runner(params)))
        _jobs.mark_done(job_id, result)
    except Exception as exc:  # le job porte l'erreur, l'API ne plante pas
        _jobs.mark_error(job_id, str(exc))


@app.post("/search", status_code=202)
async def post_search(
    body: SearchRequest,
    background: BackgroundTasks,
    runner=Depends(get_search_runner),
) -> dict:
    """Déclenche une recherche en arrière-plan. Répond 202 + job_id."""
    job = _jobs.create(body.model_dump())
    background.add_task(_execute_job, job.id, body.model_dump(), runner)
    return {"job_id": job.id, "status": job.status}


@app.get("/search/{job_id}")
def get_search_status(job_id: str) -> dict:
    """Statut d'une recherche : pending / running / done / error."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return job.public()


# --- Mode B : exploration au mieux (B-1 actif, B-2 verrouillé) --------------
class ExploreRequest(BaseModel):
    sites: list[str] = []            # labels choisis parmi l'allowlist
    depth: str = "standard"          # rapide | standard | approfondie
    autonomous: bool = False         # Mode B-2 (recherche autonome) — verrouillé
    focus: str = ""                  # cible optionnelle (pilote le tri du rapport)


async def _default_explore_runner(params: dict) -> dict:
    """Exécute le vrai pipeline d'exploration (LLM-BROWSE -> structuration -> scoring)."""
    from osint.config import get_config
    from osint.orchestration.explore import run_explore_pipeline
    cfg = get_config()
    return run_explore_pipeline(cfg, sites=params["sites"], depth=params.get("depth", "standard"),
                                focus=params.get("focus", ""))


def get_explore_runner():
    """Dépendance injectable : remplacée par un faux runner dans les tests."""
    return _default_explore_runner


@app.get("/mode-b/sites")
def get_mode_b_sites() -> dict:
    """Sites autorisés pour l'exploration Mode B + état du verrou B-2."""
    from osint.config import get_config
    cfg = get_config()
    return {
        "sites": [{"label": s["label"]} for s in cfg.mode_b_sites()],
        "autonomous_enabled": cfg.mode_b_autonomous_enabled(),
        "lpd_cloud_warning": cfg.is_third_party_transfer("LLM-BROWSE"),
        "browse_provider": cfg.resolve_model("LLM-BROWSE").model.split("/", 1)[0],
    }


@app.get("/lpd/status")
def get_lpd_status() -> dict:
    """État de transfert cloud par mode (pour l'avertissement LPD de l'UI).

    Mode A (surveillance) s'appuie sur LLM-SCORE ; Mode B (exploration) sur
    LLM-BROWSE. Chacun peut viser un fournisseur local ou cloud (per_agent),
    d'où deux drapeaux distincts.
    """
    from osint.config import get_config
    cfg = get_config()

    def _p(agent: str) -> str:
        return cfg.resolve_model(agent).model.split("/", 1)[0]

    return {
        "mode_a": {"cloud": cfg.is_third_party_transfer("LLM-SCORE"), "provider": _p("LLM-SCORE")},
        "mode_b": {"cloud": cfg.is_third_party_transfer("LLM-BROWSE"), "provider": _p("LLM-BROWSE")},
    }


@app.post("/explore", status_code=202)
async def post_explore(
    body: ExploreRequest,
    background: BackgroundTasks,
    runner=Depends(get_explore_runner),
) -> dict:
    """Déclenche une exploration Mode B en arrière-plan. Répond 202 + job_id.

    Verrou B-2 : la recherche autonome de sites est refusée tant que
    l'administrateur ne l'a pas activée en configuration. B-1 : chaque site
    choisi doit appartenir à l'allowlist (périmètre pré-autorisé).
    """
    from osint.config import get_config
    cfg = get_config()

    if body.autonomous and not cfg.mode_b_autonomous_enabled():
        raise HTTPException(
            status_code=403,
            detail="Mode B-2 (recherche autonome de sites) non activé par l'administrateur.",
        )

    resolved = []
    for label in body.sites:
        site = cfg.mode_b_site_by_label(label)
        if site is None:
            raise HTTPException(status_code=422, detail=f"Site non autorisé : {label}")
        resolved.append(site)
    if not resolved:
        raise HTTPException(status_code=422, detail="Aucun site autorisé sélectionné.")

    params = {"sites": resolved, "depth": body.depth, "focus": body.focus}
    job = _jobs.create(params)
    background.add_task(_execute_job, job.id, params, runner)
    return {"job_id": job.id, "status": job.status}


# --- Restitution : rapport et console (couche visualisation) -----------------
from osint.visualisation.report import build_report_data, render_report_html  # noqa: E402
from osint.visualisation.ui import render_index  # noqa: E402


@app.get("/reports/{run_id}")
def get_report_endpoint(run_id: int, format: str = "html", reader=Depends(get_reader)):
    """Rapport d'un run : HTML (défaut) ou JSON (?format=json)."""
    data = reader.get_run_report(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    report = build_report_data(data["run"], data["listings"])
    if format == "json":
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(content=jsonable_encoder(report))
    return HTMLResponse(render_report_html(report))


# --- Administration (validation des candidats LLM-CODE) ---------------------
#  Portillon simple par mot de passe (variable ADMIN_PASSWORD). Ce n'est pas une
#  authentification forte : c'est un garde-porte pour un déploiement pilote. Si
#  ADMIN_PASSWORD n'est pas défini, l'espace admin est désactivé (503).

def require_admin(x_admin_password: str = Header(default="")) -> str:
    """Dépendance : vérifie le mot de passe admin. Renvoie l'acteur (pour l'audit)."""
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Espace admin non configuré (ADMIN_PASSWORD absent).")
    if x_admin_password != expected:
        raise HTTPException(status_code=401, detail="Mot de passe administrateur invalide.")
    return "admin"


class CandidateDecision(BaseModel):
    decided_by: str = "admin"


@app.get("/admin/candidates")
def admin_list_candidates(reader=Depends(get_reader), _admin=Depends(require_admin)) -> dict:
    """Liste les candidats d'extracteur en attente (proposés par LLM-CODE)."""
    items = reader.list_extractor_candidates(status="pending")
    from fastapi.encoders import jsonable_encoder
    return {"count": len(items), "items": jsonable_encoder(items)}


@app.get("/admin/history")
def admin_history(reader=Depends(get_reader), _admin=Depends(require_admin)) -> dict:
    """Historique des décisions d'extracteur (approuvé / remplacé / rejeté)."""
    items = reader.list_extractor_history()
    from fastapi.encoders import jsonable_encoder
    return {"count": len(items), "items": jsonable_encoder(items)}


@app.get("/admin/audit")
def admin_audit(limit: int = 100, reader=Depends(get_reader), _admin=Depends(require_admin)) -> dict:
    """Journal d'audit centralisé (dernières entrées, tous runs)."""
    items = reader.list_audit_log(limit=limit)
    from fastapi.encoders import jsonable_encoder
    return {"count": len(items), "items": jsonable_encoder(items)}


@app.get("/admin/extractors")
def admin_extractors(reader=Depends(get_reader), _admin=Depends(require_admin)) -> dict:
    """Vue unifiée : plateformes (Mode A) + sites autorisés Mode B (config.yaml).

    Réconcilie les trois sources : table `platforms`, registres d'extracteurs
    (code), et `mode_b.sites_autorises`. Rappel : le Mode B n'exige pas
    d'extracteur (l'agent LLM-BROWSE navigue), d'où des sites Mode B sans
    extracteur — c'est normal.
    """
    from osint.orchestration.pipeline import EXTRACTORS
    from osint.config import get_config
    selector_platforms = set(reader.list_selector_platforms())

    entries: dict[str, dict] = {}
    # 1) plateformes déclarées en base (cibles Mode A potentielles)
    for p in reader.list_platforms():
        entries[p["name"]] = {
            "platform": p["name"], "base_url": p["base_url"],
            "in_db": True, "mode_b": False,
        }
    # 2) sites autorisés pour l'exploration Mode B (config.yaml)
    for s in get_config().mode_b_sites():
        key = s["platform"]
        e = entries.get(key)
        if e is None:
            e = entries[key] = {"platform": key, "base_url": s["base_url"],
                                "in_db": False, "mode_b": False}
        e["mode_b"] = True
    # 3) type d'extracteur + présence de sélecteurs actifs
    items = []
    for key, e in entries.items():
        if key in EXTRACTORS:
            e["kind"], e["extractor_available"] = "figé (code)", True
        elif key in selector_platforms:
            e["kind"], e["extractor_available"] = "sélecteurs (réparable)", True
        else:
            e["kind"], e["extractor_available"] = "—", False
        e["active_selectors_present"] = (
            True if key in selector_platforms else None
        )
        items.append(e)
    # extracteurs d'abord, puis alphabétique
    items.sort(key=lambda x: (not x["extractor_available"], x["platform"]))
    return {"count": len(items), "items": items}


@app.get("/admin/export")
def admin_export(reader=Depends(get_reader), _admin=Depends(require_admin)):
    """Export JSON des cas confirmés (téléchargeable). Aucune transmission externe."""
    from fastapi.encoders import jsonable_encoder
    from datetime import datetime, timezone
    items = reader.export_confirmed_cases()
    payload = {"exported_at": datetime.now(timezone.utc).isoformat(), "count": len(items),
               "cases": jsonable_encoder(items)}
    headers = {"Content-Disposition": "attachment; filename=cas_confirmes.json"}
    return JSONResponse(content=payload, headers=headers)


class ResetRequest(BaseModel):
    confirm: str = ""
    reset_extractors: bool = False


@app.post("/admin/reset")
def admin_reset(body: ResetRequest, reader=Depends(get_reader), admin=Depends(require_admin)) -> dict:
    """Réinitialise les données opérationnelles. Exige confirm == 'RESET'.

    Conserve la configuration, sauf si reset_extractors=True (retour usine des
    extracteurs). Destiné à ramener l'application à un état initial propre.
    """
    if body.confirm != "RESET":
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm='RESET').")
    counts = reader.reset_operational_data(reset_extractors=body.reset_extractors)
    return {"status": "reset", "effacé": counts}


@app.get("/admin/verify")
def admin_verify(reader=Depends(get_reader), _admin=Depends(require_admin)) -> dict:
    """Vérifie l'intégrité des journaux scellés.

    - Chaîne d'audit en base (audit_log) : chaînage de hachage.
    - Journaux scellés du Mode B (fichiers data/audit/*.jsonl).
    Renvoie pour chacun : intact (ok) et, sinon, l'indice de la première anomalie.
    """
    from pathlib import Path
    from osint.persistance import audit as _audit
    from osint.analyse.browse_audit import read_browse_log

    ok, first_bad = reader.verify_audit_chain()
    result = {"audit": {"ok": ok, "first_bad": first_bad}, "browse": []}

    d = Path("data/audit")
    if d.exists():
        for p in sorted(d.glob("*.jsonl")):
            try:
                entries = read_browse_log(p)
                bok, bbad = _audit.verify_chain(entries)
                result["browse"].append(
                    {"file": p.name, "ok": bok, "first_bad": bbad, "count": len(entries)}
                )
            except Exception as exc:  # fichier illisible / corrompu
                result["browse"].append({"file": p.name, "ok": False, "error": str(exc)})
    return result


# --- Réparation de CODE (verrou OFDF, expérimental) --------------------------
#  Ossature minimale : LLM-CODE propose un extracteur .py, DÉPOSÉ dans un dossier
#  et JAMAIS exécuté. Installation manuelle par un développeur. Verrou config.

class CodeRepairGenerate(BaseModel):
    platform: str
    sample_html: str = ""


class CodeRepairDiscard(BaseModel):
    filename: str


@app.get("/admin/code-repair/status")
def admin_code_repair_status(_admin=Depends(require_admin)) -> dict:
    from osint.config import get_config
    from osint.analyse.code_gen import list_proposals
    cfg = get_config()
    return {
        "enabled": cfg.code_repair_enabled(),
        "proposals_dir": cfg.code_repair_proposals_dir(),
        "count": len(list_proposals(cfg)),
    }


@app.get("/admin/code-repair/proposals")
def admin_code_repair_proposals(_admin=Depends(require_admin)) -> dict:
    from osint.config import get_config
    from osint.analyse.code_gen import list_proposals
    items = list_proposals(get_config())
    return {"count": len(items), "items": items}


@app.post("/admin/code-repair/generate")
def admin_code_repair_generate(body: CodeRepairGenerate, _admin=Depends(require_admin)) -> dict:
    from osint.config import get_config
    from osint.analyse.code_gen import propose_extractor_code
    cfg = get_config()
    if not cfg.code_repair_enabled():
        raise HTTPException(status_code=403, detail="Réparation de code désactivée (verrou OFDF).")
    try:
        result = propose_extractor_code(cfg, body.platform, body.sample_html)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "generated", **result}


@app.post("/admin/code-repair/discard")
def admin_code_repair_discard(body: CodeRepairDiscard, _admin=Depends(require_admin)) -> dict:
    from osint.config import get_config
    from osint.analyse.code_gen import discard_proposal
    if not discard_proposal(get_config(), body.filename):
        raise HTTPException(status_code=404, detail="Proposition introuvable.")
    return {"status": "discarded", "filename": body.filename}


@app.post("/admin/candidates/{candidate_id}/approve")
def admin_approve_candidate(
    candidate_id: int, reader=Depends(get_reader), admin=Depends(require_admin)
) -> dict:
    """Approuve un candidat : il devient l'extracteur actif de sa plateforme."""
    ok = reader.approve_extractor_candidate(candidate_id, decided_by=admin)
    if not ok:
        raise HTTPException(status_code=404, detail="Candidat introuvable ou déjà décidé.")
    return {"status": "approved", "candidate_id": candidate_id}


@app.post("/admin/candidates/{candidate_id}/reject")
def admin_reject_candidate(
    candidate_id: int, reader=Depends(get_reader), admin=Depends(require_admin)
) -> dict:
    """Rejette un candidat : rien ne change côté extraction."""
    ok = reader.reject_extractor_candidate(candidate_id, decided_by=admin)
    if not ok:
        raise HTTPException(status_code=404, detail="Candidat introuvable ou déjà décidé.")
    return {"status": "rejected", "candidate_id": candidate_id}


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    """Console d'administration (validation des candidats LLM-CODE)."""
    from osint.visualisation.admin_ui import render_admin
    return HTMLResponse(render_admin())


@app.get("/ui", response_class=HTMLResponse)
def ui_endpoint() -> HTMLResponse:
    """Console d'analyse (page web unique)."""
    return HTMLResponse(render_index())