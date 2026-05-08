"""
Main analysis module with persistence abstraction
"""

import os

import networkx as nx

from gardener.analysis.centrality import CentralityCalculator
from gardener.analysis.evidence import (
    build_machine_summary,
    build_repository_metadata,
    classify_dependency_fact,
    enrich_analysis_result,
)
from gardener.analysis.graph import DependencyGraphBuilder
from gardener.analysis.tree import RepositoryAnalyzer
from gardener.common.defaults import ConfigOverride, GraphAnalysisConfig as cfg, apply_config_overrides
from gardener.common.utils import Logger, get_repo
from gardener.package_metadata.url_resolution import ensure_repository_url_resolution, utc_now_isoformat
from gardener.package_metadata.url_resolver import resolve_package_url_receipts
from gardener.persistence.file import FilePersistence
from gardener.treewalk.go import GoLanguageHandler
from gardener.treewalk.javascript import JavaScriptLanguageHandler
from gardener.treewalk.python import PythonLanguageHandler
from gardener.treewalk.rust import RustLanguageHandler
from gardener.treewalk.solidity import SolidityLanguageHandler
from gardener.treewalk.typescript import TypeScriptLanguageHandler


class DependencyAnalyzer:
    """
    Analyzes a repository to extract dependency information

    This class is persistence-agnostic and returns pure data structures
    """

    def __init__(self, verbose=False, *, repository_metadata=None, invocation_metadata=None):
        """
        Args:
            verbose (bool): Enable verbose logging
            repository_metadata (dict | None): Repository provenance metadata
            invocation_metadata (dict | None): Invocation provenance metadata
        """
        self.verbose = verbose
        self.logger = Logger(verbose=verbose)
        self.repository_metadata = repository_metadata
        self.invocation_metadata = invocation_metadata

        # Initialize components that persist across analysis phases
        self.repo_analyzer = None
        self.graph_builder = DependencyGraphBuilder(self.logger)
        self.centrality_calculator = CentralityCalculator(self.logger)

    def _register_language_handlers(self):
        """
        Register language handlers on self.repo_analyzer
        """
        language_handlers = {
            "javascript": JavaScriptLanguageHandler(self.logger),
            "typescript": TypeScriptLanguageHandler(self.logger),
            "python": PythonLanguageHandler(self.logger),
            "go": GoLanguageHandler(self.logger),
            "rust": RustLanguageHandler(self.logger),
            "solidity": SolidityLanguageHandler(self.logger),
        }
        for language, handler in language_handlers.items():
            self.repo_analyzer.register_language_handler(language, handler)

    def _scan_and_process_manifests(self):
        """
        Scan repository and process manifests

        Returns:
            Dict of external packages
        """
        self.repo_analyzer.scan_repo()
        return self.repo_analyzer.process_manifest_files()

    def discover_packages(self, repo_path, specific_languages=None):
        """
        Discover external packages by scanning repository and processing manifest files

        Args:
            repo_path (str): Path to the repository to analyze
            specific_languages (list): Optional list of languages to analyze

        Returns:
            Dictionary of external packages found
        """
        self.repo_analyzer = RepositoryAnalyzer(repo_path, specific_languages, self.logger)
        self._register_language_handlers()
        return self._scan_and_process_manifests()

    def _build_dependency_graph(self):
        """
        Build and attach dependency graph using the repo_analyzer state

        Returns:
            networkx.DiGraph
        """
        self.logger.info("Building dependency graph")
        graph = self.graph_builder.build_dependency_graph(
            self.repo_analyzer.source_files,
            self.repo_analyzer.external_packages,
            self.repo_analyzer.file_imports,
            self.repo_analyzer.file_package_components,
            self.repo_analyzer.local_imports_map,
        )
        return graph

    def _calculate_importance_scores(self, graph):
        """
        Calculate importance scores for nodes if graph is non-empty

        Args:
            graph: NetworkX graph

        Returns:
            Dict[str, float] of node scores
        """
        self.logger.info("Calculating importance scores")
        if graph and graph.number_of_nodes() > 0:
            return self.graph_builder.calculate_importance()
        return {}

    def _collect_self_package_names(self):
        """
        Collect distribution and import names of root packages for self-filtering

        Returns:
            Set[str] of package names to exclude
        """
        root_package_distribution_names = self.repo_analyzer.root_package_names
        all_self_package_names = set(root_package_distribution_names)
        for root_dist_name in root_package_distribution_names:
            if root_dist_name in self.repo_analyzer.external_packages:
                import_names = self.repo_analyzer.external_packages[root_dist_name].get("import_names", [])
                all_self_package_names.update(import_names)
        return all_self_package_names

    def _normalize_top_dependencies(self, top_deps_tuples):
        """
        Convert top dependency tuples into enriched dicts with percentages, scores, URLs, and evidence metadata

        Args:
            top_deps_tuples: List of (package_name, score)

        Returns:
            List[dict] with dependency ranking and evidence metadata
        """
        top_deps = []
        total_score = sum(score for _, score in top_deps_tuples)
        for package_name, score in top_deps_tuples:
            percentage = (score / total_score * 100) if total_score > 0 else 0
            repository_url = ""
            ecosystem = "unknown"
            repository_url_resolution = None

            if package_name in self.repo_analyzer.external_packages:
                package_data = self.repo_analyzer.external_packages[package_name]
                repository_url = package_data.get("repository_url", "")
                ecosystem = package_data.get("ecosystem", "unknown")
                repository_url_resolution = package_data.get("repository_url_resolution")
                classification = classify_dependency_fact(
                    package_name,
                    ecosystem=ecosystem,
                    is_package_manager=True,
                    repository_url=repository_url,
                )
                if isinstance(repository_url_resolution, dict):
                    classification["url_resolution_status"] = repository_url_resolution["status"]
            elif self.graph_builder.graph and self.graph_builder.graph.has_node(package_name):
                graph_node = self.graph_builder.graph.nodes[package_name]
                repository_url = graph_node.get("repository_url", "")
                ecosystem = graph_node.get("ecosystem", "unknown")
                classification = {
                    "dependency_kind": graph_node.get("dependency_kind"),
                    "runtime": graph_node.get("runtime"),
                    "normalized_name": graph_node.get("normalized_name"),
                    "url_resolution_status": graph_node.get("url_resolution_status"),
                }
            else:
                classification = classify_dependency_fact(package_name, ecosystem=ecosystem)

            dependency = {
                "package_name": package_name,
                "percentage": percentage,
                "score": score,
                "package_url": repository_url,
                "ecosystem": ecosystem,
                **classification,
            }
            if isinstance(repository_url_resolution, dict):
                dependency["repository_url_resolution"] = repository_url_resolution
            top_deps.append(dependency)
        return top_deps

    def _assemble_results(self, graph, top_deps):
        """
        Assemble final results dict with graph data and analyzer details

        Returns:
            Dict with keys: external_packages, dependency_graph, top_dependencies, analyzer_details
        """
        results = {
            "external_packages": self.repo_analyzer.external_packages,
            "dependency_graph": self.graph_builder.get_graph_data() if graph else {},
            "top_dependencies": top_deps,
            "analyzer_details": {
                "local_imports_map": self.repo_analyzer.local_imports_map,
                "file_imports": self.repo_analyzer.file_imports,
                "file_package_components": self.repo_analyzer.file_package_components,
                "total_files": len(self.repo_analyzer.source_files),
                "languages_detected": (
                    list(
                        set(
                            file_info.get("language", "unknown")
                            for file_info in self.repo_analyzer.source_files.values()
                        )
                    )
                    if self.repo_analyzer.source_files
                    else []
                ),
            },
        }
        return enrich_analysis_result(
            results,
            repository_metadata=self.repository_metadata,
            invocation_metadata=self.invocation_metadata,
        )

    def analyze_dependencies(self, external_packages_with_urls, *, repository_metadata=None, invocation_metadata=None):
        """
        Analyze dependencies after URLs have been resolved for external packages

        Args:
            external_packages_with_urls (dict): The external packages dict, now with 'repository_url' populated
            repository_metadata (dict | None): Repository provenance metadata override
            invocation_metadata (dict | None): Invocation provenance metadata override

        Returns:
            The final analysis results dictionary
        """
        if repository_metadata is not None:
            self.repository_metadata = repository_metadata
        if invocation_metadata is not None:
            self.invocation_metadata = invocation_metadata
        if not self.repo_analyzer:
            raise RuntimeError("discover_packages must be called before analyze_dependencies")

        # Update the repo_analyzer's external_packages with the resolved URLs and receipts
        checked_at = utc_now_isoformat()
        self.repo_analyzer.external_packages = {
            package_name: ensure_repository_url_resolution(package_data, checked_at=checked_at)
            for package_name, package_data in external_packages_with_urls.items()
        }

        # Extract imports from files
        self.repo_analyzer.extract_imports_from_all_files()

        # Build dependency graph and calculate scores
        graph = self._build_dependency_graph()
        ranked_scores = self._calculate_importance_scores(graph)

        # Get top dependencies tuples and normalize
        all_self_package_names = self._collect_self_package_names()
        top_deps_tuples = self.graph_builder.get_top_dependencies(
            ranked_scores, all_self_package_names=all_self_package_names
        )
        top_deps = self._normalize_top_dependencies(top_deps_tuples)

        # Assemble and return results
        return self._assemble_results(graph, top_deps)

    def _resolve_repository_urls(self, external_packages, url_cache=None):
        """
        Resolve repository URLs with cache and robust defaults

        Args:
            external_packages (dict): External packages mapping
            url_cache (dict): Optional URL cache

        Returns:
            Dict of external_packages with 'repository_url' keys ensured
        """
        self.logger.info("... Resolving repository URLs for external packages")
        resolution_entries = resolve_package_url_receipts(external_packages, self.logger, cache=url_cache)
        for package_name, package_data in external_packages.items():
            resolution_entry = resolution_entries.get(package_name)
            if resolution_entry:
                package_data["repository_url"] = resolution_entry["repository_url"]
                package_data["repository_url_resolution"] = resolution_entry["repository_url_resolution"]
            else:
                external_packages[package_name] = ensure_repository_url_resolution(package_data)
        return external_packages

    def analyze(
        self,
        repo_path,
        specific_languages=None,
        url_cache=None,
        *,
        repository_metadata=None,
        invocation_metadata=None,
    ):
        """
        Analyze a repository and return the results as a data structure

        This method orchestrates the two-phase analysis: package discovery and dependency analysis

        Args:
            repo_path (str): Path to the repository to analyze
            specific_languages (list): Optional list of languages to analyze
            url_cache (dict): Optional pre-populated cache for package URLs
            repository_metadata (dict | None): Repository provenance metadata override
            invocation_metadata (dict | None): Invocation provenance metadata override

        Returns:
            Dictionary containing:
                - external_packages: Package metadata with URLs
                - dependency_graph: NetworkX graph as dictionary
                - top_dependencies: List of top dependencies with percentages
                - analyzer_details: Additional analysis metadata
        """
        # Step 1: Discover packages from manifests
        external_packages = self.discover_packages(repo_path, specific_languages)

        # Step 2: Resolve repository URLs for external packages
        external_packages = self._resolve_repository_urls(external_packages, url_cache)

        # Step 3: Analyze dependencies with resolved URLs
        return self.analyze_dependencies(
            external_packages,
            repository_metadata=repository_metadata,
            invocation_metadata=invocation_metadata,
        )


