#!/usr/bin/env python3
"""
Script to generate a large monorepo structure with 50+ manifest files
"""

import json
import os
import random

# Common dependencies with versions
COMMON_DEPS = {
    "lodash": ["4.17.21", "4.17.20", "4.17.15", "3.10.1"],
    "react": ["18.2.0", "17.0.2", "16.14.0"],
    "express": ["4.18.2", "4.18.0", "4.17.1"],
    "axios": ["1.4.0", "0.27.2", "0.26.0"],
    "moment": ["2.29.4", "2.29.0", "2.28.0"],
    "uuid": ["9.0.0", "8.3.2", "7.0.3"],
    "jest": ["29.5.0", "28.1.0", "27.5.0"],
    "typescript": ["5.0.0", "4.9.0", "4.7.0"],
    "webpack": ["5.88.0", "5.75.0", "5.70.0"],
    "babel": ["7.22.0", "7.20.0", "7.18.0"],
}


def create_package_json(name, deps_count=5, include_workspace_deps=False, workspace_deps=[]):
    """Generate a package.json with random dependencies"""
    deps = {}

    # Add some random external dependencies
    selected_deps = random.sample(list(COMMON_DEPS.keys()), min(deps_count, len(COMMON_DEPS)))
    for dep in selected_deps:
        version = random.choice(COMMON_DEPS[dep])
        deps[dep] = f"^{version}"

    # Add workspace dependencies if specified
    if include_workspace_deps and workspace_deps:
        for ws_dep in random.sample(workspace_deps, min(2, len(workspace_deps))):
            deps[ws_dep] = "workspace:*"

    return {"name": name, "version": "1.0.0", "private": True, "dependencies": deps}


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Create root package.json
    root_pkg = {
        "name": "large-monorepo",
        "version": "1.0.0",
        "private": True,
        "workspaces": ["teams/*/*", "shared/*", "tools/*"],
    }
    with open(os.path.join(base_dir, "package.json"), "w") as f:
        json.dump(root_pkg, f, indent=2)

    manifest_count = 0
    all_internal_packages = []

    # Platform team services (10)
    platform_services = [
        "auth-service",
        "user-service",
        "billing-service",
        "payment-service",
        "notification-service",
        "email-service",
        "sms-service",
        "audit-service",
        "permission-service",
        "session-service",
    ]

    for service in platform_services:
        service_dir = os.path.join(base_dir, "teams", "platform", service)
        os.makedirs(service_dir, exist_ok=True)

        pkg_name = f"@platform/{service}"
        all_internal_packages.append(pkg_name)
        pkg = create_package_json(pkg_name, deps_count=7)

        with open(os.path.join(service_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    # Frontend team apps (15)
    frontend_apps = [
        "customer-portal",
        "admin-dashboard",
        "mobile-app",
        "partner-portal",
        "developer-portal",
        "support-center",
        "help-docs",
        "marketing-site",
        "blog-platform",
        "landing-pages",
        "checkout-flow",
        "onboarding-app",
        "analytics-dashboard",
        "reporting-tool",
        "config-manager",
    ]

    for app in frontend_apps:
        app_dir = os.path.join(base_dir, "teams", "frontend", app)
        os.makedirs(app_dir, exist_ok=True)

        pkg_name = f"@frontend/{app}"
        all_internal_packages.append(pkg_name)
        # Frontend apps often depend on platform services
        pkg = create_package_json(
            pkg_name,
            deps_count=8,
            include_workspace_deps=True,
            workspace_deps=[f"@platform/{s}" for s in platform_services[:3]],
        )

        with open(os.path.join(app_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    # Data team services (10)
    data_services = [
        "etl-pipeline",
        "analytics-api",
        "data-warehouse",
        "ml-platform",
        "recommendation-engine",
        "search-service",
        "reporting-engine",
        "data-sync-service",
        "batch-processor",
        "stream-processor",
    ]

    for service in data_services:
        service_dir = os.path.join(base_dir, "teams", "data", service)
        os.makedirs(service_dir, exist_ok=True)

        # Mix of JS and Python services
        if random.choice([True, False]):
            # JavaScript service
            pkg_name = f"@data/{service}"
            all_internal_packages.append(pkg_name)
            pkg = create_package_json(pkg_name, deps_count=6)

            with open(os.path.join(service_dir, "package.json"), "w") as f:
                json.dump(pkg, f, indent=2)
        else:
            # Python service
            deps = random.sample(
                [
                    "pandas==1.5.0",
                    "numpy==1.23.0",
                    "scikit-learn==1.1.0",
                    "tensorflow==2.10.0",
                    "pytorch==1.12.0",
                    "sqlalchemy==1.4.40",
                    "airflow==2.5.0",
                    "dask==2022.10.0",
                    "pyspark==3.3.0",
                ],
                5,
            )

            with open(os.path.join(service_dir, "requirements.txt"), "w") as f:
                f.write("\n".join(deps))

        manifest_count += 1

    # Infrastructure tools (8)
    infra_tools = [
        "deployment-tool",
        "monitoring",
        "ci-runner",
        "secret-manager",
        "load-balancer",
        "service-mesh",
        "api-gateway",
        "log-aggregator",
    ]

    for tool in infra_tools:
        tool_dir = os.path.join(base_dir, "teams", "infrastructure", tool)
        os.makedirs(tool_dir, exist_ok=True)

        pkg_name = f"@infra/{tool}"
        all_internal_packages.append(pkg_name)
        pkg = create_package_json(pkg_name, deps_count=5)

        with open(os.path.join(tool_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    # Shared libraries (10)
    shared_libs = [
        "ui-components",
        "api-client",
        "data-models",
        "auth-utils",
        "validation",
        "error-handling",
        "logging",
        "metrics",
        "feature-flags",
        "config-loader",
    ]

    for lib in shared_libs:
        lib_dir = os.path.join(base_dir, "shared", lib)
        os.makedirs(lib_dir, exist_ok=True)

        pkg_name = f"@shared/{lib}"
        all_internal_packages.append(pkg_name)
        pkg = create_package_json(pkg_name, deps_count=4)

        with open(os.path.join(lib_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    # Build tools (5)
    build_tools = ["linter-config", "build-scripts", "test-utils", "deploy-scripts", "dev-server"]

    for tool in build_tools:
        tool_dir = os.path.join(base_dir, "tools", tool)
        os.makedirs(tool_dir, exist_ok=True)

        pkg_name = f"@tools/{tool}"
        pkg = create_package_json(pkg_name, deps_count=3)

        with open(os.path.join(tool_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    # Create some deeply nested packages
    deep_paths = [
        "teams/platform/auth-service/plugins/oauth-provider",
        "teams/frontend/customer-portal/src/components/shared",
        "teams/data/analytics-api/workers/aggregation/daily",
    ]

    for path in deep_paths:
        deep_dir = os.path.join(base_dir, path)
        os.makedirs(deep_dir, exist_ok=True)

        pkg_name = f"@nested/{os.path.basename(path)}"
        pkg = create_package_json(pkg_name, deps_count=3)

        with open(os.path.join(deep_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)
        manifest_count += 1

    print(f"Generated large monorepo with {manifest_count} manifest files")
    print(f"Total internal packages: {len(all_internal_packages)}")


if __name__ == "__main__":
    main()
