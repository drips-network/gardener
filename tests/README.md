# 🧤 Tests

Test suite covering language handlers, graph building, URL resolution, microservice endpoints, and robustness edge cases.

<br/>

## Layers and markers

- **Unit** (`-m unit`) — focused handlers/utilities, no network
- **Fixture** (`-m fixture`) — curated micro‑repos with YAML graph specs
- **Integration** (`-m integration`) — cross‑component (multi‑language, conflicts)
- **System** (`-m system`) — API/Worker endpoints (requires service extras)
- **Security** (`-m security`) — malformed inputs, timeouts, limits, sandboxing
- **Slow** (`-m slow`) — scale scenarios

Markers are defined in [`pytest.ini`](../pytest.ini).

<br/>

## Running

Common profiles:

```bash
# Fast dev/CI profile
pytest -m "unit or integration and not slow and not system and not external" -q

# Include slow; $GARDENER_TEST_FILECOUNT scales large file-count tests
GARDENER_TEST_FILECOUNT=2000 pytest -m slow -q

# System/API tests (install service extras first)
uv pip install -e '.[service,test]'
pytest -m system -q
````

Or use the helper script:

```bash
python tests/run_tests.py --unit|--integration|--fixtures|--system|--all [-v] [--include-slow]
```

<br/>

## Determinism

* **No live network**: registry/HTML fetches are stubbed via `tests.support.fixtures.offline_mode`
* **Stable graph serialization**: nodes/edges are sorted
* Resource limits and timeouts are enforced to avoid flakiness.

<br/>

## Fixture docs

Each fixture has a README:

* [tests/fixtures/circular\_deps/README.md](./fixtures/circular_deps/README.md)
* [tests/fixtures/corrupted\_manifest/README.md](./fixtures/corrupted_manifest/README.md)
* [tests/fixtures/large\_monorepo/README.md](./fixtures/large_monorepo/README.md)
* [tests/fixtures/monorepo\_mixed/README.md](./fixtures/monorepo_mixed/README.md)
* [tests/fixtures/monorepo\_python/README.md](./fixtures/monorepo_python/README.md)
* [tests/fixtures/symbolic\_links/README.md](./fixtures/symbolic_links/README.md)
* [tests/fixtures/workspace\_protocol/README.md](./fixtures/workspace_protocol/README.md)
