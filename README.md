# vote.sjolie.net — Ranked-Choice Voting Polls

Self-hosted ranked-choice (instant-runoff) voting. Users create multi-question
polls, share them by unguessable slug URLs, and vote by drag-and-drop ranking.
Winners are computed by instant-runoff with round-by-round elimination and a
Borda-count tiebreak chain.

- **Backend**: Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · asyncpg
- **Frontend**: React 18 · TypeScript · Vite · @dnd-kit (touch-capable) · recharts
- **Database**: PostgreSQL 16 (CloudNativePG on the cluster)
- **Auth**: server-side sessions in Postgres, argon2id password hashing
- **Deploy**: single multi-stage container behind Traefik v3 at `https://vote.sjolie.net`

---

## Repository layout

```
backend/          FastAPI app, tabulator, Alembic migrations, tests
  app/            application package (routers/, models, services, tabulator)
  alembic/        migration environment + versions
  tests/          tabulator unit tests + API integration tests
frontend/         Vite + React + TypeScript SPA
deploy/vote.yaml  Kubernetes manifests (multi-doc, in apply order)
Dockerfile        stage 1 builds the SPA, stage 2 runs uvicorn + serves it
```

---

## Local development

### Backend

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Point at a local Postgres (or use DATABASE_URL). Example:
export DATABASE_URL=postgresql://vote:vote@localhost:5432/vote
export COOKIE_SECURE=false          # allow http cookies locally

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The API is served under `http://localhost:8000/api/v1/`.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api -> :8000
```

### Tests

```bash
# Backend: tabulator unit tests (priority) + API integration tests +
# security/edge-case suite (path traversal, injection strings, input bounds,
# cascade deletes, permission matrix). Runs against SQLite — no Postgres needed.
cd backend && source .venv/bin/activate && pytest -q

# Frontend (Vitest + jsdom): api client / CSRF, auth context, results charts,
# voting flow, create wizard, and the sortable-ballot smoke test.
cd frontend && npm test
```

### Hardening notes

- **SQL injection**: all data access goes through SQLAlchemy with bound
  parameters; there is no string-built SQL. `test_security.py` stores injection
  strings and asserts they round-trip as inert data.
- **Path traversal**: the SPA fallback resolves requests through
  `resolve_static_file`, which rejects any path escaping the static root.
- **Resource exhaustion** (the memory-safe analog of buffer overflow): a
  `MaxBodySizeMiddleware` caps request bodies at 64 KiB, list inputs have
  `max_length` bounds, and pagination is clamped.
- **CSRF / XSS**: `SameSite=Lax` + a required `X-Requested-With: fetch` header on
  mutations; React auto-escapes all user text (no `dangerouslySetInnerHTML`).
- Responses carry `X-Content-Type-Options`, `X-Frame-Options`, and
  `Referrer-Policy` headers.

---

## Making a user an admin

There is **no signup path to admin**. Set the flag directly in the database
(via `psql` against the CNPG primary — see verification commands below):

```sql
UPDATE users SET is_admin = true WHERE username_lower = lower('your_username');
```

Admins get `/admin`: paginated user/poll tables, and the ability to delete any
poll or any user (deleting a user cascades their polls, ballots, and sessions).
Admin actions are emitted as structured log lines (`vote.admin ...`).

---

## Build, push, and deploy

The app is a single image. Migrations run as an `initContainer` using the same
image (`alembic upgrade head`) before the app starts.

### 1. Build & push the image

```bash
export REGISTRY=registry.example.com        # your registry
export TAG=$(git rev-parse --short HEAD)     # or a semver tag

docker build -t "$REGISTRY/vote:$TAG" .
docker push "$REGISTRY/vote:$TAG"
```

### 2. Fill in the placeholders in `deploy/vote.yaml`

| Placeholder                 | Meaning                                                        |
| --------------------------- | ------------------------------------------------------------- |
| `<REGISTRY>/vote:<TAG>`     | The image you just pushed (appears twice: init + app).        |
| `<STORAGE_CLASS_FOR_DB>`    | StorageClass for the Postgres PVC — use the **`nfs-client`** class on this cluster. |

Everything else follows cluster conventions and needs no changes.

```bash
sed -i "s#<REGISTRY>/vote:<TAG>#$REGISTRY/vote:$TAG#g" deploy/vote.yaml
sed -i "s#<STORAGE_CLASS_FOR_DB>#nfs-client#g" deploy/vote.yaml
```

### 3. Apply

Requires the CloudNativePG operator and Traefik v3 already installed on the
cluster. The manifest is a single multi-document file in apply order
(Namespace → CNPG Cluster → ConfigMap → Deployment → Service → IngressRoute):

```bash
kubectl apply -f deploy/vote.yaml
```

CloudNativePG creates the `vote-db-app` secret (key `uri`) that the Deployment
consumes for `DATABASE_URL`. Wait for the database, then the app rollout:

```bash
kubectl -n vote wait --for=condition=Ready cluster/vote-db --timeout=300s
kubectl -n vote rollout status deploy/vote
```

### 4. Verify

```bash
kubectl -n vote get ingressroute
kubectl -n vote get pods,svc
curl -I https://vote.sjolie.net/api/v1/healthz     # expect HTTP/2 200

# psql into the primary (e.g. to set an admin flag):
kubectl -n vote exec -it vote-db-1 -- psql app
```

---

## Deployment notes

- **Namespace**: `vote`. The IngressRoute lives in the **same namespace** as the
  Service (Traefik cross-namespace service refs 404).
- **TLS**: `tls: {}` — the default TLSStore serves the wildcard `*.sjolie.net`
  cert. No `secretName` is set.
- **Entry points**: `websecure` (internet) and `localsecure` (LAN/Tailscale).
- **Real client IPs**: uvicorn runs with `--proxy-headers --forwarded-allow-ips '*'`
  so it trusts Traefik's `X-Forwarded-For`. Authentication-failure logs
  (`vote.auth auth.login.failure ... ip=<client>`) therefore carry the real
  client IP for edge rule tuning.

### Edge (Cloudflare) responsibility

Bot / credential-stuffing protection is expected at **Cloudflare**, with
rate-limit rules on `/api/v1/auth/*`. **The application deliberately implements
no captcha or login rate limiting** — it only logs auth failures with the source
IP so the edge rules can be tuned. CSRF is mitigated by `SameSite=Lax` session
cookies plus a required `X-Requested-With: fetch` header on all state-changing
requests.

---

## Ranked-choice tabulation (summary)

Tabulation is a pure function, `app/tabulator.py::tabulate(options, ballots,
poll_id, question_id)`, computed on demand per results request (no caching). Per
question, over all non-invalidated ballots from non-banned voters:

1. Count each ballot's highest-ranked remaining candidate.
2. A candidate with **> 50%** of active ballots wins.
3. Otherwise eliminate exactly one lowest candidate and repeat. Ties (for
   elimination, or a final two-way tie) break by: **Borda count** → **round-1
   first-choice votes** → **deterministic PRNG** seeded from
   `sha256(poll_id + question_id + "tiebreak")` (reproducible across recomputes).

See `backend/tests/test_tabulator.py` for the full behavioral spec.
