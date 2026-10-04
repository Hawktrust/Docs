-- CROWN AI — MIGRATION 0028: re-verification that does not claim a re-reading
--
-- last_verified_at says when Crown last confirmed a record still reflects its
-- source. Nothing could move it except a full re-fetch and re-parse, so in
-- practice it moved when an amendment was first retrieved and then never again,
-- and a record could sit for a year while its column implied somebody had
-- checked. 0026 then gave evidence a shelf life measured from that column, so a
-- value that cannot be refreshed honestly is not cosmetic: it decides what
-- NO_EVIDENCE_IS_PAST_ITS_SHELF_LIFE reports.
--
-- HTTP already has the answer, and it is the publisher's answer rather than
-- ours. A server that hands back an ETag or a Last-Modified is offering to tell
-- us later whether the thing changed. Ask with If-None-Match or
-- If-Modified-Since and a 304 is the publisher saying: the page you read is
-- still the page I am serving. That is a real verification — stronger than
-- re-parsing our own guess at the markup — and it costs one small request rather
-- than a full document.
--
-- WHY THIS IS A PROVENANCE FEATURE AND NOT A CACHE.
--
-- The temptation is to treat 304 as "nothing to do" and move on. The point is
-- the opposite: a 304 is something Crown learned, from the publisher, at a
-- known time, and the record should say so. Three states have to stay
-- distinguishable, because they support different claims:
--
--   re-read      200, parsed again, fields rewritten. retrieved_at moves.
--   re-verified  304, unchanged at the source. last_verified_at moves and
--                nothing else does — in particular retrieved_at does NOT,
--                because Crown did not retrieve the document. A record must
--                never imply a fetch that did not happen.
--   unchecked    no validator stored, or the check failed. Nothing moves.
--
-- So retrieved_at keeps meaning "when we last had the bytes" and
-- last_verified_at means "when the publisher last confirmed them". Collapsing
-- the two would buy a tidier schema and lose the distinction that makes the
-- second one worth having.
--
-- WHO MAY HAVE VALIDATORS. Only a record the system fetched itself. An operator
-- capture is a person's browser session: whatever ETag that page carried belongs
-- to their request, not to one Crown can repeat, and storing it would let a
-- later 304 refresh last_verified_at on a record Crown has never fetched. The
-- constraint below refuses that outright rather than trusting the ingest path to
-- remember.

BEGIN;

ALTER TABLE evidence_record
    ADD COLUMN http_etag          text,
    ADD COLUMN http_last_modified text,
    ADD COLUMN last_revalidated_at timestamptz;

COMMENT ON COLUMN evidence_record.http_etag IS
    'The ETag the source served with this document, verbatim, for a later '
    'If-None-Match. Opaque: never parsed, compared or constructed — only handed '
    'back to the server that issued it.';

COMMENT ON COLUMN evidence_record.http_last_modified IS
    'The Last-Modified header as served, kept as text for a later '
    'If-Modified-Since. Stored unparsed because it goes back out unchanged, and '
    'because a header Crown reformatted is no longer the publisher''s statement.';

COMMENT ON COLUMN evidence_record.last_revalidated_at IS
    'When the source last answered 304 Not Modified for this document. Distinct '
    'from last_verified_at, which any verification moves, and from retrieved_at, '
    'which only a real retrieval moves.';

-- A validator is only meaningful for a retrieval Crown can repeat.
ALTER TABLE evidence_record
    ADD CONSTRAINT only_a_direct_fetch_carries_validators CHECK (
        retrieval_method = 'DIRECT_FETCH'
        OR (http_etag IS NULL AND http_last_modified IS NULL
            AND last_revalidated_at IS NULL)
    );

COMMENT ON CONSTRAINT only_a_direct_fetch_carries_validators ON evidence_record IS
    'An operator capture is a person''s browser request. Its ETag is not one '
    'Crown can present, so a 304 against it would refresh last_verified_at on a '
    'record the system never fetched.';

-- Revalidation is a claim about a document already retrieved, so it cannot
-- predate the retrieval it confirms.
ALTER TABLE evidence_record
    ADD CONSTRAINT revalidation_follows_retrieval CHECK (
        last_revalidated_at IS NULL OR last_revalidated_at >= retrieved_at
    );

-- The records a re-verification pass should look at: fetched by us, carrying
-- something to ask with, oldest verification first.
CREATE INDEX evidence_revalidation_due_idx
    ON evidence_record (last_verified_at)
    WHERE retrieval_method = 'DIRECT_FETCH'
      AND (http_etag IS NOT NULL OR http_last_modified IS NOT NULL);

COMMIT;
