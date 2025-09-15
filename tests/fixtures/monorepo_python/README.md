# Python Monorepo Test Fixture

This fixture represents a complex Python monorepo with multiple levels of nesting and various dependency scenarios.

## Structure

```
.
├── requirements.txt              # Root dependencies
├── backend/
│   ├── requirements.txt          # Backend-specific deps
│   ├── api/
│   │   ├── requirements.txt      # API service deps
│   │   └── v2/
│   │       └── requirements.txt  # API v2 deps (4 levels deep)
│   └── workers/
│       └── requirements.txt      # Worker deps
├── frontend/
│   └── requirements.txt          # Frontend deps (Python-based)
├── shared/
│   ├── requirements.txt          # Shared libraries
│   └── utils/
│       └── requirements.txt      # Utility package deps
└── tools/
    └── requirements.txt          # Development tools
```

## Test Scenarios

1. **Version Conflicts**: Different versions of the same package in different requirements.txt files
2. **Deep Nesting**: API v2 requirements are 4 levels deep from root
3. **Shared Dependencies**: Some packages appear in multiple manifest files
4. **Different Package Sets**: Each component has its own unique dependencies