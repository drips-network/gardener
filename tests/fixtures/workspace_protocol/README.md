# Workspace Protocol Test Fixture

This fixture tests handling of npm/yarn/pnpm workspace protocols.

## Structure

```
.
├── package.json         # Root with workspaces config
├── packages/
│   ├── core/
│   │   └── package.json # workspace:*
│   ├── ui/
│   │   └── package.json # workspace:^
│   └── utils/
│       └── package.json # workspace:~
└── apps/
    ├── web/
    │   └── package.json # Uses packages
    └── mobile/
        └── package.json # Uses packages
```

## Test Scenarios

1. **Workspace Protocols**: Tests workspace:*, workspace:^, workspace:~
2. **Cross-Workspace Dependencies**: Apps depend on packages
3. **Mixed Dependencies**: Both workspace and external dependencies