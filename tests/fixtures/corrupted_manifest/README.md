# Corrupted Manifest Test Fixture

This fixture tests handling of corrupted or malformed manifest files.

## Test Cases

1. **Invalid JSON**: package.json with syntax errors
2. **Invalid TOML**: Cargo.toml with syntax errors  
3. **Missing Required Fields**: Manifests missing critical fields
4. **Mixed Valid/Invalid**: Some manifests are valid, others are corrupted