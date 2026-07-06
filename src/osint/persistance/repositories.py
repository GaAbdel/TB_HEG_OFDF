"""Couche d'accès aux données (repositories) — mémoire épisodique.

Chaque fonction prend une connexion `conn` : elles se composent donc dans UNE
même transaction (cohérence). Les opérations qui constituent une *action*
métier émettent leur entrée d'audit via `audit.append()` dans la même
transaction — la traçabilité est garantie par construction, pas par convention.

Lectures : aucun audit. Écritures significatives : audit systématique.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from osint.persistance import audit

if TYPE_CHECKING:
    from psycopg import Connection


def _J(value: Any) -> Jsonb:
    """Adapte un objet Python en JSONB (None -> {})."""
    return Jsonb(value if value is not None else {})


# =============================================================================
#  platforms (référentiel — lecture)
# =============================================================================
def platform_id(conn: "Connection", name: str) -> int | None:
    row = conn.execute("SELECT id FROM platforms WHERE name = %s", (name,)).fetchone()
    return row["id"] if row else None


def get_platform(conn: "Connection", name: str) -> dict | None:
    """Fiche d'une plateforme (id, base_url canonique) ou None si inconnue.

    Le `base_url` en base est la SOURCE DE VÉRITÉ du périmètre de collecte
    Mode A : c'est lui — et non une valeur fournie par le client — qui
    détermine le domaine autorisé par les garde-fous.
    """
    row = conn.execute(
        "SELECT id, name, base_url FROM platforms WHERE name = %s", (name,)
    ).fetchone()
    return dict(row) if row else None


def get_or_create_platform(conn: "Connection", name: str, base_url: str) -> int:
    """Retourne l'id de la plateforme, en la créant si elle n'existe pas.

    Utile pour le Mode B, qui peut explorer un site autorisé absent du seed
    initial (ex. un site ajouté à l'allowlist par l'administrateur).
    """
    pid = platform_id(conn, name)
    if pid is not None:
        return pid
    row = conn.execute(
        "INSERT INTO platforms (name, base_url, default_mode) VALUES (%s, %s, 'B') "
        "ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url RETURNING id",
        (name, base_url),
    ).fetchone()
    return row["id"]


# =============================================================================
#  runs (sessions d'exécution)
# =============================================================================
def create_run(
    conn: "Connection",
    *,
    mode: str,
    trigger: str = "manuel",
    params: dict | None = None,
    config_snapshot: dict | None = None,
    actor: str = "system",
) -> int:
    row = conn.execute(
        "INSERT INTO runs (mode, trigger, params, config_snapshot) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (mode, trigger, _J(params), _J(config_snapshot)),
    ).fetchone()
    run_id = row["id"]
    audit.append(
        conn, actor=actor, action="run_start", run_id=run_id,
        detail={"mode": mode, "trigger": trigger},
    )
    return run_id


def finish_run(
    conn: "Connection",
    run_id: int,
    *,
    status: str,
    stats: dict | None = None,
    error: str | None = None,
    actor: str = "system",
) -> None:
    conn.execute(
        "UPDATE runs SET status = %s, stats = %s, error = %s, finished_at = now() "
        "WHERE id = %s",
        (status, _J(stats), error, run_id),
    )
    audit.append(
        conn, actor=actor, action="run_end", run_id=run_id,
        detail={"status": status},
    )


# =============================================================================
#  model_versions (versioning — get-or-create)
# =============================================================================
def get_or_create_model_version(
    conn: "Connection",
    *,
    agent: str,
    model_name: str,
    prompt_version: str | None = None,
    prompt_hash: str | None = None,
    topology: str | None = None,
    params: dict | None = None,
) -> int:
    # IS NOT DISTINCT FROM gère correctement les NULL de la clé unique.
    row = conn.execute(
        "SELECT id FROM model_versions WHERE agent = %s AND model_name = %s "
        "AND prompt_version IS NOT DISTINCT FROM %s "
        "AND prompt_hash IS NOT DISTINCT FROM %s",
        (agent, model_name, prompt_version, prompt_hash),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "INSERT INTO model_versions (agent, model_name, prompt_version, prompt_hash, "
        "topology, params) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (agent, model_name, prompt_version, prompt_hash, topology, _J(params)),
    ).fetchone()
    return row["id"]


# =============================================================================
#  listings + listing_observations (annonce + apparition, dédup)
# =============================================================================
def upsert_listing(
    conn: "Connection",
    *,
    run_id: int,
    actor: str,
    platform_id: int,
    external_id: str,
    content_hash: str,
    url: str | None = None,
    title: str | None = None,
    description: str | None = None,
    price_amount: float | None = None,
    price_currency: str | None = None,
    seller_label: str | None = None,
    structured: dict | None = None,
) -> tuple[int, bool]:
    """Insère ou met à jour une annonce (clé naturelle platform_id+external_id),
    enregistre l'observation du run, et trace l'action. Renvoie (id, est_nouvelle).

    `(xmax = 0)` distingue une insertion (xmax=0) d'une mise à jour (xmax<>0).
    """
    row = conn.execute(
        """
        INSERT INTO listings (platform_id, external_id, url, title, description,
            price_amount, price_currency, seller_label, structured, content_hash)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (platform_id, external_id) DO UPDATE SET
            url = EXCLUDED.url,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            price_amount = EXCLUDED.price_amount,
            price_currency = EXCLUDED.price_currency,
            seller_label = EXCLUDED.seller_label,
            structured = EXCLUDED.structured,
            content_hash = EXCLUDED.content_hash,
            last_seen_at = now(),
            observation_count = listings.observation_count + 1
        RETURNING id, (xmax = 0) AS inserted
        """,
        (platform_id, external_id, url, title, description, price_amount,
         price_currency, seller_label, _J(structured), content_hash),
    ).fetchone()
    listing_id, is_new = row["id"], row["inserted"]

    conn.execute(
        "INSERT INTO listing_observations (listing_id, run_id, content_hash) "
        "VALUES (%s,%s,%s)",
        (listing_id, run_id, content_hash),
    )
    audit.append(
        conn, actor=actor, action="collect", run_id=run_id, listing_id=listing_id,
        detail={"new": is_new, "external_id": external_id},
    )
    return listing_id, is_new


# =============================================================================
#  scores (sortie LLM-SCORE)
# =============================================================================
def add_score(
    conn: "Connection",
    *,
    run_id: int,
    listing_id: int,
    model_version_id: int,
    category: str,
    suspicion_score: float,
    category_breakdown: dict | None = None,
    rationale: str | None = None,
    rag_refs: list | None = None,
    actor: str = "LLM-SCORE",
) -> int:
    row = conn.execute(
        "INSERT INTO scores (listing_id, run_id, model_version_id, category, "
        "suspicion_score, category_breakdown, rationale, rag_refs) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (listing_id, run_id, model_version_id, category, suspicion_score,
         _J(category_breakdown), rationale, _J(rag_refs if rag_refs is not None else [])),
    ).fetchone()
    score_id = row["id"]
    audit.append(
        conn, actor=actor, action="score", run_id=run_id, listing_id=listing_id,
        detail={"category": category, "suspicion_score": float(suspicion_score)},
    )
    return score_id


# =============================================================================
#  investigator_feedback (human-in-the-loop)
# =============================================================================
def add_feedback(
    conn: "Connection",
    *,
    listing_id: int,
    investigator_ref: str,
    decision: str,
    score_id: int | None = None,
    category_corrected: str | None = None,
    comment: str | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO investigator_feedback (listing_id, score_id, investigator_ref, "
        "decision, category_corrected, comment) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (listing_id, score_id, investigator_ref, decision, category_corrected, comment),
    ).fetchone()
    feedback_id = row["id"]
    audit.append(
        conn, actor="investigator", action="validate", listing_id=listing_id,
        detail={"decision": decision, "investigator_ref": investigator_ref},
    )
    return feedback_id


def pending_ingestion(conn: "Connection", limit: int = 100) -> list[dict]:
    """Cas confirmés en attente d'ingestion vers Qdrant (confirmed_suspicious).

    Exploite l'index partiel idx_feedback_pending_ingest (ingested_to_qdrant=false).
    """
    rows = conn.execute(
        """
        SELECT f.id, f.listing_id, f.score_id, f.category_corrected,
               l.platform_id, l.external_id, l.title, l.description, l.structured
        FROM investigator_feedback f
        JOIN listings l ON l.id = f.listing_id
        WHERE f.ingested_to_qdrant = false AND f.decision = 'confirme'
        ORDER BY f.decided_at
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return list(rows)


