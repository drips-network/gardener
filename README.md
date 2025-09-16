# 🧤 Gardener

Gardener is a **static dependency analysis** tool that builds import graphs from source and analyzes them to produce **recommendations for distributing OSS funding across each project's external dependencies** via [Drip Lists](https://docs.drips.network/support-your-dependencies/overview/).

> *"If you really want to be a good gardener, you need to understand what is going on in your soil." — Jeff Lowenfels*

> *"Feed the soil, not your plants!" — Charles Dowding*

⚠️ **Status**: actively developed. Interfaces may evolve.

<br/>

## What Gardener does

- **Scans a project's package manifests and code** (Javascript/Typescript, Python, Go, Rust, Solidity) and **builds a dependency graph** representing the static import relationships of the project's local files, external dependencies, and their components
- **Computes and aggregates importance scores** (PageRank or Katz) over that graph
- **Resolves external dependencies' repository URLs** (npm, PyPI, crates.io, Go proxy, Git submodules, GitHub/GitLab/Bitbucket normalization)
- **Produces**:
  - Recommended **Drip Lists** with normalized percentages, aggregated per canonical external dependency repo URL
    - *NB: this feature currently only supports dependencies hosted on GitHub*
  - JSON exports with **complete node-link graphs**
  - Optional **interactive graph visualizations**
- Runs as a **CLI** (analyze any local path or remote Git URL) or as a **microservice** (FastAPI + Celery + Redis + PostgreSQL)

<br/>

## Documentation

For complete documentation including installation, API reference, and deployment guides, see:
- **[Core analysis modules and CLI](./gardener/README.md)** (`gardener/`)
- **[API, worker, database models](./services/README.md)** (`services/`)
- **[Tests](./tests/README.md)** (`tests/`)

<br/>

## Quick start

### CLI for local analysis

```bash
# Create a virtualenv and install dev+test extras
uv pip install -e '.[dev,test]'
uv pip install -e '.[viz]'  # optional dependency for visualization

# If using Solidity projects with Hardhat TS remappings, install the small Node helper once:
make js-helpers

# Analyze local repository
python -m gardener.main_cli /path/to/repo
````

**Options**:
* `-o, --output PREFIX` - Output file prefix (default: ownerName_repoName)
* `-v, --verbose` - Enable debug logging
* `-l, --languages LANGS` - Languages to focus the analysis on (comma-separated)
* `-c, --config JSON` - Configuration overrides
* `--visualize` - Generate interactive graph visualization (requires '[.viz]' extra)

**Outputs**:
* In-console results summary
* `output/<prefix>_dependency_analysis.json`
* `output/<prefix>_dependency_graph.html` (if '--visualize' is used and '.[viz]' is installed)

### Microservice

```bash
cp .env.example .env
# Set at minimum:
# POSTGRES_PASSWORD=...
# HMAC_SHARED_SECRET=<32+ characters>

docker-compose up --build
```

* Submit a job: `POST /api/v1/analyses/run` with  (requires auth and a `repo_url` in the send data, returns a `job_id` and `repository_id`)
  * Run `services/scripts/gen_token.py` to generate the Bearer token; see the [services docs](./services/README.md) for more details
* Check job status: `GET /api/v1/analyses/{job_id}`
* Fetch latest results:
  * By `repository_id`: `GET /api/v1/repositories/{repository_id}/results/latest` (by `repository_id`)
  * Or by GitHub URL: `GET /api/v1/repositories/results/latest?repository_url=github.com/owner/repo`

<br/>

## License

MIT — see [LICENSE](./LICENSE).
