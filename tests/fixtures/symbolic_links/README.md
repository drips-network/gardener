# Symbolic Links Test Fixture

This fixture tests handling of symbolic links in the repository structure.

## Structure

```
.
├── packages/
│   ├── core/
│   │   └── package.json
│   └── shared -> ../shared_modules/shared  # Symlink
├── shared_modules/
│   └── shared/
│       └── package.json
└── apps/
    ├── web/
    │   └── package.json
    └── common -> ../../shared_modules/shared  # Symlink to same target
```

## Test Scenarios

1. **Symlinked Directories**: shared and common both point to same directory
2. **Duplicate Detection**: Should handle the same manifest found via different paths
3. **Circular Symlinks**: Test resilience against circular symbolic links