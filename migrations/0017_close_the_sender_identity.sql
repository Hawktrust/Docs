-- CROWN AI — MIGRATION 0017: the table 0016 left open
--
-- tests/test_review_0013.py asks one question of every table: does it have a
-- row-level security policy, or is it on the short list of things deliberately
-- not row-scoped? outbound_identity, added yesterday in 0016, was neither.
--
-- This is the third time. buyer_mandate_real leaked through a view in 0004,
-- market_actor leaked through the base table in 0013, and now a new table
-- arrived with no policy at all. The test is the reason it was caught within
-- one run rather than at some later review, and it is worth saying plainly:
-- the control that works here is the regression test, not the care taken while
-- writing the migration. Care has now failed three times.
--
-- Fixed in a new migration rather than by editing 0016, which is already
-- pushed. A numbered migration that has been applied anywhere does not change
-- underneath anybody; that rule cost nothing here and is the reason it holds
-- when it does cost something.

BEGIN;

-- ============================================================
-- WHO MAY SEE AND SET THE SENDER
--
-- Reading it is ordinary: crown/outbound.py loads the active identity whenever
-- anybody drafts a message, so every working role needs SELECT.
--
-- Deciding it is not ordinary. Who Crown sends as is the claim the Spam Act
-- holds it to, and it belongs with the roles that answer for that.
-- ============================================================

ALTER TABLE outbound_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_identity FORCE ROW LEVEL SECURITY;

CREATE POLICY identity_read_by_all ON outbound_identity FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY identity_set_by_compliance ON outbound_identity FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','COMPLIANCE'));

CREATE POLICY identity_superseded_by_compliance ON outbound_identity FOR UPDATE
    USING (crown_role() IN ('ADMIN','COMPLIANCE'));

-- ============================================================
-- AN IDENTITY IS SUPERSEDED, NEVER EDITED
--
-- Section 17 of the Spam Act wants the sender information in a message to be
-- accurate, and section 18 wants it to stay that way for 30 days after it was
-- sent. An artefact records which identity it went out under. If the address on
-- that row can be edited afterwards, every message already sent starts
-- misrepresenting its sender, silently and retrospectively.
--
-- So the content is frozen, exactly as 0004 froze the score on an approved
-- match. Deactivating an identity and recording when is allowed; changing what
-- it says is not. To change the wording, insert a new row and supersede the old
-- one, which is what versioning it was for.
-- ============================================================

CREATE FUNCTION outbound_identity_is_versioned_not_edited()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.legal_entity_name, NEW.abn, NEW.postal_address,
        NEW.contact_email, NEW.contact_phone, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.legal_entity_name, OLD.abn, OLD.postal_address,
        OLD.contact_email, OLD.contact_phone, OLD.created_by, OLD.created_at)
    THEN
        RAISE EXCEPTION
            'an outbound identity is superseded, not edited: messages already '
            'sent record this row as their sender, and the Spam Act requires '
            'that to stay accurate for 30 days. Insert a new identity and set '
            'is_active = false on this one.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER outbound_identity_content_is_frozen
    BEFORE UPDATE ON outbound_identity
    FOR EACH ROW EXECUTE FUNCTION outbound_identity_is_versioned_not_edited();

-- Superseding is an update, so the application needs the verb. The trigger
-- above is what makes granting it safe.
GRANT UPDATE ON outbound_identity TO crown_app;

COMMIT;
