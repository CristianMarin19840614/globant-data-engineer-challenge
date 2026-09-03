# Deployment

> **Status: not deployed.** This document is the path I would run, written out
> so it can be checked rather than assumed. Everything below has been made
> possible by the code — the image is stateless and every path is configurable
> — but I have not stood up a billed cloud account for a proof of concept.

## What makes it deployable

The application holds no state of its own. Three environment variables decide
where its data lives, and they are the only things that change between a
laptop, a container and a cloud runtime:

| Variable | Default | In a container |
|---|---|---|
| `DB_PATH` | `data/challenge.db` | `/data/challenge.db` on a mounted volume |
| `BACKUP_DIR` | `data/backups` | `/data/backups`, or an object-storage mount |
| `API_KEY` | empty (auth disabled) | injected from a secret store |

Locally that is `docker compose up`. In a cloud runtime it is the same image
with different values.

---

## Google Cloud Run

```bash
PROJECT=your-project
gcloud artifacts repositories create globant --repository-format=docker --location=us-central1

gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT/globant/challenge

gcloud run deploy globant-challenge \
  --image us-central1-docker.pkg.dev/$PROJECT/globant/challenge \
  --region us-central1 \
  --set-secrets API_KEY=globant-api-key:latest \
  --allow-unauthenticated
```

**The catch, and it matters:** Cloud Run's filesystem is ephemeral and each
revision may run several instances. A SQLite file on local disk would be lost
on restart and would not be shared between instances. So a real deployment
changes two things:

- **the database** → Cloud SQL for PostgreSQL, reached over the Cloud SQL
  connector. In the code this means replacing the `sqlite3` connection in
  `database.py` and adjusting `strftime` to `EXTRACT` in the two queries —
  roughly thirty lines, and the honest cost of having chosen `sqlite3`.
- **the backups** → a GCS bucket mounted at `BACKUP_DIR`, or `fastavro`
  writing to a `gs://` path. The AVRO files then land in exactly the shape
  BigQuery loads natively, which is a useful accident: the backup doubles as
  the ingestion format for a warehouse.

Scheduled backups become a Cloud Scheduler job hitting `POST /backup`, or a
Cloud Run Job running the same code without the web server.

---

## Azure Container Apps

```bash
az containerapp up \
  --name globant-challenge \
  --resource-group globant-rg \
  --source . \
  --ingress external --target-port 8000 \
  --env-vars API_KEY=secretref:api-key DB_PATH=/data/challenge.db
```

Same shape, different names: Azure Database for PostgreSQL Flexible Server
behind the connection settings, Blob Storage for the AVRO files, Key Vault for
the API key, and a Container Apps Job on a cron schedule for the nightly
backup.

---

## What I would put in place before calling it production

1. **A managed PostgreSQL instance**, for the reasons above — this is the
   first change, not an optimisation.
2. **Versioned schema migrations** (Alembic), so the schema can move forward
   across environments instead of being created on first run.
3. **OAuth2 with scopes** replacing the shared API key, so calls are
   attributable and revocable per client.
4. **Metrics and an alert on the rejection rate.** For a data pipeline, a
   rejection rate leaving its normal range is the single most useful signal
   there is, and today nothing watches it.
