#!/usr/bin/env python3
"""
Generate an HMAC auth token for the Gardener API

Usage:
  - With env vars:
      HMAC_SHARED_SECRET=... python services/scripts/gen_token.py --url https://github.com/owner/repo
  - With CLI args only:
      python services/scripts/gen_token.py --url github.com/owner/repo --secret <32+ chars>

Options:
  --url / -u            Repository URL used in the token payload
  --secret / -s         Shared secret (falls back to env HMAC_SHARED_SECRET)
  --expiry / -e         Expiry seconds from now (default: 300)
  --print-curl          Print a ready-to-run curl for /analyses/run
  --print-headers       Print Authorization and X-Repo-Url headers
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import time


def make_token(url, secret, expiry_seconds):
    now = int(time.time())
    payload = {"url": url, "exp": now + expiry_seconds}
    msg = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = base64.b64encode(hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()).decode()
    token_data = {"payload": payload, "signature": sig}
    return base64.b64encode(json.dumps(token_data).encode()).decode()


def main():
    p = argparse.ArgumentParser(description="Generate Gardener HMAC token")
    p.add_argument("--url", "-u", required=True, help="Repository URL used in the signed payload")
    p.add_argument(
        "--secret",
        "-s",
        default=os.environ.get("HMAC_SHARED_SECRET", ""),
        help="Shared secret (or set HMAC_SHARED_SECRET)",
    )
    p.add_argument("--expiry", "-e", type=int, default=300, help="Expiry in seconds (default: 300)")
    p.add_argument("--print-curl", action="store_true", help="Print a curl example for /analyses/run")
    p.add_argument("--print-headers", action="store_true", help="Print Authorization and X-Repo-Url headers")
    args = p.parse_args()

    if not args.secret or len(args.secret) < 32:
        raise SystemExit("HMAC secret missing or too short (>=32 chars). Set --secret or HMAC_SHARED_SECRET")

    token = make_token(args.url, args.secret, args.expiry)
    print(token)

    if args.print_headers:
        print("\n# Headers:")
        print(f"Authorization: Bearer {token}")
        print(f"X-Repo-Url: {args.url}")

    if args.print_curl:
        print("\n# curl:")
        print('curl -X POST "http://localhost:8000/api/v1/analyses/run" \\')
        print(f'  -H "Authorization: Bearer {token}" \\')
        print(f'  -H "X-Repo-Url: {args.url}" \\')
        print('  -H "Content-Type: application/json" \\')
        body = json.dumps({"repo_url": args.url})
        print(f"  -d '{body}'")


if __name__ == "__main__":
    main()
