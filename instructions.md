# instructions.md — Ranked-Choice Voting Polls (vote.sjolie.net)

Build a self-hosted ranked-choice voting (RCV) web application. Users create accounts,
create multi-question polls, share them via unique URLs, and vote by drag-and-drop
ranking. The app computes instant-runoff winners with round-by-round elimination and
Borda-count tiebreaks. Deployed to a Kubernetes homelab cluster behind Traefik at
`https://vote.sjolie.net`.

---

## 1. Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic migrations,
  asyncpg driver.
- **Database**: PostgreSQL 16 (deployed via CloudNativePG on the cluster — see §12).
- **Frontend**: React 18 + TypeScript + Vite. Drag-and-drop via `@dnd-kit/core` +
  `@dnd-kit/sortable` (must work with touch — mobile support is a launch requirement).
  Charts via `recharts`.
- **Packaging**: single container. Multi-stage Dockerfile: stage 1 builds the Vite
  frontend; stage 2 runs FastAPI (uvicorn) and serves the built static assets at `/`
  with the API under `/api/v1/`. SPA fallback: unknown non-`/api` paths return
  `index.html`.
- **Auth**: server-side sessions stored in Postgres. Session cookie: `HttpOnly`,
  `Secure`, `SameSite=Lax`, 30-day expiry, rotated on login.
- **Password hashing**: argon2id (`argon2-cffi`).
- No email, no external services, no third-party auth. Fully self-contained.

## 2. Accounts & Auth

- Registration: username + password + password confirmation. Nothing else.
  - Username: 3–20 chars, `[A-Za-z0-9_]`, case-insensitively unique, displayed as
    entered.
  - Password: min 8 chars, max 128, no composition rules. Reject if it equals the
    username (case-insensitive).
  - No password recovery. Lost password = lost account. State this on the signup form.
- Login: username (case-insensitive) + password. Generic error on failure (don't
  reveal whether the username exists).
- Logout invalidates the server-side session.
- **Rate limiting / bot protection is handled at the edge (Cloudflare + Traefik),
  NOT in the app.** Do not add captcha or app-level login throttling. Do log
  authentication failures with source IP (respect `X-Forwarded-For` from Traefik)
  so edge rules can be tuned.
- Users table includes an `is_admin` boolean (default false). There is no signup path
  to admin; it is set directly in the DB (document the SQL in the README).

## 3. Data model (Postgres)

Use these entities (exact column naming up to you; use UUIDv4 PKs, timestamps
`created_at`/`updated_at` everywhere):

- **users**: id, username, username_lower (unique), password_hash, is_admin,
  created_at.
- **sessions**: id (opaque token, random 256-bit), user_id, expires_at, created_at.
- **polls**: id, slug (unique, 8-char URL-safe random, e.g. base62 — not sequential,
  not guessable), creator_id, title, closes_at (nullable timestamp), closed_at
  (nullable — set by manual close or by the scheduler when `closes_at` passes),
  created_at.
- **questions**: id, poll_id, position (int, ordering), title, description (text,
  nullable), is_required (boolean, default true), created_at, updated_at.
- **options**: id, question_id, position (int), label, created_at.
- **ballots**: one per (user, question). id, question_id, user_id, ranking (JSONB
  array of option ids, full order), is_invalidated (boolean, default false),
  submitted_at, updated_at. Unique constraint on (question_id, user_id).
- **poll_bans**: (poll_id, user_id) — creator-issued ban, unique pair.
- **display_orders**: (question_id, user_id, order JSONB) — the randomized initial
  presentation order for that voter (see §7). Generated once on first view, reused
  thereafter.

Constraints:
- 1–20 questions per poll; 2–10 options per question. Enforce in the API.
- Poll title ≤ 200 chars; question title ≤ 300; description ≤ 2000; option label
  ≤ 200.

## 4. Poll lifecycle