def analyze_repository(
    repo_path,
    specific_languages=None,
    verbose=False,
    overrides=None,
    url_cache=None,
    *,
    repository_metadata=None,
    invocation_metadata=None,
):
    """
    Convenience function to analyze a repository

    This is the main entry point for simple programmatic usage

    Args:
        repo_path (str): Path to the repository to analyze
        specific_languages (list): Optional list of languages to analyze
        verbose (bool): Enable verbose logging
        url_cache (dict): Optional pre-populated cache for package URLs
        repository_metadata (dict | None): Repository provenance metadata
        invocation_metadata (dict | None): Invocation provenance metadata

    Returns:
        Dictionary containing analysis results
    """
    analyzer = DependencyAnalyzer(
        verbose=verbose,
        repository_metadata=repository_metadata,
        invocation_metadata=invocation_metadata,
    )
    # Prefer scoped overrides when provided to avoid global mutation during tests
    if overrides:
        with ConfigOverride(overrides, logger=analyzer.logger):
            return analyzer.analyze(
                repo_path,
                specific_languages,
                url_cache=url_cache,
                repository_metadata=repository_metadata,
                invocation_metadata=invocation_metadata,
            )
    return analyzer.analyze(
        repo_path,
        specific_languages,
        url_cache=url_cache,
        repository_metadata=repository_metadata,
        invocation_metadata=invocation_metadata,
    )


