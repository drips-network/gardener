# Mixed Language Monorepo Test Fixture

This fixture represents a monorepo with JavaScript, Python, and Rust components.

## Structure

```
.
├── package.json                  # Root Node.js dependencies
├── backend/
│   ├── python-service/
│   │   └── requirements.txt      # Python microservice
│   └── rust-service/
│       └── Cargo.toml            # Rust microservice
├── frontend/
│   ├── package.json              # React frontend
│   └── mobile/
│       └── package.json          # React Native app
├── shared/
│   ├── js-utils/
│   │   └── package.json          # Shared JS utilities
│   └── py-utils/
│       └── requirements.txt      # Shared Python utilities
└── tools/
    ├── package.json              # JS-based tools
    └── requirements.txt          # Python-based tools
```

## Test Scenarios

1. **Cross-Language Dependencies**: Same library available in multiple ecosystems (e.g., protobuf)
2. **Language-Specific Conflicts**: Different versions of lodash in different package.json files
3. **Mixed Tooling**: Both JS and Python development tools
4. **Nested Language Boundaries**: Language changes at different directory levels