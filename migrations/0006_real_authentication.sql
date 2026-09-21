-- CROWN AI — MIGRATION 0006: authentication
--
-- Authorisation was real from the start: roles come from the database,
-- row-level security enforces them, forged headers change nothing.
-- Authentication was not. POST /login took an email and no password, so anyone
-- who could reach the app could be anyone. Every control built on top of
-- identity rested on that.

BEGIN;

ALTER TABLE app_user
    ADD COLUMN password_hash    text,
    ADD COLUMN password_set_at  timestamptz,
    ADD COLUMN failed_attempts  integer NOT NULL DEFAULT 0,
    ADD COLUMN locked_until     timestamptz,
    ADD COLUMN last_sign_in_at  timestamptz;

COMMENT ON COLUMN app_user.password_hash IS
    'scrypt, as produced by crown.auth.hash_password. Never a plaintext or an '
    'unsalted digest. NULL means the account cannot sign in at all.';

-- An account with no password set cannot be signed into. That is the safe
-- default for the seeded users: they exist as owners and approvers before
-- anyone has given them credentials, and until then nobody can be them.
UPDATE app_user SET password_hash = NULL;

-- ============================================================
-- Operator capture (see ingest/capture.py)
--
-- The build environment cannot reach the amendment source, but a person with a
-- browser can. A capture is a real retrieval of the publisher's own page by a
-- named human, with the URL, the moment, the raw bytes and their hash retained.
--
-- That is materially better evidence than a search intermediary's summary and
-- materially weaker than a machine-verified fetch by the system itself. So it
-- may be STRONG — which means a gazetted amendment captured this way can be a
-- FACT — but never AUTHORITATIVE, which stays reserved for DIRECT_FETCH.
-- ============================================================

ALTER TABLE evidence_record DROP CONSTRAINT evidence_record_retrieval_method_check;
ALTER TABLE evidence_record
    ADD CONSTRAINT evidence_record_retrieval_method_check
        CHECK (retrieval_method IN ('DIRECT_FETCH', 'OPERATOR_CAPTURE',
                                    'SEARCH_RELAY', 'MANUAL_ENTRY'));

ALTER TABLE evidence_record DROP CONSTRAINT only_direct_fetch_can_be_strong;
ALTER TABLE evidence_record
    ADD CONSTRAINT retrieval_method_limits_reliability CHECK (
        CASE retrieval_method
            -- the system fetched it and can fetch it again
            WHEN 'DIRECT_FETCH'     THEN true
            -- a named human fetched it, and the bytes are kept
            WHEN 'OPERATOR_CAPTURE' THEN reliability <> 'AUTHORITATIVE'
            -- everything else is somebody's account of a page
            ELSE reliability NOT IN ('AUTHORITATIVE', 'STRONG')
        END
    );

-- Who captured it, and the bytes they captured, so any record can be rechecked.
ALTER TABLE evidence_record
    ADD COLUMN captured_by uuid REFERENCES app_user(id),
    ADD COLUMN capture_sha256 text;

ALTER TABLE evidence_record
    ADD CONSTRAINT capture_is_attributed_and_retained CHECK (
        retrieval_method <> 'OPERATOR_CAPTURE'
        OR (captured_by IS NOT NULL AND capture_sha256 IS NOT NULL)
    );

-- The raw bytes themselves, kept once per capture and shared by every evidence
-- record drawn from that page.
CREATE TABLE capture_artifact (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    uuid NOT NULL REFERENCES data_source(id),
    captured_by  uuid NOT NULL REFERENCES app_user(id),
    captured_at  timestamptz NOT NULL,
    source_url   text NOT NULL,
    sha256       text NOT NULL UNIQUE,
    byte_length  integer NOT NULL,
    raw_html     text NOT NULL,
    page_title   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX capture_artifact_sha_idx ON capture_artifact (sha256);

GRANT SELECT, INSERT ON capture_artifact TO crown_app;

COMMENT ON TABLE capture_artifact IS
    'The bytes a named human captured from the publisher''s page. Retained so '
    'every evidence record drawn from a capture can be rechecked against what '
    'was actually on the page at the time.';

COMMIT;
