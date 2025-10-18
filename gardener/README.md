# Core

Type‑safe, deterministic static analysis that builds a multi-language dependency graph and ranks external dependencies by graph centrality scores.

## Table of contents
- [Core](#-core)
  - [Table of contents](#table-of-contents)
  - [Quick start](#quick-start)
  - [Analysis pipeline](#analysis-pipeline)
  - [Architecture](#architecture)
  - [Language support](#language-support)
    - [Python](#python)
    - [JavaScript, TypeScript](#javascript-typescript)
    - [Go](#go)
    - [Rust](#rust)
    - [Solidity](#solidity)
    - [Adding a language](#adding-a-language)
  - [Configuration](#configuration)
  - [Alias \& framework resolution](#alias--framework-resolution)
    - [Resolution order](#resolution-order)
    - [Patterns and targets](#patterns-and-targets)
    - [File resolution](#file-resolution)
    - [Examples handled](#examples-handled)

## Quick start

See [README: Quick Start](../README.md#quick-start) for installation and basic usage.

## Analysis pipeline

1. **Repository scanning** with secure file operations
   - Identifies source files and manifests
   - Respects `.gitignore` patterns
   - Detects language from file extensions
   - Parses `.gitmodules`: if a repo's dependency is vendored via git submodule, Gardener prioritizes the submodule's canonical URL from `.gitmodules`.
1. **Manifest processing** (package.json, requirements.txt / pyproject, Cargo.toml, go.mod, foundry.toml, remappings.txt, Hardhat configs)
   - Extracts declared dependencies
   - Maps distribution names to import names (e.g., `python-telegram-bot` → `telegram`)
   - Resolves version conflicts
   - Associates submodules with packages
2. **External repository URL resolution**
   - Queries package registries (npm, PyPI, crates.io)
   - Prioritizes `.gitmodules` URLs
   - Normalizes GitHub/GitLab URLs
   - Aggregates packages by repository
3. **Import extraction** — tree-sitter language handlers parse source files to extract:
   - External package imports
   - Specific component imports
   - Local file-to-file dependencies
   - Parsers are obtained via `gardener/common/tsl.py` which supports `tree_sitter_language_pack` or `tree_sitter_languages`
4. **Graph construction** — a directed graph with:
   - **Nodes**: Files, packages, and package components
   - **Edges**: Import relationships with typed connections (to adjust scaling factors per edge type, see [Configuration](#configuration) below))
     - `imports_package`: File imports external package
     - `uses_component`: File uses specific package component
     - `contains_component`: Package contains component
     - `imports_local`: File imports another local file
5. **Centrality analysis**
   - Calculates importance scores via PageRank/Katz (see [Configuration](#configuration) below)
   - Aggregates scores to the level of external dependencies' repo URLs
   - Filters out self-packages
   - Normalizes the final set to percentages summing to 100% (as needed for the [Drip Lists](https://docs.drips.network/support-your-dependencies/overview/) application)
6. **Graph serialization and reporting**
   - [README: CLI](../README.md#cli-for-local-analysis) for output types
   - Optionally, a HTML file with an interactive graph visualization can be produced (if `ipysigma` is installed (`.[viz]`)).  Here is an example, from Gardener's analysis of [github.com/keras-team/keras/](https://github.com/keras-team/keras/)):

![Keras import graph visualization](visualization/visualization-demo.gif)

## Architecture

```text
gardener/
├── analysis/                    # Core analysis orchestration
│   ├── main.py                  # Analysis entry point and high-level orchestrator
│   ├── tree.py                  # RepositoryAnalyzer orchestrator (delegates to helpers)
│   ├── scanner.py               # Secure repo scan, .gitignore, foundry src, .gitmodules
│   ├── manifests.py             # Manifest processing, dedup, conflicts, import-name attach
│   ├── js_ts_aliases.py         # tsconfig/jsconfig parsing and alias resolver creation
│   ├── imports.py               # LocalImportResolver and import extraction loop
│   ├── solidity_meta.py         # Solidity remappings and submodule association
│   ├── graph.py                 # Dependency graph construction
│   └── centrality.py            # Centrality analysis (PageRank, Katz)
├── treewalk/                    # Language-specific parsers
│   ├── python.py
│   ├── javascript.py
│   ├── typescript.py
│   ├── go.py
│   ├── rust.py
│   └── solidity.py
├── package_metadata/
│   ├── url_resolver.py          # Repository URL resolution for external dependencies
│   └── name_resolvers/          # Distribution name → import name mapping
├── common/                      # Shared utilities
│   ├── alias_config.py          # Unified alias resolution
│   ├── framework_config.py      # Framework-specific aliases
│   ├── defaults.py              # Tunable analysis defaults
│   ├── input_validation.py      # CLI and API input validation
│   ├── file_helpers.py          # Shared file IO helpers
│   ├── secure_file_ops.py       # Secure I/O and path traversal protection
│   ├── subprocess.py            # Sandboxed command execution
│   ├── utils.py                 # Logging and helpers
│   ├── tsl.py                   # Tree-sitter wrapper (selects language backend)
│   └── language_detection.py    # Filename → language detection
├── persistence/                 # Storage abstraction layer
└── visualization/               # Graph visualization
```

## Language support

### Python
- Import and from-import statements
- Relative imports (`from . import`, `from ..package`)
- Distribution vs import name resolution (e.g., `scikit-learn` → `sklearn`)
- Manifest parsing: `requirements.txt`, `pyproject.toml`, `Pipfile`, `environment.yml`

### JavaScript, TypeScript
- ES modules and CommonJS
- Path aliases from `tsconfig.json`/`jsconfig.json`
- Framework aliases (e.g., SvelteKit's `$lib/`)
- Dynamic imports and require calls
- Manifest parsing: `package.json`

### Go
- Standard library and module imports
- Local package resolution
- Manifest parsing: `go.mod`

### Rust
- Crate dependencies with components
- Use declarations (e.g. `crate::`, `super::`, `self::`)
- Manifest parsing: `Cargo.toml`

### Solidity
- Import directives with remappings
- `remappings.txt` support
- Hardhat configuration parsing
- Git submodule integration

### Adding a language

To add support for a new language, implement the `LanguageHandler` interface:

```python
from gardener.treewalk.base import LanguageHandler, TreeVisitor

class NewLanguageHandler(LanguageHandler):
    def get_manifest_files(self):
        """Return list of manifest file patterns"""
        return ["manifest.ext"]

    def get_file_extensions(self):
        """Return list of source file extensions"""
        return [".ext"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        """Extract declared dependencies from manifest"""
        pass

    def extract_imports(self, tree_node, rel_path, file_components_dict,
                       local_resolver_func, logger=None):
        """Extract imports from parsed source file"""
        pass
```

## Configuration

Core defaults are specified in [`gardener/common/defaults.py`](common/defaults.py). Highlights:
* **Centrality**: `CENTRALITY_METRIC` (`pagerank` or `katz`), `alpha` parameter
* **Edge weights**: `EDGE_W_*` for rescaling edge weights per edge type
* **Resource limits**: parse timeout, max imports per file, path length, etc.
* **Visualization colors and node sizing**

These can be overriden at runtime via the CLI `-c` JSON, e.g.:

```bash
python -m gardener.main_cli <repo> \
  --config '{"CENTRALITY_METRIC":"katz","EDGE_W_IMPORTS_PACKAGE":0.6}'
```

## Alias & framework resolution

Gardener has an alias configuration system that handles commonly used JS/TS import aliases. The `LocalImportResolver` consults the unified resolver for both path and framework aliases and prefers its extension set when resolving relative imports, falling back to defaults only when no resolver is present. Gardener resolves JS/TS and framework‑specific aliases before deciding whether an import is local or external

See:
* Core config datatypes in [`gardener/common/alias_config.py`](common/alias_config.py)
* Framework presets in [`gardener/common/framework_config.py`](common/framework_config.py)

### Resolution order

Aliases are resolved in the following priority order:

1. **Custom rules** (pattern → target, sorted in descending order by their `priority` argument)
2. **TS/JS path aliases** (`baseUrl`, `paths` from tsconfig/jsconfig)
3. **Framework-specific aliases**
   - SvelteKit: `$lib/` → `src/lib/` (+ `.svelte`)
   - Example configs for Next.js (`@/ → src/`) and Vue (`~/ → src/` + `.vue`)
4. **Relative imports** (./  ../)
5. **External packages** (node_modules)

### Patterns and targets

- Wildcards `*` are supported in both pattern and target
- Multiple targets are tried in order

### File resolution

- Exact path
- Try extensions: `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`, `.json`
- Framework extras (e.g., `.svelte`, `.vue`)
- `index.{ext}` for directory imports

### Examples handled

```typescript
import Button from '@components/Button';
// Resolves to: ./src/components/Button.tsx

import { helper } from '@utils/helpers';
// Resolves to: ./src/utils/helpers.ts

import api from '@api';
// Resolves to: ./src/services/api/index.ts

import { Types } from '@shared/types';
// Resolves to: ./shared/types.ts
```

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "baseUrl": "./src",
    "paths": {
      "@components/*": ["components/*"],
      "@utils/*": ["utils/*"],
      "@api": ["services/api/index.ts"],
      "@shared/*": ["../shared/*"]
    }
  }
}
```