def save_analysis_results(results, output_prefix, persistence, logger):
    """
    Save analysis results using the provided persistence backend

    Args:
        results (dict): Analysis results dictionary
        output_prefix (str): Prefix for output files
        persistence (object): Persistence backend to use
        logger (Logger): Logger instance

    Returns:
        True if successful, False otherwise
    """
    try:
        # Save the main analysis results
        persistence.save_analysis_results(results, output_prefix)

        return True
    except Exception as e:
        logger.error(f"Error saving analysis results: {str(e)}")
        return False


def save_machine_summary(summary, output_prefix, persistence, logger):
    """
    Save machine summary using the provided persistence backend

    Args:
        summary (dict): Machine summary dictionary
        output_prefix (str): Prefix for output files
        persistence (object): Persistence backend to use
        logger (Logger): Logger instance

    Returns:
        True if successful, False otherwise
    """
    try:
        persistence.save_machine_summary(summary, output_prefix)
        return True
    except Exception as e:
        logger.error(f"Error saving machine summary: {str(e)}")
        return False


def _maybe_generate_graph_viz(results, output_prefix, persistence, logger):
    """
    If dependency graph present, generate graph HTML and save via persistence
    """
    if "dependency_graph" in results:
        logger.info("Generating dependency graph visualization...")
        graph = nx.node_link_graph(results["dependency_graph"])
        try:
            from gardener.visualization.generate_graph import generate_graph_viz
        except Exception as e:  # ImportError or missing optional deps
            logger.warning(
                "Visualization dependencies not installed; skipping graph viz " "(install extras 'viz' to enable)."
            )
            logger.debug(f"Visualization import error detail: {e}")
            return
        graph_html = generate_graph_viz(graph, logger)
        if graph_html:
            persistence.save_graph_visualization(graph_html, output_prefix)
        else:
            logger.warning("Failed to generate graph visualization")


