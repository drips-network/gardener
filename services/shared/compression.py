"""
JSON compression utilities
"""

import gzip
import json


def to_gzip_bytes(obj):
    """
    Dump to compact JSON and gzip to bytes

    Args:
        obj: JSON-serializable object

    Returns:
        bytes: Gzipped JSON
    """
    json_str = json.dumps(obj, separators=(",", ":"))
    return gzip.compress(json_str.encode("utf-8"))
