# Large Monorepo Test Fixture

This fixture simulates a large enterprise monorepo with 50+ manifest files across multiple teams and projects.

## Structure

```
.
├── package.json                    # Root workspace config
├── teams/
│   ├── platform/                   # Platform team (10 services)
│   │   ├── auth-service/
│   │   ├── user-service/
│   │   ├── billing-service/
│   │   └── ...
│   ├── frontend/                   # Frontend team (15 apps)
│   │   ├── customer-portal/
│   │   ├── admin-dashboard/
│   │   ├── mobile-app/
│   │   └── ...
│   ├── data/                       # Data team (10 services)
│   │   ├── etl-pipeline/
│   │   ├── analytics-api/
│   │   └── ...
│   └── infrastructure/             # Infra team (8 tools)
│       ├── deployment-tool/
│       ├── monitoring/
│       └── ...
├── shared/                         # Shared libraries (10 packages)
│   ├── ui-components/
│   ├── api-client/
│   ├── data-models/
│   └── ...
└── tools/                          # Build tools (5 packages)
    ├── linter-config/
    ├── build-scripts/
    └── ...
```

## Test Scenarios

1. **Scale Testing**: 50+ manifest files to test performance
2. **Deep Nesting**: Up to 5 levels of directory nesting
3. **Diverse Dependencies**: Mix of internal workspace deps and external
4. **Version Sprawl**: Same package with many different versions across teams