def generate_and_save_visualizations(results, output_prefix, persistence, logger, minimal_outputs=False):
    """
    Generate and save interactive visualization HTML file

    Args:
        results (dict): Analysis results dictionary
        output_prefix (str): Prefix for output files
        persistence (object): Persistence backend to use
        logger (Logger): Logger instance
        minimal_outputs (bool): Whether to skip visualization generation

    Returns:
        True if successful, False otherwise
    """
    if minimal_outputs:
        logger.info("Skipping visualization generation (minimal outputs mode)")
        return True

    try:
        _maybe_generate_graph_viz(results, output_prefix, persistence, logger)
        return True
    except Exception as e:
        logger.error(f"Error generating visualizations: {str(e)}")
        return False


def _prepare_repository_path(repo_path, logger):
    """
    Clone or resolve local repo path, return absolute path

    Args:
        repo_path (str): Repository path or URL
        logger (Logger): Logger instance

    Returns:
        str: Absolute repository path
    """
    repo_path = get_repo(repo_path)
    abs_path = os.path.abspath(repo_path)
    return abs_path


def _is_remote_repository_input(repo_path):
    """
    Return whether repo_path is a remote repository input
    """
    return str(repo_path).startswith(("http://", "https://", "git@"))


def _parse_focus_languages(focus_languages_str, logger):
    """
    Parse comma-separated focus languages into a normalized list or None

    Args:
        focus_languages_str (str): Comma-separated languages
        logger (Logger): Logger instance

    Returns:
        list|None: List of normalized languages, or None
    """
    focus_languages = None
    if focus_languages_str:
        focus_languages = [lang.strip().lower() for lang in focus_languages_str.split(",")]
        logger.info(f"Focusing analysis on languages: {focus_languages}")
    return focus_languages


def _apply_overrides_if_any(config_overrides, logger):
    """
    Apply config overrides if present

    Args:
        config_overrides (dict): Overrides mapping
        logger (Logger): Logger instance
    """
    if config_overrides:
        apply_config_overrides(config_overrides, logger)