def mark_ingested(conn: "Connection", feedback_id: int, *, actor: str = "system") -> None:
    row = conn.execute(
        "UPDATE investigator_feedback SET ingested_to_qdrant = true, ingested_at = now() "
        "WHERE id = %s RETURNING listing_id",
        (feedback_id,),
    ).fetchone()
    listing_id = row["listing_id"] if row else None
    audit.append(
        conn, actor=actor, action="ingest", listing_id=listing_id,
        detail={"feedback_id": feedback_id},
    )


# --- Lectures pour l'API (aucun audit : ce sont des consultations) ----------
def list_listings(
    conn: "Connection", *, limit: int = 50, offset: int = 0,
    min_score: float | None = None, run_id: int | None = None,
    category: str | None = None,
) -> list[dict]:
    """Annonces collectées avec leur score (file d'investigation).

    Sans `run_id` : toutes les annonces, avec leur DERNIER score (historique
    cumulatif). Avec `run_id` : uniquement les annonces scorées par CE run, avec
    le score de ce run. `min_score` et `category` filtrent dans les deux cas.
    Tri par score décroissant (run) ou dernière observation (historique).
    """
    if run_id is not None:
        rows = conn.execute(
            """
            SELECT l.id, l.title, l.price_amount, l.price_currency, l.url,
                   p.name AS platform, l.last_seen_at, l.seller_label, l.structured,
                   s.category, s.suspicion_score, fb.decision AS review_decision,
                   r.mode AS run_mode
            FROM scores s
            JOIN listings l ON l.id = s.listing_id
            JOIN platforms p ON p.id = l.platform_id
            LEFT JOIN runs r ON r.id = s.run_id
            LEFT JOIN LATERAL (
                SELECT decision FROM investigator_feedback
                WHERE listing_id = l.id ORDER BY decided_at DESC LIMIT 1
            ) fb ON true
            WHERE s.run_id = %s
              AND (%s::numeric IS NULL OR s.suspicion_score >= %s)
              AND (%s::text IS NULL OR s.category = %s::risk_category)
            ORDER BY s.suspicion_score DESC
            LIMIT %s OFFSET %s
            """,
            (run_id, min_score, min_score, category, category, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT l.id, l.title, l.price_amount, l.price_currency, l.url,
                   p.name AS platform, l.last_seen_at, l.seller_label, l.structured,
                   s.category, s.suspicion_score, fb.decision AS review_decision,
                   r.mode AS run_mode
            FROM listings l
            JOIN platforms p ON p.id = l.platform_id
            LEFT JOIN LATERAL (
                SELECT category, suspicion_score, run_id
                FROM scores WHERE listing_id = l.id
                ORDER BY scored_at DESC LIMIT 1
            ) s ON true
            LEFT JOIN runs r ON r.id = s.run_id
            LEFT JOIN LATERAL (
                SELECT decision FROM investigator_feedback
                WHERE listing_id = l.id ORDER BY decided_at DESC LIMIT 1
            ) fb ON true
            WHERE (%s::numeric IS NULL OR s.suspicion_score >= %s)
              AND (%s::text IS NULL OR s.category = %s::risk_category)
            ORDER BY l.last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            (min_score, min_score, category, category, limit, offset),
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        structured = d.pop("structured", None) or {}
        d["location"] = structured.get("location")
        items.append(d)
    return items


def list_platforms(conn: "Connection") -> list[dict]:
    """Liste les plateformes connues (pour le choix de cible en Mode A)."""
    rows = conn.execute(
        "SELECT name, base_url, default_mode FROM platforms ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


# --- Versions d'extracteur (réparation LLM-CODE supervisée) -------------------

def get_active_selectors(conn: "Connection", platform: str) -> dict | None:
    """Sélecteurs de l'extracteur ACTIF d'une plateforme, ou None si aucun."""
    row = conn.execute(
        "SELECT selectors FROM extractor_versions "
        "WHERE platform = %s AND status = 'active'",
        (platform,),
    ).fetchone()
    return dict(row["selectors"]) if row else None


def list_selector_platforms(conn: "Connection") -> list[str]:
    """Plateformes pilotées par sélecteurs : celles ayant une version ACTIVE.

    Source de vérité DÉCLARATIVE (base) plutôt que codée en dur : onboarder une
    plateforme à sélecteurs = insérer sa version active, sans toucher au code.
    """
    rows = conn.execute(
        "SELECT DISTINCT platform FROM extractor_versions WHERE status = 'active'"
    ).fetchall()
    return [r["platform"] for r in rows]


def insert_extractor_candidate(
    conn: "Connection", *, platform: str, selectors: dict,
    source: str = "llm-code", repair_history: list | None = None,
    validation: dict | None = None,
) -> int:
    """Insère un CANDIDAT (status='pending') proposé par LLM-CODE. Non appliqué."""
    row = conn.execute(
        "INSERT INTO extractor_versions (platform, selectors, status, source, "
        "repair_history, validation) VALUES (%s, %s, 'pending', %s, %s, %s) "
        "RETURNING id",
        (platform, _J(selectors), source, _J(repair_history), _J(validation)),
    ).fetchone()
    return int(row["id"])


def list_extractor_candidates(conn: "Connection", *, status: str = "pending") -> list[dict]:
    """Liste les candidats d'extracteur, avec le sélecteur actif pour comparaison."""
    rows = conn.execute(
        "SELECT id, platform, selectors, source, repair_history, validation, "
        "status, created_at FROM extractor_versions "
        "WHERE status = %s ORDER BY created_at DESC",
        (status,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active_selectors"] = get_active_selectors(conn, r["platform"])
        out.append(d)
    return out


def approve_extractor_candidate(conn: "Connection", candidate_id: int, *, decided_by: str) -> bool:
    """Approuve un candidat : l'ancien actif passe 'superseded', le candidat 'active'.

    Atomique. Renvoie False si le candidat n'existe pas ou n'est pas 'pending'.
    """
    row = conn.execute(
        "SELECT platform FROM extractor_versions WHERE id = %s AND status = 'pending'",
        (candidate_id,),
    ).fetchone()
    if row is None:
        return False
    platform = row["platform"]
    conn.execute(
        "UPDATE extractor_versions SET status = 'superseded', decided_at = now() "
        "WHERE platform = %s AND status = 'active'",
        (platform,),
    )
    conn.execute(
        "UPDATE extractor_versions SET status = 'active', decided_at = now(), "
        "decided_by = %s WHERE id = %s",
        (decided_by, candidate_id),
    )
    return True


def reject_extractor_candidate(conn: "Connection", candidate_id: int, *, decided_by: str) -> bool:
    """Rejette un candidat (status='rejected'). Rien d'autre ne change."""
    res = conn.execute(
        "UPDATE extractor_versions SET status = 'rejected', decided_at = now(), "
        "decided_by = %s WHERE id = %s AND status = 'pending'",
        (decided_by, candidate_id),
    )
    return res.rowcount > 0


def list_extractor_history(conn: "Connection", *, platform: str | None = None, limit: int = 50) -> list[dict]:
    """Historique des décisions : versions approuvées, remplacées ou rejetées.

    Exclut le seed initial jamais décidé (decided_at NULL). Trié du plus récent.
    """
    base = (
        "SELECT id, platform, selectors, status, source, decided_at, decided_by, created_at "
        "FROM extractor_versions WHERE decided_at IS NOT NULL"
    )
    if platform:
        rows = conn.execute(
            base + " AND platform = %s ORDER BY decided_at DESC LIMIT %s",
            (platform, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            base + " ORDER BY decided_at DESC LIMIT %s", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# --- Administration : journal, export, réinitialisation ------------------------

def list_audit_log(conn: "Connection", *, limit: int = 100) -> list[dict]:
    """Dernières entrées du journal d'audit (chaîne de traçabilité), tous runs."""
    rows = conn.execute(
        "SELECT id, run_id, listing_id, actor, action, detail, created_at "
        "FROM audit_log ORDER BY created_at DESC, id DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def export_confirmed_cases(conn: "Connection") -> list[dict]:
    """Cas confirmés par les enquêteurs (matière d'un export / transmission OFDF).

    Jointure feedback + annonce + score. Ne réalise AUCUNE transmission : sert à
    produire un export local. La transmission réelle relève du déploiement chez
    le mandant (art. 34 LPD), hors périmètre du livrable.
    """
    rows = conn.execute(
        "SELECT f.id, f.decision, f.category_corrected, f.comment, f.decided_at, "
        "f.investigator_ref, l.title, l.url, l.price_amount, l.price_currency, "
        "l.content_hash, p.name AS platform, s.category, s.suspicion_score "
        "FROM investigator_feedback f "
        "JOIN listings l ON l.id = f.listing_id "
        "LEFT JOIN platforms p ON p.id = l.platform_id "
        "LEFT JOIN scores s ON s.id = f.score_id "
        "WHERE f.decision = 'confirme' "
        "ORDER BY f.decided_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def reset_operational_data(conn: "Connection", *, reset_extractors: bool = False) -> dict:
    """Vide les données OPÉRATIONNELLES (runs, annonces, scores, feedback, audit).

    Par défaut, conserve la CONFIGURATION (plateformes, versions d'extracteur,
    versions de modèle). Si `reset_extractors=True`, remet aussi les extracteurs
    à la configuration initiale (retour « usine » : seul le seed mock_shop v1
    reste actif). Renvoie le décompte effacé avant troncature (indicatif).
    """
    counts = {}
    for t in ("runs", "listings", "scores", "investigator_feedback", "audit_log"):
        row = conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()
        counts[t] = int(row["n"])
    conn.execute(
        "TRUNCATE audit_log, investigator_feedback, scores, "
        "listing_observations, listings, runs RESTART IDENTITY CASCADE"
    )
    if reset_extractors:
        from osint.collecte.selector_extractor import V1_SELECTORS
        conn.execute("DELETE FROM extractor_versions")
        conn.execute(
            "INSERT INTO extractor_versions (platform, selectors, status, source) "
            "VALUES ('mock_shop', %s, 'active', 'manual')",
            (_J(V1_SELECTORS),),
        )
        counts["extractors_reset"] = True
    return counts


def list_runs(conn: "Connection", *, limit: int = 50) -> list[dict]:
    """Liste les runs récents (pour filtrer la file d'investigation)."""
    rows = conn.execute(
        """
        SELECT id AS run_id, mode, status, stats, started_at
        FROM runs ORDER BY started_at DESC LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_listing_detail(conn: "Connection", listing_id: int) -> dict | None:
    """Détail d'une annonce + son dernier score, ou None si introuvable."""
    listing = conn.execute(
        """
        SELECT l.id, l.external_id, l.title, l.description, l.price_amount,
               l.price_currency, l.seller_label, l.url, p.name AS platform,
               l.observation_count, l.first_seen_at, l.last_seen_at, l.structured
        FROM listings l JOIN platforms p ON p.id = l.platform_id
        WHERE l.id = %s
        """,
        (listing_id,),
    ).fetchone()
    if listing is None:
        return None
    score = conn.execute(
        """
        SELECT category, suspicion_score, category_breakdown, rationale,
               rag_refs, scored_at
        FROM scores WHERE listing_id = %s
        ORDER BY scored_at DESC LIMIT 1
        """,
        (listing_id,),
    ).fetchone()
    feedback = conn.execute(
        """
        SELECT decision, investigator_ref, comment, decided_at
        FROM investigator_feedback WHERE listing_id = %s
        ORDER BY decided_at DESC LIMIT 1
        """,
        (listing_id,),
    ).fetchone()
    return {
        "listing": dict(listing),
        "score": dict(score) if score else None,
        "feedback": dict(feedback) if feedback else None,
    }


def get_run_report(conn: "Connection", run_id: int) -> dict | None:
    """Données complètes d'un run pour la génération de rapport : métadonnées
    du run + annonces scorées (titre, score, catégorie, justification,
    localisation), triées par score décroissant. None si le run est introuvable.
    """
    run = conn.execute(
        """
        SELECT id AS run_id, mode, status, params, stats, config_snapshot,
               started_at, finished_at
        FROM runs WHERE id = %s
        """,
        (run_id,),
    ).fetchone()
    if run is None:
        return None

    rows = conn.execute(
        """
        SELECT l.id, l.title, l.price_amount, l.price_currency, l.url,
               p.name AS platform, l.structured, l.content_hash,
               s.category, s.suspicion_score, s.rationale
        FROM scores s
        JOIN listings l ON l.id = s.listing_id
        JOIN platforms p ON p.id = l.platform_id
        WHERE s.run_id = %s
        ORDER BY s.suspicion_score DESC
        """,
        (run_id,),
    ).fetchall()

    listings = []
    for r in rows:
        d = dict(r)
        structured = d.pop("structured", None) or {}
        d["location"] = structured.get("location")
        listings.append(d)

    return {"run": dict(run), "listings": listings}