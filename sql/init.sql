-- =============================================================================
--  sql/init.sql — schéma PostgreSQL mémoire épisodique
-- -----------------------------------------------------------------------------
--  Exécuté une seule fois à la création du volume postgres_data.
--  Couvre : historique structuré, déduplication, scoring, versioning des
--  modèles, feedback enquêteur, et chaîne de traçabilité (audit_log).
-- =============================================================================

-- --- Types énumérés (auto-documentés) ----------------------------------------
CREATE TYPE collection_mode   AS ENUM ('A', 'B');         -- A=surveillance, B=exploration
CREATE TYPE run_status        AS ENUM ('running', 'completed', 'failed');
CREATE TYPE risk_category     AS ENUM ('tabac','alcool','cites','viande','contrefacon','arme','autre','aucune');
CREATE TYPE feedback_decision AS ENUM ('confirme','rejete','incertain');

-- --- Version du schéma --------------------------------------------------------
CREATE TABLE schema_version (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO schema_version (version) VALUES ('0.2.0-persistance');

-- --- Plateformes (référentiel) -----------------------------------------------
CREATE TABLE platforms (
    id             SMALLSERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,                  -- ricardo, anibis, tutti, facebook
    base_url       TEXT,
    antibot_rating SMALLINT,                              -- 1..5 (résistance anti-bot estimée)
    default_mode   collection_mode NOT NULL DEFAULT 'A',
    active         BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO platforms (name, base_url, antibot_rating, default_mode) VALUES
    ('ricardo',  'https://www.ricardo.ch',                3, 'A'),
    ('anibis',   'https://www.anibis.ch',                 2, 'A'),
    ('tutti',    'https://www.tutti.ch',                  2, 'A'),
    ('mock_shop', 'http://mock_shop:8000',                1, 'A'),
    ('facebook', 'https://www.facebook.com/marketplace',  5, 'B'),
    -- Jeu de test : données fictives, isolées des vraies plateformes
    ('fake_market', 'http://fake_market:8000',            1, 'A');

-- --- Versioning des modèles/prompts (reproductibilité, audit) -----------------
CREATE TABLE model_versions (
    id             SERIAL PRIMARY KEY,
    agent          TEXT NOT NULL,                         -- LLM-EXPAND/PARSE/SCORE/CODE/BROWSE
    model_name     TEXT NOT NULL,                         -- ex: ollama/qwen3:8b
    prompt_version TEXT,                                   -- ex: analyzer_v1
    prompt_hash    TEXT,                                   -- SHA-256 du fichier de prompt
    topology       TEXT,                                   -- locale/centrale/cloud à l'exécution
    params         JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active      BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (agent, model_name, prompt_version, prompt_hash)
);

-- --- Sessions d'exécution du pipeline ----------------------------------------
CREATE TABLE runs (
    id              BIGSERIAL PRIMARY KEY,
    mode            collection_mode NOT NULL,
    trigger         TEXT NOT NULL DEFAULT 'manuel',       -- manuel/planifie/n8n
    status          run_status NOT NULL DEFAULT 'running',
    params          JSONB NOT NULL DEFAULT '{}',          -- requêtes, plateformes ciblées...
    stats           JSONB NOT NULL DEFAULT '{}',          -- compteurs (collectées, scorées...)
    config_snapshot JSONB NOT NULL DEFAULT '{}',          -- topologie + modèles utilisés
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- --- Annonces (entité centrale, dédupliquée) ---------------------------------
CREATE TABLE listings (
    id                BIGSERIAL PRIMARY KEY,
    platform_id       SMALLINT NOT NULL REFERENCES platforms(id),
    external_id       TEXT NOT NULL,                       -- id de l'annonce sur la plateforme
    url               TEXT,
    title             TEXT,
    description       TEXT,
    price_amount      NUMERIC(12,2),
    price_currency    TEXT,
    seller_label      TEXT,                                -- libellé vendeur (pseudonymisable)
    structured        JSONB NOT NULL DEFAULT '{}',         -- sortie LLM-PARSE
    content_hash      TEXT NOT NULL,                       -- SHA-256 du contenu normalisé (dédup)
    observation_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform_id, external_id)                      -- clé naturelle : 1 annonce = 1 ligne
);
CREATE INDEX idx_listings_content_hash ON listings(content_hash);
CREATE INDEX idx_listings_last_seen    ON listings(last_seen_at);

-- --- Observations (chaque apparition d'une annonce dans un run) ---------------
CREATE TABLE listing_observations (
    id           BIGSERIAL PRIMARY KEY,
    listing_id   BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    run_id       BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    content_hash TEXT NOT NULL,                            -- hash au moment de l'observation
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_obs_listing ON listing_observations(listing_id);
CREATE INDEX idx_obs_run     ON listing_observations(run_id);

-- --- Scores de suspicion (sortie LLM-SCORE) ----------------------------------
CREATE TABLE scores (
    id                 BIGSERIAL PRIMARY KEY,
    listing_id         BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    run_id             BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    model_version_id   INTEGER REFERENCES model_versions(id),
    category           risk_category NOT NULL,             -- catégorie dominante
    suspicion_score    NUMERIC(4,3) NOT NULL CHECK (suspicion_score >= 0 AND suspicion_score <= 1),
    category_breakdown JSONB NOT NULL DEFAULT '{}',        -- score par catégorie
    rationale          TEXT,                                -- justification du modèle
    rag_refs           JSONB NOT NULL DEFAULT '[]',        -- chunks customs_rules utilisés
    scored_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_scores_listing ON scores(listing_id);
CREATE INDEX idx_scores_queue   ON scores(category, suspicion_score DESC); -- file d'investigation
CREATE INDEX idx_scores_run     ON scores(run_id);

-- --- Feedback enquêteur (human-in-the-loop) ----------------------------------
CREATE TABLE investigator_feedback (
    id                 BIGSERIAL PRIMARY KEY,
    listing_id         BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    score_id           BIGINT REFERENCES scores(id) ON DELETE SET NULL,
    investigator_ref   TEXT NOT NULL,                       -- identifiant enquêteur (pseudonyme)
    decision           feedback_decision NOT NULL,
    category_corrected risk_category,                       -- correction éventuelle
    comment            TEXT,
    decided_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_to_qdrant BOOLEAN NOT NULL DEFAULT false,      -- poussé vers confirmed_suspicious ?
    ingested_at        TIMESTAMPTZ
);
CREATE INDEX idx_feedback_listing ON investigator_feedback(listing_id);
CREATE INDEX idx_feedback_pending_ingest ON investigator_feedback(ingested_to_qdrant)
    WHERE ingested_to_qdrant = false;                       -- requête d'ingestion différée

-- --- Journal d'audit (chaîne de traçabilité) --------------------------------
--  Chaque entrée référence le hash de la précédente -> chaîne inviolable.
--  prev_hash / entry_hash sont calculés côté application (repository), pas en
--  SQL, pour rester explicites et testables.
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    listing_id  BIGINT REFERENCES listings(id) ON DELETE SET NULL,
    actor       TEXT NOT NULL,                              -- agent / 'system' / 'investigator'
    action      TEXT NOT NULL,                              -- collect/parse/score/validate/ingest...
    detail      JSONB NOT NULL DEFAULT '{}',
    prev_hash   TEXT,                                       -- entry_hash de l'entrée précédente
    entry_hash  TEXT NOT NULL,                              -- SHA-256(prev_hash + contenu)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_created ON audit_log(created_at);
CREATE INDEX idx_audit_listing ON audit_log(listing_id);
CREATE INDEX idx_audit_run     ON audit_log(run_id);

-- --- Versions d'extracteur (réparation LLM-CODE supervisée) -----------------
--  Les sélecteurs d'un extracteur déterministe sont versionnés en base. Quand un
--  site change et casse l'extraction, LLM-CODE propose de nouveaux sélecteurs :
--  ils sont insérés en CANDIDAT (status='pending'), JAMAIS appliqués seuls. Un
--  administrateur les valide (status='active', l'ancien passe 'superseded') ou
--  les rejette ('rejected'). Human-in-the-loop étendu au code : le modèle
--  propose, l'humain décide. repair_history conserve la trace auditable.
CREATE TYPE extractor_status AS ENUM ('active', 'pending', 'rejected', 'superseded');

CREATE TABLE extractor_versions (
    id             BIGSERIAL PRIMARY KEY,
    platform       TEXT NOT NULL,                            -- nom de plateforme (ex. mock_shop)
    selectors      JSONB NOT NULL,                           -- {champ: sélecteur CSS}
    status         extractor_status NOT NULL DEFAULT 'pending',
    source         TEXT NOT NULL DEFAULT 'manual',           -- 'manual' | 'llm-code'
    repair_history JSONB,                                    -- trace de réparation (si llm-code)
    validation     JSONB,                                   -- enregistrement ré-extrait par le candidat
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at     TIMESTAMPTZ,
    decided_by     TEXT
);
-- Au plus UN extracteur actif par plateforme (garantie d'intégrité).
CREATE UNIQUE INDEX ux_extractor_active ON extractor_versions(platform)
    WHERE status = 'active';
CREATE INDEX idx_extractor_pending ON extractor_versions(status)
    WHERE status = 'pending';

-- Seed : sélecteurs v1 du mock_shop, actifs par défaut (terrain de démo LLM-CODE).
INSERT INTO extractor_versions (platform, selectors, status, source) VALUES
    ('mock_shop',
     '{"title":"h1.listing-title","price":".listing-price","seller":".seller","location":".location","description":".listing-description"}',
     'active', 'manual');