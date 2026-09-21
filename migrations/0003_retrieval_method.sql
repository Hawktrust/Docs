-- CROWN AI — MIGRATION 0003: record how evidence was actually obtained
--
-- Why this exists.
--
-- Egress from the build environment reaches almost nothing: planning.vic.gov.au,
-- the planning schemes app and the council sites are all refused by the network
-- policy. One channel is open — a server-side web search — and it does return
-- real amendment identifiers.
--
-- It is not good enough to base evidence on. Two independent searches for the
-- same amendment disagreed: C232melt was reported gazetted on 7 May 2026 by one
-- and 8 May 2026 by the other, and two searches for C272hume returned
-- substantively different descriptions of what the amendment does. A summary of
-- a page is not the page.
--
-- Constitution §2 makes provenance mandatory, and the existing columns cannot
-- express the difference between "we fetched this" and "something told us about
-- this". Without that distinction a relayed claim, written with the real
-- upstream URL in source_url, is indistinguishable from a direct read. That is
-- the failure this migration prevents.

BEGIN;

ALTER TABLE evidence_record
    ADD COLUMN retrieval_method text NOT NULL DEFAULT 'DIRECT_FETCH'
        CHECK (retrieval_method IN ('DIRECT_FETCH', 'SEARCH_RELAY', 'MANUAL_ENTRY'));

COMMENT ON COLUMN evidence_record.retrieval_method IS
    'How this record was obtained. DIRECT_FETCH: the source_url was retrieved. '
    'SEARCH_RELAY: a search intermediary reported it; the URL was not fetched. '
    'MANUAL_ENTRY: a named human typed it in.';

-- Second-hand is not proof. Anything we did not retrieve ourselves may not be
-- called an authoritative or strong source, whatever the intermediary implied.
--
-- Read together with fact_needs_strong_source from 0001 — a FACT requires
-- AUTHORITATIVE or STRONG — this makes it impossible to classify a relayed or
-- hand-entered claim as FACT. The rule is enforced by the database rather than
-- left to the discipline of whoever writes the next ingestion path.
ALTER TABLE evidence_record
    ADD CONSTRAINT only_direct_fetch_can_be_strong
        CHECK (retrieval_method = 'DIRECT_FETCH'
               OR reliability NOT IN ('AUTHORITATIVE', 'STRONG'));

CREATE INDEX evidence_retrieval_method_idx ON evidence_record (retrieval_method);

-- The canonical amendment URLs live on the planning schemes app, a different
-- host from the departmental site already registered. Same publisher, same
-- licence question, so the register row is updated rather than duplicated.
UPDATE data_source
SET notes = notes || ' Canonical amendment URLs are served from '
                  || 'planning-schemes.app.planning.vic.gov.au in the form '
                  || '/{Scheme}/amendments/{AmendmentNumber}.'
WHERE code = 'VIC_PLANNING_AMENDMENTS';

COMMIT;
