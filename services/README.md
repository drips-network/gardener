# 🧤 Services

REST API and background worker architecture for running Gardener's **[core dependency analysis](../gardener/README.md)**), persisting results, and serving recommended Drip Lists for the [Drips Network app](https://www.drips.network/app).

## Table of contents
- [🧤 Services](#-services)
  - [Table of contents](#table-of-contents)
  - [Architecture](#architecture)
    - [Components](#components)
  - [Quick start](#quick-start)
    - [Local development with Docker Compose](#local-development-with-docker-compose)
  - [Object storage](#object-storage)
  - [API endpoints](#api-endpoints)
    - [Health check](#health-check)
    - [Submit analysis](#submit-analysis)
    - [Check job status](#check-job-status)
    - [Get latest results](#get-latest-results)
  - [Deployment example (Railway, Nixpacks)](#deployment-example-railway-nixpacks)
  - [Operational notes](#operational-notes)
  - [Runtime prediction](#runtime-prediction)
    - [Config](#config)
  - [Database schema](#database-schema)
    - [Core tables](#core-tables)
    - [Migrations](#migrations)
  - [Troubleshooting](#troubleshooting)
  - [API client examples](#api-client-examples)
    - [Typescript](#typescript)

## Architecture

```text
services/
├── api/                        # FastAPI REST server
│   ├── app/
│   │   ├── main.py             # API endpoints and middleware
│   │   ├── schemas.py          # Request/response models
│   │   └── security.py         # HMAC authentication
│   └── Dockerfile
├── worker/                     # Celery background workers
│   ├── app/
│   │   ├── main.py             # Worker configuration
│   │   └── tasks.py            # Analysis task implementation
│   └── Dockerfile
├── shared/                     # Microservice shared utilities
│   ├── models.py               # Database models
│   ├── database.py             # DB engine/session helpers
│   ├── config.py               # Configuration management
│   ├── storage.py              # Storage backends
│   ├── compression.py          # Graph compression/decompression
│   ├── url_cache.py            # Package URL cache helpers
│   ├── drip_list_processor.py  # Drip List aggregation + normalization
│   ├── estimator.py            # Job runtime prediction
│   ├── celery_client.py        # Celery app factory/client
│   ├── utils.py                # URL normalization and helpers
│   └── persistence/
│       └── alembic/            # Database migrations
└── scripts/
    ├── gen_token.py            # HMAC token generation helper
    └── fit_duration_model.py   # Fit model for job runtime prediction
```

### Components
* **API** (FastAPI): queues analysis jobs, exposes status and results
* **Worker** (Celery): asynchronous processing of analysis jobs (involving cloning repos, analyzing source, package URL resolution, results storage)
* **Storage** (Postgres): of job metadata, compressed dependency graphs, analysis results, and cached package URLs
* **Message broker** (Redis): for job queue and rate limiting

## Quick start

### Local development with Docker Compose

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with required variables:
# - POSTGRES_PASSWORD (required)
# - HMAC_SHARED_SECRET (required, 32+ chars)
# - S3_* variables (required): point to MinIO/S3-compatible object storage
#   S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET, S3_REGION,
#   S3_FORCE_PATH_STYLE=true, S3_ARTIFACTS_PREFIX=gardener/v1

# 2. Start services
docker-compose up -d
# If you added a local MinIO service to compose, create the bucket once
#   mc alias set local "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY"
#   mc mb local/"$S3_BUCKET"

# 3. Check health, version
curl http://localhost:8000/health
curl http://localhost:8000/version

# 4. Generate auth token (requires HMAC_SHARED_SECRET in env)
REPO_URL='https://github.com/owner/repo'
TOKEN=$(python services/scripts/gen_token.py --url "$REPO_URL")

# 5. Submit analysis job
curl -X POST "http://localhost:8000/api/v1/analyses/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Repo-Url: $REPO_URL" \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"$REPO_URL\"}"
```
* Only the job submission endpoint (**POST `/api/v1/analyses/run`**) requires authentication
* The token is valid for 5 minutes by default; this can be configured via `TOKEN_EXPIRY_SECONDS` in `services/shared/config.py
* As an alternative to (5), you can execute the curl command printed by running:
```bash
python services/scripts/gen_token.py --url "$REPO_URL" --print-curl
```

## Object storage

Gardener stores large artifacts in an S3-compatible object store (e.g., MinIO):

- Artifacts per job
  - `graph.pkl` — NetworkX pickle of the dependency graph
  - `results.json` — lightweight analysis results
- Object key layout
  - `"{S3_ARTIFACTS_PREFIX}/{canonical_url}/{commit_sha}/{job_id}/{artifact}"`
  - Example: `gardener/v1/github.com/owner/repo/abcd1234.../job-uuid/graph.pkl`
- Checksums & metadata
  - Size, ETag, MD5, SHA‑256, optional VersionId are captured
- Postgres database pointer table
  - `analysis_artifacts` links each job to its artifacts and metadata

Environment variables (API and Worker):

- `S3_ENDPOINT_URL` - e.g., `https://bucket-<id>.up.railway.app` for Railway MinIO
- `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` - MinIO credentials
- `S3_BUCKET` - pre-created bucket (e.g., `gardener-artifacts`)
- `S3_REGION` - any string (e.g., `eu-west-3`)
- `S3_FORCE_PATH_STYLE` - `true` for MinIO and most S3-compatible endpoints
- `S3_ARTIFACTS_PREFIX` - `gardener/v1` by default

Ensure to create the bucket once via `mc` or `aws`.

## API endpoints

### Health check

```http
GET /health
```
* No authentication required

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "database": true,
  "redis": true
}
```

### Submit analysis

```http
POST /api/v1/analyses/run
Authorization: Bearer <token>
X-Repo-Url: <repository-url>
```

**Request Body**:
```json
{
  "repo_url": "https://github.com/owner/repo",
  "drip_list_max_length": 200,
  "force_url_refresh": false
}
```
* Authentication required (see [Local Development](#local-development-with-docker-compose) above)
* `repo_url` — required — ⚠️ must be prefixed with `https://`
* `force_url_refresh` — optional — if `true` (default is `false`), requires the worker to look up via package registries the repository URL of every external dependency in the project, and to overwrite those dependencies' URLs in the `package_url_cache` table
* `drip_list_max_length` — optional — limits the maximum number of third-party GitHub-hosted dependencies in the final recommended Drip List. By default, it is set to 200. If set to some number below the total number of third-party GitHub-hosted dependencies of an analyzed project, the final list will be limited to that length, and the `split_percentage` values stored in the `drip_list_items` table (queried by the [Latest Results endpoint](#get-latest-results)) will be calculated such that the project's resulting limited set's `split_percentage` values sum to 100%

**Response**:
```json
{
  "job_id": "uuid",
  "repository_id": "uuid",
  "status": "PENDING",
  "message": "Analysis queued successfully"
}
```

### Check job status

```http
GET /api/v1/analyses/{job_id}
```
* No authentication required
* Use the `job_id` returned by **POST** `/api/v1/analyses/run`


**Response**:
```json
{
  "job_id": "uuid",
  "repository_id": "uuid",
  "status": "COMPLETED",
  "created_at": "2024-01-01T00:00:00Z",
  "started_at": "2024-01-01T00:00:10Z",
  "completed_at": "2024-01-01T00:05:00Z",
  "commit_sha": "abc123",
  "error_message": null,
  "predicted_duration_seconds": 42.123,
  "elapsed_seconds": 299.876
}
```

### Get latest results

By repository ID:
```http
GET /api/v1/repositories/{repository_id}/results/latest
```
Or by repository URL:
```http
GET /api/v1/repositories/results/latest?repository_url=github.com/owner/repo
```
* No authentication required
* `repository_url` may be prefixed with `https://`, but `repository_url` at this endpoint also accepts `forge.com/owner/repo` patterns
* ⚠️ The scored dependencies in the final recommended Drip List are limited to dependencies hosted on GitHub, as currently GitHub is the only forge that Drips's funding and claiming flows support

**Response**:
```json
{
  "job_id": "uuid",
  "repository_id": "uuid",
  "commit_sha": "abc123",
  "completed_at": "2024-01-01T00:05:00Z",
  "results": [
    {
      "package_name": "requests",
      "package_url": "https://github.com/psf/requests",
      "split_percentage": 25.0000
    },
    {
      "package_name": "requests",
      "package_url": "https://github.com/sympy/sympy",
      "split_percentage": 33.0000
    }
  ]
}
```

## Deployment example (Railway, Nixpacks)

Create two services (API + Worker) pointing to this repository, add Postgres and Redis, and then:

**API**

* **Build**: `pip install --upgrade pip && pip install -e '.[service]'`
* **Start**: `uvicorn services.api.app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers`
* **Variables**:
  * `ENVIRONMENT=production`, `DEBUG=false`
  * `HMAC_SHARED_SECRET` (≥ 32 chars)
  * `ALLOWED_HOSTS` (your Railway domain or `*.up.railway.app,*.railway.app`)
  * `DATABASE_URL` = Postgres (Railway reference)
  * `REDIS_URL` = Redis (Railway reference)
  * `RUN_DB_MIGRATIONS=1` (default, migrations run automatically during deployment startup)
    * Set `RUN_DB_MIGRATIONS=0` only if you prefer to manage Alembic migrations manually
  * Optional (runtime prediction): set both on API for enqueue-time predictions
    * `DURATION_MODEL_JSON` — one-line JSON with model params (see Runtime prediction below)
    * `GITHUB_TOKEN` — GitHub PAT to enable `/languages` and root `/contents` calls
  * Versioning: No manual bumps; `/version` returns the installed package
    version (from package metadata). If you need to override, set `SERVICE_VERSION`

**Worker**

* **Build**: `pip install --upgrade pip && pip install -e '.[service]' && cd gardener/external_helpers/hardhat_config_parser && npm ci --omit=dev`
  * This installs the Hardhat parser helper, which is optional but recommended to support Solidity projects
* **Start**: `celery -A services.worker.app.main worker --loglevel=info --concurrency=1 -n gardener-worker@%h`
* **Variables**:
  `ENVIRONMENT=production`, `DEBUG=false`,
  `HMAC_SHARED_SECRET` (same as API),
  `DATABASE_URL`, `REDIS_URL`,
  `ALLOWED_HOSTS` (any non-"\*"),
  `NIXPACKS_PKGS=git nodejs_20` (`git` is required for cloning; `nodejs_20` is needed if you build the Hardhat TS remappings helper)
  Optional (runtime prediction fallback):
  `DURATION_MODEL_JSON`, `GITHUB_TOKEN` — only needed if you want the worker to backfill predictions when API couldn't

## Operational notes

* **Idempotency**: resubmitting the same repo while a job is `RUNNING` returns the existing job. New submissions after completion create new jobs
* **Stale watchdog**: API marks actual started jobs as stale if they exceed the max running window
* **Rate limiting**: Redis-backed rate limiting is configurable via `RATE_LIMIT_PER_MINUTE` (default: `60`)
* **Security**: use HTTPS and set `ALLOWED_HOSTS` to your domain(s). Keep `DEBUG=false` in production
* **URL caching**: external dependencies' repository URLs are cached in `package_url_cache`; when a job is submitted with the `--force_url_refresh` flag, cached repo URLs will get overwritten by newly fetched matches
* **Runtime prediction**: when configured (see below), POST `/api/v1/analyses/run` returns `predicted_duration_seconds`, and GET `/api/v1/analyses/{job_id}` returns both `predicted_duration_seconds` and a live `elapsed_seconds` (frozen at completion). `elapsed_seconds` is null until the worker sets `started_at` (i.e., until the job begins cloning the to-be-analyzed repository). (Intended for use cases like client-side progress approximation via something like `min(0.98, elapsed_seconds / predicted_duration_seconds)` until status becomes `COMPLETED`.)
* **Versioning**: the API reads its version from the installed `gardener` package. Publishing a new package or shipping a new image updates the version endpoint automatically

## Runtime prediction

Gardener can estimate how long an analysis will run. This feature is optional and controlled purely via environment variables (no runtime ML dependencies).

### Config

Set these on the API (required for enqueue-time predictions) and optionally on the Worker (fallback if API is unable to compute):

- `GITHUB_TOKEN` — a Personal Access Token to be used for the GitHub API's `/repos/{owner}/{repo}/languages` and `/repos/{owner}/{repo}/contents` endpoints
- `DURATION_MODEL_JSON` — a one-line JSON blob describing a log-linear model

Use `services/scripts/fit_duration_model.py` to fit a parsimonious OLS model using some empirical dataset of Gardener analysis job runtimes, and emit a JSON file. Replace the `DURATION_MODEL_JSON` environment variable (e.g. after further tuning) to update predictions.

Example:

```bash
python services/scripts/fit_duration_model.py \
  --csv runtimes_per_repo.csv \
  --out duration_model.json \
  --version duration-v1

# Ensure to compact the json for DURATION_MODEL_JSON
export DURATION_MODEL_JSON="$(jq -c . duration_model.json)"
export GITHUB_TOKEN="..."
```

## Database schema

### Core tables

* **repositories** - unique repositories by canonical URL
* **analysis_jobs** - job queue and status tracking
  * Removed legacy in-DB artifact blob; see migrations below
* **drip_list_items** - final Drip List recommendation with a `split_percentage` per `package_url` (resolved repo URL of external dependency)
  * ⚠️ The scored dependencies stored in this table are limited to GitHub-hosted projects (see [above](#get-latest-results))
* **analysis_metadata** - job statistics and metrics (includes `graph_size_bytes`)
* **analysis_artifacts** - metadata pointers for S3-stored artifacts (per job, unique on `(job_id, artifact_type)`)
* **package_url_cache** - cached external dependency → canonical repository URL mappings

Notes on URL columns:
* `package_url_cache.resolved_url` and `drip_list_items.package_url` store the "https://"-prefixed, originally-cased URL that is returned by [Gardener's URL resolver](../gardener/package_metadata/url_resolver.py) for analyzed projects' external dependencies
* `drip_list_items.repository_url` and `repositories.canonical_url` store lower-cased URLs without a "https://" prefix

### Migrations

```bash
# Create new migration
cd services
alembic revision -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Troubleshooting
* **401 on submit**: check for expired token (default `TOKEN_EXPIRY_SECONDS`: >300 seconds), HMAC_SHARED_SECRET mismatch between token and API, or `X-Repo-Url` header mismatch with token payload
* **502 / trusted hosts**: ensure `--proxy-headers` and `ALLOWED_HOSTS` are correct
* **Cloning issues or jobs stuck in PENDING**: confirm worker has `git` and repo access (for private repos), check worker logs for errors, verify Redis connectivity
* **Job failures**: check repo accessibility, review worker memory limits, inspect DB:
  ```sql
  SELECT id, status, error_message
  FROM analysis_jobs
  WHERE status = 'FAILED';
  ```
* **Logs**:

  ```bash
  docker-compose logs -f api
  docker-compose logs -f worker
  ```

## API client examples

### Typescript

To submit an authenticated request for analysis:
```typescript
// gardenerAuth.ts

import crypto from "crypto";

  // Sort keys for stable JSON like Python's json.dumps(sort_keys=True)
  function stableStringify(obj: any): string {
    if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
    if (Array.isArray(obj)) return `[${obj.map(stableStringify).join(",")}]`;
    return `{${Object.keys(obj).sort().map(k => `${JSON.stringify(k)}:
  ${stableStringify(obj[k])}`).join(",")}}`;
  }

  export function makeGardenerToken(repoUrl: string, secret: string,
  expirySeconds = 300): string {
    const now = Math.floor(Date.now() / 1000);
    const payload = { url: repoUrl, exp: now + expirySeconds };
    const msg = stableStringify(payload);
    const sig = crypto.createHmac("sha256", Buffer.from(secret,
  "utf8")).update(msg).digest("base64");
    const tokenData = { payload, signature: sig };
    return Buffer.from(JSON.stringify(tokenData)).toString("base64");
  }
```

```typescript
// gardenerEnqueue.ts

import { makeGardenerToken } from "path/to/gardenerAuth";

  export async function post(req, res) {
    const { repoUrl } = await req.json();
    if (!repoUrl) return res.status(400).json({ error: "repoUrl required" });

    const secret = process.env.HMAC_SHARED_SECRET!;
    const apiBase = process.env.GARDENER_API_BASE ?? "http://localhost:8000";
    const token = makeGardenerToken(repoUrl, secret, 300); // 5 minutes

    const r = await fetch(`${apiBase}/api/v1/analyses/run`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "X-Repo-Url": repoUrl,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ repo_url: repoUrl })
    });

    const body = await r.json();
    return res.status(r.status).json(body);
  }
```

To poll job status:
```typescript
async function pollJob(jobId: string, { interval = 3000, max = 60 } = {}) {
  for (let i = 0; i < max; i++) {
    const r = await fetch(`${GARDENER_API_BASE}/api/v1/analyses/${jobId}`);
    const s = await r.json();
    if (s.status === "COMPLETED" || s.status === "FAILED") return s;
    await new Promise(res => setTimeout(res, interval));
  }
  throw new Error("Timed out waiting for analysis");
}
```

To fetch latest results by repository URL:
```typescript
async function getLatestResults(repoUrl: string) {
  const r = await fetch(`${GARDENER_API_BASE}/api/v1/repositories/results/latest?repository_url=${repoUrl}`);
  const s = await r.json();
  return s;
}