- Any logged-in user can create a poll.
- Creation form: poll title, optional end date/time (`closes_at`, stored UTC, entered
  in the creator's local timezone), then questions added one at a time. Each question:
  title, optional description, required/optional toggle, and 2–10 options added one
  by one.
- A poll is **open** if `closed_at` is null and (`closes_at` is null or in the
  future). A background task (or lazy check on read — lazy check is fine and simpler)
  sets `closed_at` when `closes_at` passes.
- Creator can manually close an open poll at any time. Closing is permanent
  (no reopen). Closed polls: no new/changed votes; results remain visible to the
  creator and to users who voted.
- Creator can delete a poll (cascades questions, options, ballots, bans). Confirm
  dialog required.
- The creator MAY vote in their own poll.

## 5. Editing rules (the invalidation contract)

- **Question `description` is freely editable at any time and never affects votes.**
- Editing a question's **title**, or **adding/removing/renaming/reordering any of its
  options**, is allowed while the poll is open BUT **invalidates every ballot on that
  question**: set `is_invalidated = true` on all of that question's ballots and delete
  the stored `display_orders` for it. Affected voters must re-vote on that question.
- The UI must show the creator a warning dialog before any invalidating edit, stating
  exactly how many ballots will be invalidated.
- Poll title and `closes_at` are editable without consequence (extending or shortening
  the deadline is allowed while open; setting `closes_at` in the past closes the poll).
- Questions cannot be added or deleted after the poll has any ballots on ANY question
  — lock the question set at first vote. (Options within a question can still change
  via the invalidating-edit path above.)

## 6. Voting rules & ballot semantics

- Voting requires login. Any logged-in, non-banned user with the link can vote.
- Voting is **one question at a time**, in question order, with a progress indicator
  (e.g. "Question 2 of 5").
- **Full ranking per question**: the drag-and-drop list always contains every option;
  submitting a question submits a complete ordering. There is no partial ranking
  within a question.
- **Optional questions may be skipped** (a visible "Skip this question" action).
  Required questions cannot be skipped. Skipped = no ballot row for that question.
- **Partial poll submission is allowed**: each question's ballot is committed
  independently when the voter advances past it. A voter who answers 3 of 5 questions
  and leaves has 3 counted ballots. They can return later to finish.
- **Vote changes**: while the poll is open, a voter can revisit any question and
  re-rank; the ballot row is replaced (update `ranking`, clear `is_invalidated`,
  bump `updated_at`). When revisiting, show their current submitted ranking, not the
  random order.
- Server-side validation on every ballot submit: poll open, user not banned, ranking
  is a permutation of exactly the question's current option ids (reject stale
  submissions referencing changed options with a clear "this question changed,
  please re-rank" error).

## 7. Randomized presentation order

- On a voter's **first** view of a question they haven't voted on, generate a uniform
  random permutation of the options, persist it in `display_orders`, and render the
  DnD list in that order (positions labeled 1–N, N ≤ 10).
- Subsequent views before voting reuse the stored order (consistent across refreshes
  and devices). After voting, views show the voter's own submitted ranking.

## 8. RCV tabulation algorithm (implement exactly)

Tabulate **per question**, over all ballots for that question where
`is_invalidated = false` and the voter is not banned from the poll.

Definitions for a given round with remaining candidate set `R`:
- A ballot's *current choice* is its highest-ranked option that is in `R`.
  (Because rankings are full permutations, every ballot always has a current choice
  while `|R| ≥ 1`.)
- *Active ballots* = all counted ballots for the question.

Instant-runoff loop:
1. Round `k`: count each ballot's current choice among `R`.
2. If some candidate has **> 50%** of active ballots, they win. Record the round and
   stop.
3. If `|R| == 2` and the two are exactly tied, apply the tiebreak chain below to pick
   the winner directly (higher Borda wins), record, and stop.
4. Otherwise identify the candidate(s) with the fewest current-choice votes.
   Eliminate **exactly one** candidate per round:
   - If a single lowest candidate: eliminate it.
   - If multiple tie for lowest, use the tiebreak chain to pick ONE to eliminate.
5. Record the round's counts (per remaining candidate) and the eliminated candidate,
   then loop.

**Tiebreak chain** (used both for elimination ties and final two-way ties):
1. **Borda count**: for each tied candidate, over ALL active ballots, sum
   `(number_of_options_in_question − rank_position)` where rank_position is 1-indexed
   within the ballot's full original ranking (so 1st place on a 10-option question
   scores 9, last scores 0). Eliminate the candidate with the LOWEST Borda score
   (or, for a final two-way tie, the higher Borda score wins).
