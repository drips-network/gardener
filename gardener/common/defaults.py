"""
Default parameter values used in data processing, analysis, and visualization stages
"""


class GraphAnalysisConfig:
    """
    Parameters for graph analysis and centrality metric calculations

    These parameters control the behavior of the dependency graph builder
    and the PageRank or Katz algorithm used to determine relative importance of
    different software components
    """

    # PageRank/Katz parameters
    CENTRALITY_METRIC = "pagerank"  # Either 'pagerank' or 'katz'
    PAGERANK_ALPHA = 0.85  # Damping parameter for PageRank
    KATZ_ALPHA = 0.15  # Alpha parameter for Katz

    # Edge weights (tunable via CLI overrides)
    EDGE_W_IMPORTS_PACKAGE = 0.5
    EDGE_W_IMPORTS_LOCAL = 0.7
    EDGE_W_CONTAINS_COMPONENT = 1.0
    EDGE_W_USES_COMPONENT = 1.0

    # Serialization behavior
    SERIALIZE_SORT_KEYS = True


class VisualizationConfig:
    """
    Defaults for graph visualization styling and rendering

    These parameters control the visual appearance of the generated
    dependency graph visualizations, including node sizes, colors,
    edge styles, and other visual attributes
    """

    # Maximum number of nodes to include in visualization
    # None means no limit is applied
    VISUALIZATION_FILTER_LIMIT = None

    # Color defaults
    COLOR_PACKAGE = "#81d5dd"  # Blue for packages
    COLOR_COMPONENT = "#c6b6e5"  # Purple for components
    COLOR_FILE = "#e2b9c6"  # Red for files
    COLOR_IDENTIFIER = "#ffddcc"  # Yellow for identifiers
    COLOR_DEFAULT = "#999999"  # Gray fallback

    # Label formatting
    MAX_NODE_LABEL_LENGTH = 25
    NODE_LABEL_SUFFIX_LENGTH = 22

    # Node size scaling
    NODE_SIZE_SCALING_FACTOR = 9000


class ResourceLimits:
    """
    Resource limits for robustness and edge case handling

    These are set to extremely large values by default, and should
    should be tuned empirically to your environment and analysis use cases
    """

    # Structural limits on inputs from analyzed repositories
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB max file size for parsing
    MAX_IMPORTS_PER_FILE = 1000000  # Maximum imports to track per file
    MAX_TREE_DEPTH = 50000  # Maximum AST tree depth

    # Timeouts
    PARSE_TIMEOUT = 300  # Seconds to timeout a single file parsing

    # Path and string limits (should not need retuning)
    MAX_PATH_LENGTH = 4096  # Maximum file path length
    MAX_URL_LENGTH = 2048  # Maximum URL length

    # Repository scan behavior
    # Reserved for future use (e.g., disabling symlink following in scans)
    FOLLOW_SYMLINKS = True


def apply_config_overrides(overrides, logger=None):
    """
    Apply configuration overrides from an external source

    Searches through all configuration classes to find matching parameters
    and applies type-safe value overrides with validation

    Args:
        overrides (dict): Dictionary mapping parameter names to override values
        logger (Logger): Optional logger for reporting applied overrides

    Example:
        apply_config_overrides({
            'MAX_TREE_DEPTH': 1000,
            'PAGERANK_ALPHA': 0.9
        })
    """
    if not overrides:
        return

    config_classes = {
        "GraphAnalysisConfig": GraphAnalysisConfig,
        "VisualizationConfig": VisualizationConfig,
        "ResourceLimits": ResourceLimits,
    }

    for key, value in overrides.items():
        applied = False
        for class_name, config_class in config_classes.items():
            if hasattr(config_class, key):
                try:
                    # Get the original value and its type for casting
                    old_value = getattr(config_class, key)
                    value_type = type(old_value)

                    # Cast the new value to the correct type
                    setattr(config_class, key, value_type(value))

                    if logger:
                        logger.debug(f"Config override: {class_name}.{key} = {value} (was {old_value})")
                    applied = True
                    break  # Move to the next key
                except (ValueError, TypeError) as e:
                    if logger:
                        logger.warning(f"Could not apply override for {key}={value}: {e}")
                    applied = True  # Mark as applied to avoid 'Unknown parameter' warning
                    break

        if not applied and logger:
            logger.warning(f"Config override ignored: Unknown parameter {key}")


class ConfigOverride:
    """
    Context manager to temporarily override configuration values

    Supports GraphAnalysisConfig, VisualizationConfig, and ResourceLimits. Ensures
    overrides are reverted when the context exits, preventing test bleed‑through.

    Args:
        overrides (dict): Mapping of attribute name to new value
        logger (Logger): Optional logger for debug messages
    """

    def __init__(self, overrides=None, logger=None):
        self.overrides = overrides or {}
        self.logger = logger
        self._originals = []  # list of (cls, key, old_value)

    def __enter__(self):
        if not self.overrides:
            return self
        config_classes = {
            "GraphAnalysisConfig": GraphAnalysisConfig,
            "VisualizationConfig": VisualizationConfig,
            "ResourceLimits": ResourceLimits,
        }
        for key, value in self.overrides.items():
            applied = False
            for class_name, cls in config_classes.items():
                if hasattr(cls, key):
                    old_value = getattr(cls, key)
                    try:
                        casted = type(old_value)(value)
                    except Exception:
                        casted = value
                    self._originals.append((cls, key, old_value))
                    setattr(cls, key, casted)
                    if self.logger:
                        self.logger.debug(f"ConfigOverride: {class_name}.{key} = {casted} (was {old_value})")
                    applied = True
                    break
            if not applied and self.logger:
                self.logger.warning(f"ConfigOverride ignored unknown parameter: {key}")
        return self

    def __exit__(self, exc_type, exc, tb):
        # Restore in reverse order
        for cls, key, old_value in reversed(self._originals):
            setattr(cls, key, old_value)
            if self.logger:
                cls_name = cls.__name__
                self.logger.debug(f"ConfigOverride: restored {cls_name}.{key} -> {old_value}")
        self._originals.clear()
        return False
