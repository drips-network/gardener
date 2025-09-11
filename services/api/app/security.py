"""
API security and HMAC auth middleware
"""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from fastapi import Header, HTTPException, status

from gardener.common.utils import get_logger
from services.shared.config import settings

logger = get_logger("api.security")


class HMACAuthenticator:
    def __init__(self, shared_secret, hash_name="sha256", expiry_seconds=300):
        # Store secret as string, convert to bytes when needed
        self.shared_secret = shared_secret
        try:
            self.hash_fn = getattr(hashlib, hash_name)
        except AttributeError:
            raise ValueError(f"Unsupported hash algorithm: {hash_name}")
        self.expiry_seconds = expiry_seconds

    def _canonicalize_url(self, url) -> str:
        """Normalize URL to avoid signature mismatches"""
        parsed = urlparse(url)
        # Lowercase host, remove trailing slash, normalize scheme
        canonical = f"{parsed.scheme or 'https'}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
        if parsed.query:
            canonical += f"?{parsed.query}"
        return canonical

    def verify_token(self, token, url) -> bool:
        try:
            # Decode the token (assuming base64 encoded JSON with payload and signature)
            token_data = json.loads(base64.b64decode(token))
            payload = token_data["payload"]
            provided_signature = token_data["signature"]

            # Check absolute expiry with small skew window (5 seconds)
            if "exp" in payload:
                now = int(time.time())
                if now > int(payload["exp"]) + 5:  # 5 second skew tolerance
                    return False

            # Compare canonical URL equivalence without mutating payload
            payload_url = payload.get("url", "")
            if self._canonicalize_url(payload_url) != self._canonicalize_url(url):
                return False

            # Create message to sign from the original payload
            message = json.dumps(payload, sort_keys=True)

            # Compute signature
            secret_bytes = self.shared_secret.encode("utf-8")
            computed_signature = hmac.new(secret_bytes, message.encode("utf-8"), self.hash_fn).digest()

            # Ensure both are bytes before comparison
            provided_signature_bytes = base64.b64decode(provided_signature)

            # Use constant-time comparison
            return hmac.compare_digest(computed_signature, provided_signature_bytes)
        except Exception:
            # Never leak specific error details
            return False


async def verify_auth_token(authorization=Header(default=None), x_repo_url=Header(alias="X-Repo-Url")):
    # Initialize authenticator with settings
    authenticator = HMACAuthenticator(
        shared_secret=settings.security.HMAC_SHARED_SECRET,
        hash_name=settings.security.HMAC_HASH_NAME,
        expiry_seconds=settings.security.TOKEN_EXPIRY_SECONDS,
    )

    # Keep Bearer prefix for compatibility
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    token = authorization[7:]  # Strip 'Bearer ' prefix

    if not authenticator.verify_token(token, x_repo_url):
        # Generic error only
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