2. If still tied: fewest **round-1 first-choice votes** is eliminated (most wins,
   for a final tie).
3. If still tied: deterministic pseudo-random — seed a PRNG with
   `sha256(poll_id + question_id + "tiebreak")`, shuffle the tied candidate ids
   (sorted lexicographically first for determinism), eliminate the first. This makes
   results reproducible across recomputations.

Tally output per question (this feeds the charts and API):
```json
{
  "question_id": "...",
  "total_ballots": 42,
  "winner_option_id": "...",
  "rounds": [
    {
      "round": 1,
      "counts": {"opt_a": 18, "opt_b": 12, "opt_c": 8, "opt_d": 4},
      "eliminated": "opt_d",
      "tiebreak_used": null
    },
    {
      "round": 2,
      "counts": {"opt_a": 20, "opt_b": 13, "opt_c": 9},
      "eliminated": "opt_c",
      "tiebreak_used": "borda"
    }
  ]
}
```
- Compute tallies on demand per results request (poll sizes are small; do not build a
  caching layer, but structure the tabulator as a pure function
  `tabulate(options, ballots) -> TallyResult` and unit-test it heavily — see §13).

## 9. Results visibility

- **Voters** (anyone with ≥1 counted ballot in the poll): see **aggregate results
  only**, live, for every question — round-by-round breakdown and charts (§10). Never
  any voter identities or individual ballots. Questions they skipped still show
  aggregate results.
- **Non-voters** hitting the poll URL: see the voting flow only, no results.
- **Creator**: sees everything voters see, PLUS a per-question voter table: username,
  submitted_at, the full ranking they submitted, invalidation status. From this table
  the creator can:
  - **Invalidate a vote**: sets `is_invalidated = true`. The ballot leaves the tally
    immediately. The voter is notified in-UI ("your vote on Q2 was invalidated by the
    poll creator") and **may re-vote** on that question (re-voting replaces the row
    and clears the flag).
  - **Ban a user from the poll** (separate action): adds a `poll_bans` row. All the
    user's existing ballots in the poll are excluded from tallies (keep the rows,
    exclude at tabulation time), and they cannot submit or change votes anywhere in
    the poll. Banned users hitting the poll URL see "you cannot participate in this
    poll." Creator can un-ban (ballots count again, voting re-enabled).
- Results pages poll the API every 10 seconds for live updates (simple polling; no
  websockets).

## 10. Charts

Per question, on every results view:
1. **Headline bar chart**: grouped bars per option — **first-round votes vs final-round
   votes** side by side. Options eliminated before the final round show final = 0
   (visually distinct, e.g. hatched/dimmed). Mark the winner clearly.
2. **Round-by-round breakdown**: an expandable section showing each elimination round
   — a small bar chart (or table + bars) of that round's counts, which option was
   eliminated, and whether a tiebreak was used (and which stage: borda /
   first-choice / random). This is the full elimination story, not just two
   snapshots.
