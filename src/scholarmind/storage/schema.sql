CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS scholarmind_sources (
    source_id text PRIMARY KEY,
    kind text NOT NULL,
    uri text NOT NULL,
    content_sha256 char(64),
    payload jsonb NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS scholarmind_sources_content_sha256_idx
    ON scholarmind_sources (content_sha256)
    WHERE content_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS scholarmind_evidence (
    evidence_id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES scholarmind_sources(source_id),
    text_content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    locator jsonb NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS scholarmind_evidence_source_idx
    ON scholarmind_evidence (source_id);
CREATE INDEX IF NOT EXISTS scholarmind_evidence_fts_idx
    ON scholarmind_evidence
    USING gin (to_tsvector('simple', text_content));

CREATE TABLE IF NOT EXISTS scholarmind_claims (
    claim_id text PRIMARY KEY,
    text_content text NOT NULL,
    status text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS scholarmind_claim_evidence (
    claim_id text NOT NULL REFERENCES scholarmind_claims(claim_id) ON DELETE CASCADE,
    evidence_id text NOT NULL REFERENCES scholarmind_evidence(evidence_id),
    PRIMARY KEY (claim_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS scholarmind_citations (
    citation_id text PRIMARY KEY,
    claim_id text NOT NULL REFERENCES scholarmind_claims(claim_id) ON DELETE CASCADE,
    evidence_id text NOT NULL REFERENCES scholarmind_evidence(evidence_id),
    source_id text NOT NULL REFERENCES scholarmind_sources(source_id),
    payload jsonb NOT NULL,
    UNIQUE (claim_id, evidence_id)
);

-- The dimension is intentionally unconstrained so local and hosted embedding
-- models can coexist. Production migrations should create a model-specific
-- expression/HNSW index after freezing the selected embedding dimension.
CREATE TABLE IF NOT EXISTS scholarmind_evidence_embeddings (
    evidence_id text NOT NULL REFERENCES scholarmind_evidence(evidence_id) ON DELETE CASCADE,
    model text NOT NULL,
    content_sha256 char(64),
    embedding vector NOT NULL,
    PRIMARY KEY (evidence_id, model)
);

ALTER TABLE scholarmind_evidence_embeddings
    ADD COLUMN IF NOT EXISTS content_sha256 char(64);
