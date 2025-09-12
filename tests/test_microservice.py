#!/usr/bin/env python3
"""
Microservice smoke tests and examples
"""
import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import time

import requests

# Setup simple logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Configuration
API_URL = os.environ.get("API_URL") or "http://localhost:8000"
raw = os.environ.get("HMAC_SHARED_SECRET")
SHARED_SECRET = (raw or "").encode("utf-8")
if not SHARED_SECRET:
    raise ValueError("Set HMAC_SHARED_SECRET for tests")


def generate_token(url):
    """Generate HMAC token for authentication"""
    timestamp = int(time.time())
    expiry_seconds = 300

    payload = {"url": url, "exp": timestamp + expiry_seconds}

    message = json.dumps(payload, sort_keys=True)
    signature = hmac.new(SHARED_SECRET, message.encode("utf-8"), hashlib.sha256).digest()

    token_data = {"payload": payload, "signature": base64.b64encode(signature).decode()}

    token = base64.b64encode(json.dumps(token_data).encode()).decode()
    return token


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Test Gardener microservice analysis")
    parser.add_argument("repo_url", help="Git repository URL to analyze")
    parser.add_argument(
        "--drip-list-max-length",
        type=int,
        default=200,
        help="Maximum number of dependencies in drip list (default: 200, max: 200)",
    )
    parser.add_argument(
        "--force-url-refresh", action="store_true", help="Force fresh URL resolution, bypassing the cache"
    )
    parser.add_argument(
        "--use-url-results-endpoint", action="store_true", help="Fetch results via the URL-based endpoint"
    )

    args = parser.parse_args()

    # Validate drip_list_max_length
    if args.drip_list_max_length < 1 or args.drip_list_max_length > 200:
        logger.error(f"Error: drip-list-max-length must be between 1 and 200, got {args.drip_list_max_length}")
        sys.exit(1)

    repo_url = args.repo_url
    drip_list_max_length = args.drip_list_max_length
    force_url_refresh = args.force_url_refresh

    logger.info(f"Testing analysis of {repo_url}")
    logger.info(f"Drip List max length: {drip_list_max_length}")
    logger.info(f"Force URL refresh: {force_url_refresh}")

    # 1. Submit job
    logger.info("\n1. Submitting analysis job...")

    token = generate_token(repo_url)
    headers = {"Authorization": f"Bearer {token}", "X-Repo-Url": repo_url}

    response = requests.post(
        f"{API_URL}/api/v1/analyses/run",
        json={
            "repo_url": repo_url,
            "drip_list_max_length": drip_list_max_length,
            "force_url_refresh": force_url_refresh,
        },
        headers=headers,
    )

    if response.status_code not in [200, 202]:
        logger.error(f"   Failed to submit job: {response.status_code}")
        logger.error(f"   Response: {response.text}")
        return

    job_data = response.json()
    job_id = job_data["job_id"]
    logger.info(f"   Job submitted successfully")
    logger.info(f"   Job ID: {job_id}")

    # 2. Poll for completion
    logger.info("\n2. Waiting for analysis to complete...")

    start_time = time.time()
    # Worker has 60 min timeout (MAX_ANALYSIS_DURATION=3600s) + 5 min buffer for cleanup
    max_wait = 3900  # 65 minutes total

    while True:
        # Get job status
        response = requests.get(f"{API_URL}/api/v1/analyses/{job_id}")

        if response.status_code != 200:
            logger.error(f"   Failed to get job status: {response.status_code}")
            return

        job_status = response.json()
        status = job_status["status"]  # Keep as uppercase from API

        if status == "COMPLETED":
            logger.info(f"   Status: {status} ✓")
            break
        elif status == "FAILED":
            logger.error(f"   Status: {status} ✗")
            logger.error(f"   Error: {job_status.get('error_message', 'Unknown error')}")
            return
        else:
            logger.info(f"   Status: {status} (elapsed: {int(time.time() - start_time)}s)")

        if time.time() - start_time > max_wait:
            logger.error("   Timeout waiting for job completion")
            return

        time.sleep(5)

    # 3. Get results
    logger.info("\n3. Getting analysis results...")

    if args.use_url_results_endpoint:
        # Fetch via URL endpoint
        response_url = requests.get(
            f"{API_URL}/api/v1/repositories/results/latest", params={"repository_url": repo_url}
        )
        if response_url.status_code != 200:
            logger.error(f"   URL results failed: {response_url.status_code} {response_url.text}")
            return
        results_url = response_url.json()

        # Also fetch via repository_id for side-by-side comparison
        repository_id = job_status.get("repository_id")
        if not repository_id:
            logger.error("   No repository ID in job status; cannot compare ID vs URL endpoints")
            results = results_url
        else:
            response_id = requests.get(f"{API_URL}/api/v1/repositories/{repository_id}/results/latest")
            if response_id.status_code != 200:
                logger.warning(f"   ID results failed: {response_id.status_code} {response_id.text}")
                results = results_url
            else:
                results_id = response_id.json()
                # Print side-by-side summary
                logger.info("   Results by URL vs by ID (side-by-side):")
                url_count = len(results_url.get("results", []))
                id_count = len(results_id.get("results", []))
                logger.info(f"     URL: commit {results_url.get('commit_sha')}  | items: {url_count}")
                logger.info(f"      ID: commit {results_id.get('commit_sha')}  | items: {id_count}")
                if results_url.get("commit_sha") == results_id.get("commit_sha") and url_count == id_count:
                    logger.info("     ✓ Endpoints match on commit and item count")
                else:
                    logger.warning("     ! Endpoints differ (investigate)")
                results = results_url
    else:
        # Use repository_id from job status (legacy path)
        repository_id = job_status.get("repository_id")
        if not repository_id:
            logger.error("   No repository ID in job status")
            return
        response = requests.get(f"{API_URL}/api/v1/repositories/{repository_id}/results/latest")
        if response.status_code != 200:
            logger.error(f"   Failed to get results: {response.status_code}")
            return
        results = response.json()

    logger.info("   Results retrieved successfully")
    logger.info(f"   - Analyzed repository at commit {results['commit_sha']}")
    if results.get("metadata"):
        logger.info(f"   - Total files: {results['metadata']['total_files']}")
        logger.info(f"   - Languages: {', '.join(results['metadata']['languages_detected'])}")
        if results["metadata"].get("analysis_duration_seconds"):
            logger.info(f"   - Analysis duration: {results['metadata']['analysis_duration_seconds']:.2f}s")

    # 4. Display recommended Drip List
    logger.info("\n4. Recommended Drip List:")

    drip_list = results.get("results", [])
    if not drip_list:
        logger.info("   No dependencies found!")
    else:
        logger.info(f"   Found {len(drip_list)} dependencies (max requested: {drip_list_max_length})")
        # Show all results (up to the requested limit)
        for i, item in enumerate(drip_list, 1):
            logger.info(f"   {i:2d}. {item['package_name']}: {float(item['split_percentage']):.2f}%")
            if item.get("package_url"):
                logger.info(f"       URL: {item['package_url']}")

    # 5. Check db directly
    logger.info("\n5. Verifying DB storage...")

    # Query the db using docker exec
    query = (
        f"SELECT package_name, package_url, split_percentage FROM drip_list_items "
        f"WHERE job_id = '{job_id}' ORDER BY split_percentage DESC LIMIT {drip_list_max_length};"
    )

    result = subprocess.run(
        ["docker", "exec", "gardener-postgres", "psql", "-U", "gardener", "-d", "gardener_db", "-t", "-c", query],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info("   DB query successful")
        logger.info("   DB contents:")
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.strip():
                logger.info(f"     {line.strip()}")
    else:
        logger.error(f"   DB query failed: {result.stderr}")

    logger.info("\nCOMPLETE")


if __name__ == "__main__":
    main()