- Charts must render on mobile widths (stack, don't squeeze).

## 11. Pages & routing (frontend)

- `/login`, `/signup`.
- `/` (dashboard, requires login): two lists — **"Polls you created"** (title, open/
  closed status, vote count, link to manage/results) and **"Polls you've voted in"**
  (title, status, link to live results). Plus a "Create poll" button.
- `/create` — poll creation wizard (poll meta → add questions one by one → review →
  publish, which generates the slug).
- `/p/{slug}` — the shareable poll URL. Behavior by viewer:
  - Not logged in → redirect to login, then back to `/p/{slug}`.
  - Creator → management view (edit per §5, close, delete, results, voter table,
    invalidate/ban).
  - Banned → blocked message.
  - Voter with all answerable questions answered → live results.
  - Otherwise → voting flow (resume at first unanswered question), then results.
- `/admin` (requires `is_admin`): paginated tables of all users (username, created,
  poll count, admin flag) and all polls (title, creator, status, ballot count).
  Admin can **delete any poll** and **delete any user** (deleting a user cascades
  their polls, ballots, sessions; confirm dialog). Admin actions are logged
  (structured log line with admin id, action, target).
- API base `/api/v1/`; return 401 vs 403 correctly; all state-changing endpoints are
  POST/PUT/DELETE with JSON bodies; CSRF is mitigated by `SameSite=Lax` + requiring a
  custom header (`X-Requested-With: fetch`) on state-changing requests.

## 12. Deployment (sjolie.net cluster)

Produce a `deploy/` directory containing the manifests below, plus a `README.md`
section with build/push/apply steps. Cluster conventions (follow exactly):

- Namespace: `vote` (per-app namespace convention). Include the Namespace object.
- **Database**: CloudNativePG `Cluster` resource, 2 instances, image
  `ghcr.io/cloudnative-pg/postgresql:16` (pinned tag), storage via a PVC — 
  put Postgres on the `nfs-client` StorageClass
  `<STORAGE_CLASS_FOR_DB>` placeholder and call it out. App DB credentials from the
  CNPG-generated secret.
- **App**: Deployment (2 replicas, `app: vote` labels on deployment/pod/service
  selector), pinned image tag placeholder `<REGISTRY>/vote:<TAG>`, readiness probe on
  `/api/v1/healthz`, env from the CNPG secret, `TZ: America/New_York`.
- **Service**: `ClusterIP` (no LoadBalancer needed — HTTP behind Traefik).
- **IngressRoute** (Traefik v3, apiVersion `traefik.io/v1alpha1`), **in the `vote`
  namespace** (same namespace as the Service — cross-namespace refs 404):
  - Host `vote.sjolie.net`, entryPoints `[websecure, localsecure]` (internet-facing
    site that should also resolve on LAN/Tailscale).
  - `tls: {}` — the default TLSStore serves the wildcard `*.sjolie.net` cert. Do NOT
    set a `secretName`.
- Migrations: run Alembic as an initContainer (or a Job) before app start.
- Trust `X-Forwarded-For` from Traefik (uvicorn `--proxy-headers` +
  `--forwarded-allow-ips` set to the pod network, or FastAPI middleware) so auth
  failure logs carry real client IPs for edge tuning.
- Emit manifests as multi-document YAML in apply order: Namespace → CNPG Cluster →
  ConfigMap/Secret → Deployment → Service → IngressRoute. No commented-out
  `key: value` lines inside mappings. After the manifests, list every placeholder and
  give verification commands (`kubectl -n vote get ingressroute`, a `curl -I
  https://vote.sjolie.net/api/v1/healthz`).
- Edge note in README: bot/credential-stuffing protection is expected at Cloudflare
  (rate-limit rules on `/api/v1/auth/*`) — the app deliberately does not implement it.

## 13. Testing requirements

- **Tabulator unit tests are the priority.** Pure-function tests covering at minimum:
  simple majority in round 1; multi-round elimination; elimination tie broken by
  Borda; Borda tie broken by round-1 first choices; full tie falling through to the
  deterministic PRNG (assert reproducibility across two runs); final two-way exact
  tie; 2-option question; 10-option question; invalidated and banned ballots excluded.
- API integration tests: auth flow, poll creation limits (question/option counts),
  the invalidating-edit contract (§5), stale-ballot rejection (§6), permission matrix
  (creator vs voter vs non-voter vs banned vs admin) on results endpoints.
- Frontend: at least a smoke test that the sortable list reorders and submits the
  permutation.

## 14. Non-goals (do not build)

- No email, password recovery, or 2FA.
- No public poll discovery, browsing, or search — polls are reachable only by slug.
- No app-level captcha or login rate limiting (edge responsibility).
- No websockets; polling only.
- No poll reopening after close.
- No anonymous voting.
