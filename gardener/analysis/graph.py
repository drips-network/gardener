"""
Graph building and PageRank calculation
"""

from collections import defaultdict

import networkx as nx
from grep_ast import filename_to_lang

from gardener.analysis.centrality import CentralityCalculator
from gardener.common.defaults import GraphAnalysisConfig as cfg


class DependencyGraphBuilder:
    """
    Builds and analyzes the dependency graph by constructing a directed graph of file,
    package, and component dependencies, then calculating importance scores using
    PageRank or Katz centrality metrics
    """

    # Node types: 'file', 'package', 'package_component'
    # Edge types: imports_local, imports_package, contains_component, uses_component
    # Centrality computed over object nodes: packages & components

    # Edge type labels
    EDGE_T_IMPORTS_PACKAGE = "imports_package"
    EDGE_T_IMPORTS_LOCAL = "imports_local"
    EDGE_T_CONTAINS_COMPONENT = "contains_component"
    EDGE_T_USES_COMPONENT = "uses_component"

    # Language → stdlib ecosystem mapping
    _STDLIB_ECOSYSTEM_MAP = {
        "go": "go_stdlib",
        "python": "python_stdlib",
        "rust": "rust_stdlib",
        "javascript": "js_stdlib",
        "typescript": "ts_stdlib",
        "solidity": "solidity_stdlib",
    }

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance for debugging and progress reporting
        """
        self.logger = logger
        self.graph = None
        self.object_nodes = set()
        self.import_to_node = {}
        self.import_to_dist = {}
        self._ambiguous_choices = {}  # import_name -> {chosen: str, candidates: [str, ...]}
        self.external_packages = {}
        self.file_package_components = {}
        self.local_imports_map = {}
        self.source_files = {}
        self.file_imports = {}
        self.centrality_calculator = CentralityCalculator(logger=logger)

        # Initialize instance-level edge weights from configuration so CLI overrides apply
        self.EDGE_W_IMPORTS_PACKAGE = cfg.EDGE_W_IMPORTS_PACKAGE
        self.EDGE_W_IMPORTS_LOCAL = cfg.EDGE_W_IMPORTS_LOCAL
        self.EDGE_W_CONTAINS_COMPONENT = cfg.EDGE_W_CONTAINS_COMPONENT
        self.EDGE_W_USES_COMPONENT = cfg.EDGE_W_USES_COMPONENT

    def build_dependency_graph(
        self, source_files, external_packages, file_imports, file_package_components, local_imports_map
    ):
        """
        Build dependency graph focusing on File, Package, and PackageComponent nodes,
        including local file-to-file import edges

        Args:
            source_files (dict): Dictionary mapping relative paths to absolute paths
            external_packages (dict): Dictionary of external packages with their import names
            file_imports (dict): Dictionary mapping file paths to lists of imported package names
            file_package_components (dict): Dictionary mapping file paths to lists of (package, component) tuples
            local_imports_map (dict): Dictionary mapping file paths to lists of imported local file paths

        Returns:
            NetworkX directed graph
        """
        G = nx.DiGraph()

        # Orchestration pipeline:
        # 1) Build import→distribution map
        # 2) Add file nodes and external package nodes
        # 3) Connect file→package, then components, then local imports

        # Save inputs for later reference
        self.source_files = source_files
        self.external_packages = external_packages
        self.file_imports = file_imports
        self.file_package_components = file_package_components
        self.local_imports_map = local_imports_map

        # Build import-to-distribution map (logs ambiguous warnings identically)
        self.import_to_dist = self._build_import_to_dist_map(external_packages)

        all_files = set(source_files.keys())

        self._add_file_nodes(G, source_files)

        if self.logger:
            self.logger.debug(f"Adding package nodes from distribution names")
        self.object_nodes.clear()

        # Track which import name maps to which node ID
        self.import_to_node = {}

        # First create nodes for each unique distribution package
        self._add_external_package_nodes(G, external_packages)

        # Connect files directly to imported packages (overall file dependency)
        # This needs to run BEFORE _add_package_component_edges so that stdlib package nodes
        # and their entries in self.import_to_node are created
        if self.logger:
            self.logger.debug("Connecting files to directly imported packages")
        self._add_file_package_edges(G)

        # Connect imported package components
        if self.logger:
            self.logger.debug("Connecting package components")
        self._add_package_component_edges(G)

        if self.logger:
            self.logger.debug("Connecting local file imports")
        self._add_local_import_edges(G)

        self.graph = G
        if self.logger:
            self.logger.info(
                f"... Dependency graph built with {G.number_of_nodes()} nodes and " f"{G.number_of_edges()} edges"
            )
        return G

    def calculate_importance(self):
        """
        Calculate importance scores (PageRank or Katz) focusing on Package and PackageComponent nodes

        Returns:
            Dictionary mapping node IDs to importance scores for object nodes
        """
        # Copy object_nodes to centrality calculator
        self.centrality_calculator.object_nodes = self.object_nodes
        scores = self.centrality_calculator.calculate_importance(self.graph)

        # Store scores in graph nodes based on centrality metric
        if scores and self.graph:
            metric_name = cfg.CENTRALITY_METRIC.lower()
            for node_id, score in scores.items():
                if self.graph.has_node(node_id):
                    self.graph.nodes[node_id][metric_name] = score
                    # Also store as 'importance' for visualization
                    self.graph.nodes[node_id]["importance"] = score

        return scores

    def get_top_dependencies(self, ranked_scores, all_self_package_names=None):
        """
        Get top dependencies based on calculated importance scores, excluding self-references

        Args:
            ranked_scores (dict): Dictionary mapping node IDs to importance scores (from calculate_importance)
            all_self_package_names (set): Set of distribution and import names belonging to the analyzed repo

        Returns:
            List of (package_name, score) tuples ordered by importance (raw scores, not normalized)
        """
        if not ranked_scores:
            self.logger.warning("No importance scores provided to get_top_dependencies")
            return []
        if not self.graph:
            self.logger.error("Graph hasn't been built yet, cannot get node attributes")
            return []

        # Accumulate importance scores by distribution name from the ranked_scores dictionary
        package_scores = defaultdict(float)

        # Iterate through the ranked nodes (packages and components)
        for node, score in ranked_scores.items():
            if not self.graph.has_node(node):
                self.logger.warning(f"Node '{node}' from ranked_scores not found in graph, skipping")
                continue

            attrs = self.graph.nodes[node]
            node_type = attrs.get("type")

            if node_type in ("package", "package_component"):
                # Use distribution_name for aggregating scores
                # Fallback logic remains similar, using 'package' attribute or node ID itself if needed
                dist = attrs.get("distribution_name", attrs.get("package", node))

                package_scores[dist] += score
                self.logger.debug(f"Adding score {score:.10f} to distribution '{dist}' from node '{node}'")

        if all_self_package_names is None:
            all_self_package_names = set()

        self.logger.debug(f"Filtering scores. Filter set: {all_self_package_names}")
        self.logger.debug(f"Package scores before filtering (sample): {dict(list(package_scores.items())[:20])}")

        filtered_scores = {
            pkg: score for pkg, score in package_scores.items() if score > 0 and pkg not in all_self_package_names
        }

        self.logger.debug(f"Package scores after filtering (sample): {dict(list(filtered_scores.items())[:20])}")

        # Convert filtered scores to list and sort
        scores_list = [(pkg, score) for pkg, score in filtered_scores.items()]
        top_packages = sorted(scores_list, key=lambda x: x[1], reverse=True)

        return top_packages

    def _detect_language_from_filename(self, rel_path):
        """
        Return language inferred from rel_path, honoring .mjs/.cjs overrides

        Args:
            rel_path (str): Repository-relative file path

        Returns:
            Language name string inferred from filename or 'unknown'
        """
        lang_result = filename_to_lang(rel_path)
        language = lang_result if lang_result else "unknown"
        if rel_path.endswith(".mjs"):
            language = "javascript"
        elif rel_path.endswith(".cjs"):
            language = "javascript"
        return language

    def _stdlib_ecosystem_for_language(self, lang):
        """
        Map a file language to its stdlib ecosystem label

        Args:
            lang (str): File language label (e.g., 'python')

        Returns:
            Ecosystem label for stdlib (e.g., 'python_stdlib') or 'unknown_stdlib'
        """
        return self._STDLIB_ECOSYSTEM_MAP.get(lang, "unknown_stdlib")

    def _create_package_node(self, G, node_id, ecosystem, distribution_name, import_names):
        """
        Ensure a package node is present with attributes and mark as object node

        Args:
            G (networkx.DiGraph): Graph instance
            node_id (str): Node identifier
            ecosystem (str): Ecosystem label
            distribution_name (str): Distribution name to store on node
            import_names (list): Import names associated to the distribution
        """
        G.add_node(
            node_id,
            type="package",
            ecosystem=ecosystem,
            distribution_name=distribution_name,
            import_names=import_names,
        )
        self.object_nodes.add(node_id)

    def _add_edge(self, G, src, dst, edge_type, weight, **attrs):
        """
        Add a directed edge with uniform attributes

        Args:
            G (networkx.DiGraph): Graph instance
            src (str): Source node id
            dst (str): Destination node id
            edge_type (str): Edge type label
            weight (float): Edge weight
        """
        G.add_edge(src, dst, weight=weight, type=edge_type, **attrs)

    def _build_import_to_dist_map(self, external_packages):
        """
        Construct a deterministic import-to-distribution mapping and log ambiguous import warnings

        Args:
            external_packages (dict): External packages metadata

        Returns:
            dict mapping import names to distribution names
        """
        # Gather candidate distributions per import name
        candidates = defaultdict(set)
        for dist, pkg_data in external_packages.items():
            import_names = pkg_data.get("import_names", []) or [dist]
            for imp in import_names:
                candidates[imp].add(dist)

        # Deterministically choose the lexicographically smallest distribution
        import_to_dist = {}
        self._ambiguous_choices = {}
        for imp, dists in candidates.items():
            sorted_cands = sorted(dists)
            chosen = sorted_cands[0]
            import_to_dist[imp] = chosen
            if len(sorted_cands) > 1:
                self._ambiguous_choices[imp] = {
                    "chosen": chosen,
                    "candidates": sorted_cands,
                }

        # Log one standardized warning per ambiguous import
        if self.logger and self._ambiguous_choices:
            for imp, info in sorted(self._ambiguous_choices.items()):
                cand_list = ", ".join(info["candidates"])
                self.logger.warning(
                    f"Ambiguous import '{imp}' has candidates: {cand_list}; choosing '{info['chosen']}' by lexicographic rule"
                )  # noqa

        if self.logger:
            self.logger.debug(f"Created import-to-distribution mapping with {len(import_to_dist)} entries")
        return import_to_dist

    def _add_file_nodes(self, G, source_files):
        """
        Create file nodes with language attribute

        Args:
            G (networkx.DiGraph): Graph instance
            source_files (dict): Map of relative path -> absolute path
        """
        all_files = set(source_files.keys())
        for rel_path in all_files:
            abs_path = source_files.get(rel_path)
            if not abs_path:
                if self.logger:
                    self.logger.warning(f"Absolute path not found for {rel_path}, skipping file node")
                continue

            language = self._detect_language_from_filename(rel_path)
            G.add_node(rel_path, type="file", language=language)
            if self.logger:
                self.logger.debug(f"Added file node: {rel_path} (lang: {language})")

    def _add_external_package_nodes(self, G, external_packages):
        """
        Add one node per distribution name and map each import_name -> dist_name

        Args:
            G (networkx.DiGraph): Graph instance
            external_packages (dict): External packages metadata
        """
        for dist_name, pkg_data in external_packages.items():
            ecosystem = pkg_data.get("ecosystem", "unknown")
            G.add_node(
                dist_name,
                type="package",
                ecosystem=ecosystem,
                distribution_name=dist_name,
                import_names=pkg_data.get("import_names", [dist_name]),
            )
            self.object_nodes.add(dist_name)
            if self.logger:
                self.logger.debug(f"Added package node: {dist_name} (ecosystem: {ecosystem})")

            for import_name in pkg_data.get("import_names", [dist_name]):
                # Respect deterministic import->distribution resolution if present
                resolved_dist = self.import_to_dist.get(import_name, dist_name)
                self.import_to_node[import_name] = resolved_dist
                if self.logger:
                    self.logger.debug(f"Mapped import '{import_name}' to distribution node '{resolved_dist}'")

    def _resolve_dist_node_for_import(self, package_name):
        """
        Return mapped distribution node id for an import name, applying
        longest-prefix fallback for hierarchical ecosystems (e.g., Go)

        Args:
            package_name (str): Import identifier (e.g., 'github.com/x/y/z')

        Returns:
            str|None: Distribution node id, or None if unmapped
        """
        node = self.import_to_node.get(package_name)
        if node:
            return node
        if "/" in package_name:
            prefix = package_name
            while "/" in prefix:
                prefix = prefix.rsplit("/", 1)[0]
                node = self.import_to_node.get(prefix)
                if node:
                    return node
        return None

    def _ensure_stdlib_node_if_needed(self, G, file_path, package_name):
        """
        Ensure stdlib-like package node exists when import is unmapped and not in external packages

        Args:
            G (networkx.DiGraph): Graph instance
            file_path (str): File path importing the package
            package_name (str): Import name

        Returns:
            Tuple (dist_node, dist_node_for_edge, ecosystem)
        """
        file_lang = G.nodes[file_path].get("language", "unknown")
        ecosystem = "unknown"
        # Language-aware stdlib classification
        if file_lang == "go":
            # Only mark Go stdlib when first path segment has no dot
            first_seg = package_name.split("/", 1)[0]
            if "." not in first_seg:
                ecosystem = self._stdlib_ecosystem_for_language(file_lang)
        elif file_lang == "python":
            ecosystem = self._stdlib_ecosystem_for_language(file_lang)
        elif file_lang == "rust":
            # Recognize Rust standard crates by name
            if package_name in ("std", "core", "alloc", "test"):
                ecosystem = self._stdlib_ecosystem_for_language(file_lang)
        elif file_lang == "javascript":
            ecosystem = self._stdlib_ecosystem_for_language(file_lang)
        elif file_lang == "typescript":
            ecosystem = self._stdlib_ecosystem_for_language(file_lang)
        self._create_package_node(G, package_name, ecosystem, package_name, [package_name])
        self.import_to_node[package_name] = package_name
        dist_node = package_name
        dist_node_for_edge = dist_node
        if self.logger:
            self.logger.debug(
                f"Created {'stdlib' if ecosystem.endswith('_stdlib') else 'unknown'} package node: "
                f"{package_name} (ecosystem: {ecosystem})"
            )
        return dist_node, dist_node_for_edge, ecosystem

    def _normalize_node_fs_target(self, dist_node):
        """
        Normalize target node id for special Node stdlib identifiers like 'node:fs'
        """
        return "fs" if dist_node == "node:fs" else dist_node

    def _ensure_external_package_node_if_missing(self, G, package_name, dist_node):
        """
        Create a known external package node if absent, using manifest metadata
        """
        node_id_to_add = dist_node
        distribution_name_attr = dist_node
        ecosystem = self.external_packages[package_name].get("ecosystem", "npm")
        import_names_attr = self.external_packages[package_name].get("import_names", [package_name])
        self._create_package_node(G, node_id_to_add, ecosystem, distribution_name_attr, import_names_attr)
        self.import_to_node[package_name] = node_id_to_add

    def _ensure_unknown_or_stdlib_node_if_missing(self, G, package_name, dist_node, dist_node_for_edge, ecosystem):
        """
        Create a stdlib/unknown package node when not declared in external_packages
        Returns updated dist_node_for_edge (for 'node:fs' normalization)
        """
        node_id_to_add = dist_node
        distribution_name_attr = dist_node
        import_names_attr = [package_name]

        if dist_node == "node:fs":
            node_id_to_add = "fs"
            dist_node_for_edge = node_id_to_add
            distribution_name_attr = node_id_to_add
            import_names_attr = ["fs", "node:fs"]
        elif dist_node == "path":
            distribution_name_attr = node_id_to_add

        self._create_package_node(G, node_id_to_add, ecosystem, distribution_name_attr, import_names_attr)
        if dist_node == "node:fs":
            self.import_to_node["fs"] = node_id_to_add
            self.import_to_node["node:fs"] = node_id_to_add
        else:
            self.import_to_node[package_name] = node_id_to_add

        if self.logger:
            self.logger.debug(
                f"Created {'stdlib' if str(ecosystem).endswith('_stdlib') else 'unknown'} package node: "
                f"{node_id_to_add} (ecosystem: {ecosystem})"
            )
        return dist_node_for_edge

    def _add_imports_package_edge(self, G, file_path, dist_node_for_edge, package_name):
        """
        Add file -> imports_package -> package edge using internal constants
        """
        edge_attrs = {"ident": package_name}
        if package_name in self._ambiguous_choices:
            edge_attrs["ambiguity_resolution"] = "lexicographic"
        self._add_edge(
            G,
            file_path,
            dist_node_for_edge,
            self.EDGE_T_IMPORTS_PACKAGE,
            self.EDGE_W_IMPORTS_PACKAGE,
            **edge_attrs,
        )

    def _resolve_distribution_context(self, G, pkg_name):
        """
        Resolve which distribution node and attributes apply for a package name

        Returns a tuple (dist_node or None, dist, ecosystem). If dist_node is None and
        the package is unknown, caller should skip processing.
        """
        dist_node = self._resolve_dist_node_for_import(pkg_name)

        if not dist_node:
            if pkg_name in self.external_packages:
                dist_node = pkg_name
                if self.logger:
                    self.logger.debug(
                        f"Package '{pkg_name}' not found in import_to_node mapping, "
                        f"using as its own distribution node"
                    )
            else:
                if self.logger:
                    self.logger.debug(
                        f"Skipping unknown package '{pkg_name}' " f"(not found in import_to_node or external_packages)"
                    )
                return None, None, None

        dist = dist_node
        ecosystem = "unknown"
        if G.has_node(dist_node):
            node_attrs = G.nodes[dist_node]
            dist = node_attrs.get("distribution_name", dist_node)
            ecosystem = node_attrs.get("ecosystem", "unknown")
        return dist_node, dist, ecosystem

    def _normalize_component_identifier(self, pkg_name, component_name_from_visitor):
        """
        Normalize component identifier and return (final_component_node_id, simple_name_for_attr)
        """
        simple_name_for_attr = component_name_from_visitor
        base_component_path = component_name_from_visitor
        normalized_component_path = component_name_from_visitor

        if " as " in normalized_component_path:
            normalized_component_path = normalized_component_path.split(" as ")[0].strip()

        if " {" in normalized_component_path and normalized_component_path.endswith("}"):
            normalized_component_path = normalized_component_path.split(" {")[0].strip()

        if normalized_component_path.endswith(".sol") and (
            "/" in normalized_component_path or "." in normalized_component_path
        ):
            normalized_component_path = normalized_component_path[:-4]

        if normalized_component_path.startswith(pkg_name + "."):
            base_component_path = normalized_component_path[len(pkg_name) + 1 :]
        else:
            base_component_path = normalized_component_path

        if not base_component_path:
            return None, simple_name_for_attr

        if normalized_component_path.startswith(pkg_name + "."):
            full_component_name = normalized_component_path
        elif normalized_component_path.startswith(pkg_name + "::"):
            full_component_name = normalized_component_path
        else:
            full_component_name = f"{pkg_name}.{base_component_path}"

        return full_component_name, simple_name_for_attr

    def _ensure_component_node_and_contains_edge(self, G, component_node_id, pkg_name, dist, ecosystem, simple_name):
        """
        Ensure component node exists and add contains_component edge from the package distribution
        """
        if not G.has_node(component_node_id):
            G.add_node(
                component_node_id,
                type="package_component",
                package=pkg_name,
                distribution_name=dist,
                ecosystem=ecosystem,
                component=simple_name,
            )
            self.object_nodes.add(component_node_id)
            dist_node_for_contains = self.import_to_node.get(pkg_name, pkg_name)
            if G.has_node(dist_node_for_contains):
                self._add_edge(
                    G,
                    dist_node_for_contains,
                    component_node_id,
                    self.EDGE_T_CONTAINS_COMPONENT,
                    self.EDGE_W_CONTAINS_COMPONENT,
                )
            if self.logger:
                self.logger.debug(
                    f"Added component node: {component_node_id} " f"(for package {pkg_name}, distribution {dist})"
                )

    def _add_uses_component_edge_if_applicable(self, G, file_path, component_node_id, component_ident):
        """
        Add file -> uses_component -> component edge if both nodes exist
        """
        if G.has_node(file_path) and G.has_node(component_node_id):
            self._add_edge(
                G,
                file_path,
                component_node_id,
                self.EDGE_T_USES_COMPONENT,
                self.EDGE_W_USES_COMPONENT,
                ident=component_ident,
            )
            if self.logger:
                self.logger.debug(f"Added file-to-component edge: {file_path} -> {component_node_id}")

    def _add_package_component_edges(self, G):
        """
        Add edges for package components and their relationships

        Creates package_component nodes and establishes relationships:
        - package -> contains_component -> package_component
        - file -> uses_component -> package_component

        Args:
            G (networkx.DiGraph): NetworkX graph to add edges to
        """
        if self.logger:
            self.logger.debug(f"Processing package components for {len(self.file_package_components)} files")
        for file_path, components in self.file_package_components.items():
            if not G.has_node(file_path):
                continue

            for pkg_name, component_name_from_visitor in components:
                dist_node, dist, ecosystem = self._resolve_distribution_context(G, pkg_name)
                if not dist_node:
                    continue

                final_component_node_id, simple_name_for_attr = self._normalize_component_identifier(
                    pkg_name, component_name_from_visitor
                )
                if not final_component_node_id:
                    continue

                self._ensure_component_node_and_contains_edge(
                    G,
                    final_component_node_id,
                    pkg_name,
                    dist,
                    ecosystem,
                    simple_name_for_attr,
                )

                self._add_uses_component_edge_if_applicable(
                    G, file_path, final_component_node_id, component_name_from_visitor
                )

    def _add_file_package_edges(self, G):
        """
        Add edges from files to the packages they import

        Creates package nodes as needed and establishes file -> imports_package -> package relationships
        Handles standard library packages by detecting ecosystem from file language

        Args:
            G (networkx.DiGraph): NetworkX graph to add edges to
        """
        for file_path, package_names in self.file_imports.items():
            if not G.has_node(file_path):
                continue

            for package_name in package_names:
                dist_node = self._resolve_dist_node_for_import(package_name)
                dist_node_for_edge = dist_node
                ecosystem = None

                if not dist_node:
                    if package_name in self.external_packages:
                        dist_node = package_name
                        dist_node_for_edge = dist_node
                        if self.logger:
                            self.logger.warning(
                                f"Package '{package_name}' in external_packages " f"but not in import_to_node mapping"
                            )
                    else:
                        # JavaScript/TypeScript heuristic: map unknown '@scope/foo' to '@scope/core' if present
                        file_lang = G.nodes[file_path].get("language", "unknown")
                        if file_lang in ("javascript", "typescript") and package_name.startswith("@"):
                            parts = package_name.split("/")
                            if len(parts) >= 2:
                                scope = parts[0]
                                core_candidate = f"{scope}/core"
                                if core_candidate in self.external_packages:
                                    dist_node = core_candidate
                                    dist_node_for_edge = dist_node
                                    # Cache this resolution to avoid repeating work
                                    self.import_to_node[package_name] = dist_node
                                    if self.logger:
                                        self.logger.debug(
                                            f"Mapped unknown scoped import '{package_name}' to '{dist_node}' via '@scope/core' heuristic"  # noqa
                                        )
                        if not dist_node:
                            dist_node, dist_node_for_edge, ecosystem = self._ensure_stdlib_node_if_needed(
                                G, file_path, package_name
                            )

                if dist_node == "node:fs":
                    dist_node_for_edge = self._normalize_node_fs_target(dist_node)

                if not G.has_node(dist_node_for_edge):
                    if package_name in self.external_packages:
                        self._ensure_external_package_node_if_missing(G, package_name, dist_node)
                    else:
                        dist_node_for_edge = self._ensure_unknown_or_stdlib_node_if_missing(
                            G, package_name, dist_node, dist_node_for_edge, ecosystem
                        )

                self._add_imports_package_edge(G, file_path, dist_node_for_edge, package_name)
                self.logger.debug(
                    f"Added imports_package edge: {file_path} -> {dist_node_for_edge} (import: {package_name})"
                )

    def _ensure_file_node_if_missing(self, G, rel_path, importing_file):
        """
        Ensure a file node exists for a locally imported file; log accordingly

        Returns True if the node exists or was created; False to skip
        """
        if not G.has_node(rel_path):
            if rel_path in self.source_files:
                lang_result = filename_to_lang(rel_path)
                language = lang_result if lang_result else "unknown"
                G.add_node(rel_path, type="file", language=language)
                if self.logger:
                    self.logger.info(
                        f"Locally imported file '{rel_path}' (from '{importing_file}') not found in graph. Adding it now."  # noqa
                    )
            else:
                if self.logger:
                    self.logger.warning(
                        f"Locally imported file '{rel_path}' (from '{importing_file}') not found in source files or graph."  # noqa
                    )
                return False
        return True

    def _add_local_import_edge(self, G, importing_file, imported_file):
        """
        Add a local import edge using internal constants and preserve debug log
        """
        self._add_edge(
            G,
            importing_file,
            imported_file,
            self.EDGE_T_IMPORTS_LOCAL,
            self.EDGE_W_IMPORTS_LOCAL,
        )
        if self.logger:
            self.logger.debug(f"Added local import edge: {importing_file} -> {imported_file}")

    def _add_local_import_edges(self, G):
        """
        Add edges between files for local imports

        Creates file -> imports_local -> file relationships for intra-repository dependencies
        Creates missing file nodes as needed for imported local files

        Args:
            G (networkx.DiGraph): NetworkX graph to add edges to
        """
        added_edges = 0
        for importing_file, imported_files in self.local_imports_map.items():
            if not G.has_node(importing_file):
                if self.logger:
                    self.logger.warning(
                        f"Importing file '{importing_file}' not found in graph, skipping local imports."
                    )
                continue

            for imported_file in imported_files:
                if not self._ensure_file_node_if_missing(G, imported_file, importing_file):
                    continue

                self._add_local_import_edge(G, importing_file, imported_file)
                added_edges += 1

        if self.logger:
            self.logger.debug(f"Added {added_edges} local import edges")

    def get_graph_data(self):
        """
        Get graph data in a format suitable for JSON serialization

        Returns:
            Dictionary representation of the graph with nodes and edges data,
            or empty dict if no graph has been built
        """
        if self.graph:
            data = nx.node_link_data(self.graph)
            if cfg.SERIALIZE_SORT_KEYS:
                # Sort nodes by (type, id) and links by (type, source, target, ident)
                nodes = data.get("nodes", [])
                links = data.get("links", [])
                nodes.sort(key=lambda n: (str(n.get("type", "")), str(n.get("id", ""))))
                links.sort(
                    key=lambda e: (
                        str(e.get("type", "")),
                        str(e.get("source", "")),
                        str(e.get("target", "")),
                        str(e.get("ident", "")),
                    )
                )
                data["nodes"] = nodes
                data["links"] = links
            return data
        return {}
