-- CROWN AI — MIGRATION 0025: the way out has to be findable
--
-- APP 7.3(c) requires each direct marketing message to PROMINENTLY draw
-- attention to the opt-out. 0016 made the opt-out exist, 0024 made the channel
-- lawful, and neither looked at the message. A compliant artefact could carry
-- its way out in the twelfth line of a footer and nothing here would object.
--
-- THE MARKER. The link cannot be in the body when the body is written: it is
-- an HMAC over the artefact id and the artefact does not exist yet. So the body
-- carries '{{opt-out}}' where the link goes and crown/message.py substitutes it
-- at send time. Prominence is then a property of where that marker sits, which
-- is decidable — unlike the link itself, which is not there to inspect.
--
-- WHAT THIS CANNOT DECIDE, and it is most of what prominent means to a person:
-- font size, colour, contrast, whether the mail client renders it, and whether
-- a human notices. What it can decide is whether the way out was put somewhere
-- a reader would find it. That is a smaller claim than the Act makes and it is
-- stated here rather than implied, because a check that appears to settle a
-- question it has only narrowed is worse than an honest partial one.

BEGIN;

-- ============================================================
-- THE RULES
--
-- One implementation, used by the trigger and by the readiness view, so they
-- cannot disagree about what prominent means. Returns the reason it is not
-- prominent, or NULL. A sentence rather than a boolean because the reason is
-- the useful part: "not prominent" tells nobody what to change.
--
-- crown/message.py carries the same rules for the sake of a better error
-- before the row is attempted, and tests/test_prominence.py compares the two
-- on the same corpus. If they drift, the control silently stops firing.
-- ============================================================

CREATE OR REPLACE FUNCTION opt_out_is_prominent(body text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    marker      constant text := '{{opt-out}}';
    trailing_allowance constant int := 400;
    line_limit  constant int := 200;
    lead_in_len constant int := 200;
    pos         int;
    occurrences int;
    after_marker int;
    marker_line text;
    lead_in     text;
BEGIN
    IF body IS NULL THEN
        RETURN 'the message has no body';
    END IF;

    pos := position(marker in body);
    IF pos = 0 THEN
        RETURN 'the message does not say how to stop it';
    END IF;

    occurrences := (length(body) - length(replace(body, marker, '')))
                   / length(marker);
    IF occurrences > 1 THEN
        RETURN 'the message offers ' || occurrences || ' ways out; one is a '
               || 'way out, several is a maze';
    END IF;

    after_marker := length(body) - (pos + length(marker) - 1);
    IF after_marker > trailing_allowance THEN
        RETURN 'the way out has ' || after_marker || ' characters after it; a '
               || 'reader would have to hunt for it';
    END IF;

    SELECT l INTO marker_line
    FROM unnest(string_to_array(body, E'\n')) AS l
    WHERE strpos(l, marker) > 0
    LIMIT 1;
    IF length(marker_line) > line_limit THEN
        RETURN 'the way out is inside a paragraph rather than on a line of '
               || 'its own';
    END IF;

    -- A bare link draws attention to nothing. Something near it has to say
    -- what it is for.
    --
    -- Only what comes BEFORE the marker. The marker is literally '{{opt-out}}',
    -- so a window including it always matches 'opt[ -]?out' and the rule would
    -- be satisfied by its own subject — inert, and inert in the direction that
    -- passes everything.
    lead_in := lower(substring(body
                               from greatest(1, pos - lead_in_len)
                               for pos - greatest(1, pos - lead_in_len)));
    IF lead_in !~ 'stop|unsubscribe|opt[ -]?out|remove|no longer|leave you alone|hear from us' THEN
        RETURN 'nothing near the link tells the reader what it does';
    END IF;

    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION opt_out_is_prominent(text) IS
    'Why a message body''s opt-out would not be found, or NULL. Must stay '
    'identical to crown.message.fault(); tests/test_prominence.py compares '
    'them.';

-- ============================================================
-- THE CONSTRAINT
--
-- A trigger rather than a CHECK because the rule is a function of the body,
-- and on UPDATE as well as INSERT for the same reason 0024's is: a body
-- rewritten afterwards is the way around a rule enforced only at insert.
-- ============================================================

CREATE FUNCTION a_message_shows_the_way_out()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    problem text;
BEGIN
    IF NEW.artifact_type NOT IN ('OUTREACH_DRAFT', 'BUYER_BRIEF') THEN
        RETURN NEW;      -- an EXPORT is not addressed to anybody
    END IF;

    problem := opt_out_is_prominent(NEW.content ->> 'body');
    IF problem IS NOT NULL THEN
        RAISE EXCEPTION
            '%. APP 7.3(c) wants the opt-out drawn to the reader''s attention '
            'rather than merely present: put {{opt-out}} on its own line near '
            'the end, introduced by a sentence saying what it does.', problem
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER outbound_shows_the_way_out
    BEFORE INSERT OR UPDATE ON outbound_artifact
    FOR EACH ROW EXECUTE FUNCTION a_message_shows_the_way_out();

-- ============================================================
-- THE GATE REPORTS IT
-- ============================================================

CREATE OR REPLACE VIEW opt_out_prominence_exception AS
SELECT id,
       artifact_type,
       contact_scope,
       contact_identifier,
       opt_out_is_prominent(content ->> 'body') AS problem
FROM outbound_artifact
WHERE artifact_type IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
  AND opt_out_is_prominent(content ->> 'body') IS NOT NULL;

COMMENT ON VIEW opt_out_prominence_exception IS
    'Messages whose way out a reader would have to hunt for. Should always be '
    'empty; the trigger refuses the row. This is what says so.';

COMMIT;