def _determine_output_prefix(abs_path, output_prefix):
    """
    Use repo name when output_prefix is None, otherwise return provided value

    Args:
        abs_path (str): Absolute repository path
        output_prefix (str|None): Provided prefix or None

    Returns:
        str: Effective output prefix
    """
    if output_prefix is None:
        repo_name = os.path.basename(abs_path.rstrip("/"))
        return repo_name
    return output_prefix


def _persist_and_visualize(results, output_prefix, persistence, logger, minimal_outputs, machine_summary):
    """
    Save analysis results, optional machine summary, and visualizations

    Args:
        results (dict): Analysis results
        output_prefix (str): Output prefix
        persistence (object): Persistence backend
        logger (Logger): Logger instance
        minimal_outputs (bool): Whether to skip visualizations
        machine_summary (bool): Whether to persist the compact machine summary sidecar
    """
    save_success = save_analysis_results(results, output_prefix, persistence, logger)
    if not save_success:
        logger.error("Failed to save analysis results")

    if machine_summary:
        summary = build_machine_summary(results)
        summary_success = save_machine_summary(summary, output_prefix, persistence, logger)
        if not summary_success:
            logger.error("Failed to save machine summary")

    viz_success = generate_and_save_visualizations(results, output_prefix, persistence, logger, minimal_outputs)
    if not viz_success:
        logger.warning("Failed to generate some visualizations")


def _report_top_dependencies(results, logger):
    """
    Print top dependencies with percentages and URLs using cfg.CENTRALITY_METRIC

    Args:
        results (dict): Analysis results
        logger (Logger): Logger instance
    """
    if "top_dependencies" in results and results["top_dependencies"]:
        logger.info(f"\nTop dependencies by {cfg.CENTRALITY_METRIC} score:")
        for dep in results["top_dependencies"]:
            pkg = dep["package_name"]
            pct = dep["percentage"]
            url = dep.get("package_url", "")
            if url:
                logger.info(f"  {pct:.2f}%: {pkg} ({url})")
            else:
                logger.info(f"  {pct:.2f}%: {pkg}")
    elif "error" not in results:
        logger.info("\nNo dependencies were found, or calculation failed")


def run_analysis(
    repo_path,
    output_prefix=None,
    verbose=False,
    minimal_outputs=False,
    focus_languages_str=None,
    config_overrides=None,
    persistence=None,
    machine_summary=False,
):
    """
    Run the full dependency analysis with the specified persistence backend

    Args:
        repo_path (str): Local path to the repo or URL of hosted git repo
        output_prefix (str): Prefix for output files
        verbose (bool): Whether to enable verbose logging
        minimal_outputs (bool): Whether to skip visualization generation
        focus_languages_str (str): Comma-separated list of languages to focus on
        config_overrides (dict): Optional dictionary of configuration parameter overrides
        persistence (object): Persistence backend to use (defaults to FilePersistence)
        machine_summary (bool): Whether to persist the compact machine summary sidecar

    Returns:
        Dict of analysis results
    """
    logger = Logger(verbose=verbose)

    # Use default file persistence if none provided
    if persistence is None:
        persistence = FilePersistence()

    try:
        original_repo_path = repo_path
        abs_path = _prepare_repository_path(repo_path, logger)
        logger.info(f"Analyzing repository: {abs_path}")

        focus_languages = _parse_focus_languages(focus_languages_str, logger)
        repository_metadata = build_repository_metadata(
            input_value=original_repo_path,
            resolved_path=None if _is_remote_repository_input(original_repo_path) else abs_path,
            canonical_url=None,
            commit_sha=None,
        )
        invocation_metadata = {
            "entrypoint": "cli",
            "languages": focus_languages,
            "minimal_outputs": minimal_outputs,
            "visualize": not minimal_outputs,
            "machine_summary": machine_summary,
            "config_overrides": config_overrides or {},
        }
        # Use scoped overrides for the run to avoid global state bleed-through
        results = analyze_repository(
            repo_path=abs_path,
            specific_languages=focus_languages,
            verbose=verbose,
            overrides=config_overrides,
            repository_metadata=repository_metadata,
            invocation_metadata=invocation_metadata,
        )

        output_prefix = _determine_output_prefix(abs_path, output_prefix)
        _persist_and_visualize(results, output_prefix, persistence, logger, minimal_outputs, machine_summary)
        _report_top_dependencies(results, logger)
        return results

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise
