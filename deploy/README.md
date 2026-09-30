# Running Crown somewhere real

The Flask development server is not a deployment. Everything here is ordinary
and none of it is surprising; it is written down because "deploy it" is a
sentence that hides about six decisions, and making them at 11pm on the day of
launch is how the wrong one gets made.

Nothing in this directory is secret. Every secret is named and none is stored.

---

## What has to be true before this is worth doing

`python scripts/readiness.py` exits non-zero while anything blocking fails.
Deploying a system the gate refuses is deploying a system that cannot lawfully
be used, which is a worse problem than not having deployed it.

## Start here

```bash
sudo ./deploy/provision.sh \
     --admin-dsn postgresql://admin:...@db.example:5432/postgres \
     --database crown_ai \
     --domain crown.example.com
```

It creates the database, applies all 28 migrations, seeds the configuration and
the data rights register **and nothing else**, gives `crown_app` a password while
proving it is not a superuser, cannot bypass row-level security and owns no
tables, writes `/etc/crown/crown.env` at mode 0600 with two freshly generated
secrets, and then **reads the readiness gate as `crown_app` and exits non-zero
if anything blocking fails.**

That last part is the point. The gate is a set of queries, so a connection
exempt from the policies reads it clean and reports itself ready — which is
exactly what a provisioning script must never do. Its exit code is the number of
blocking failures.

Re-running it is safe. It will not re-apply migrations to a database that
already has a schema, and it reuses the password already in the env file rather
than rotating it out from under a running service.

What it deliberately leaves to you: a human's password (interactive, because a
credential this script generated would be a credential in a log), ingesting real
evidence, and publishing the privacy policy.

## The pieces

| | |
|---|---|
| `provision.sh` | the above; the only file here you have to run |
| `crown.service` | systemd unit, gunicorn behind it |
| `gunicorn.conf.py` | workers, timeouts, logging to stdout for the journal |
| `crown.env.example` | every variable Crown reads, with what breaks if it is wrong |
| `nginx.conf.example` | TLS termination and the headers Crown expects |
| `backup.sh` | pg_dump, retention on the dumps themselves, and a restore check |
| `crown.cron` | the two scheduled jobs |

## The order

1. **A database that is not the application's owner.** `crown_app` owns
   nothing — row-level security does not constrain a table's owner, so an
   application connecting as the owner bypasses every policy in this schema.
   This is the single most consequential line in the file.

2. **Secrets from somewhere that is not a file in the repository.** systemd
   `EnvironmentFile=` pointing at `/etc/crown/crown.env`, mode 0600, owned by
   root. Better still, a secret manager; the unit reads the environment either
   way.

3. **TLS in front.** `CROWN_INSECURE_COOKIES` must be unset in production. It
   exists for the test client and turns off `Secure` on the session cookie.

4. **Both cron entries.** The alert run and the retention sweep. A system that
   alerts nobody will not be noticed when it stops working, and a retention
   period nobody applies is a promise in a privacy policy that the database
   does not keep.

5. **Restore the backup before you need to.** An untested backup is a belief.
   `backup.sh --verify-restore` does it against a scratch database and exits
   non-zero if the row counts do not match.

## What is deliberately not here

**Nothing that runs `psql` against production from a script in the repository.**
Migrations are applied by a person who has read them. Twenty-six forward-only
migrations with no down-steps have been fine so far; the first one applied to a
database holding real records is where that stops being fine, and an automated
runner would remove the moment where somebody notices.
