# Circular Dependencies Test Fixture

This fixture tests handling of circular dependencies between packages in a monorepo.

## Structure

```
.
├── package-a/
│   └── package.json    # Depends on package-b
├── package-b/
│   └── package.json    # Depends on package-c
└── package-c/
    └── package.json    # Depends on package-a (circular!)
```

## Test Scenarios

1. **Direct Circular Dependency**: A → B → C → A
2. **Workspace Protocol**: Uses workspace:* for internal dependencies
3. **External Dependencies**: Each package also has external dependencies