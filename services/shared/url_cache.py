"""
URL cache service utilities
"""

from sqlalchemy import tuple_

from services.shared.models import PackageUrlCache


def _cache_key(ecosystem, package_name):
    """
    Build cache key string 'ecosystem:package_name'
    """
    return f"{ecosystem}:{package_name}"


class UrlCacheService:
    """
    Service for preloading and upserting package URL cache entries
    """

    def preload(self, db, external_packages):
        """
        Return dict {'<ecosystem>:<package_name>': resolved_url} for existing cache hits

        Args:
            db (Session): SQLAlchemy session
            external_packages (dict): {'pkg_name': {'ecosystem': 'python', ...}, ...}

        Returns:
            dict: Mapping cache key to resolved URL
        """
        if not external_packages:
            return {}

        package_keys = []
        for name, data in external_packages.items():
            package_keys.append((name, data.get("ecosystem", "unknown")))

        if not package_keys:
            return {}

        cached = (
            db.query(PackageUrlCache)
            .filter(tuple_(PackageUrlCache.package_name, PackageUrlCache.ecosystem).in_(package_keys))
            .all()
        )

        result = {}
        for item in cached:
            result[_cache_key(item.ecosystem, item.package_name)] = item.resolved_url
        return result

    def upsert(self, db, package_name, ecosystem, repository_url, force_refresh=False):
        """
        Insert or update a cache entry; tolerate concurrent updates

        Args:
            db (Session): SQLAlchemy session
            package_name (str): Package name
            ecosystem (str): Ecosystem identifier (e.g., 'python')
            repository_url (str): Resolved repository URL
            force_refresh (bool): Force update even if same URL
        """
        try:
            existing = db.query(PackageUrlCache).filter_by(package_name=package_name, ecosystem=ecosystem).first()

            if not existing:
                entry = PackageUrlCache(package_name=package_name, ecosystem=ecosystem, resolved_url=repository_url)
                db.add(entry)
            elif force_refresh or existing.resolved_url != repository_url:
                existing.resolved_url = repository_url
                from datetime import datetime, timezone

                existing.resolved_at = datetime.now(timezone.utc)
        except Exception:
            # Do not let cache failures bubble up; storage will continue
            pass
