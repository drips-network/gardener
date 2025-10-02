"""
Centrality calculation functions for dependency graph analysis
"""

import networkx as nx

from gardener.common.defaults import GraphAnalysisConfig as cfg


class CentralityCalculator:
    """
    Handles centrality metric calculations for dependency graphs
    """

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance for debugging and progress reporting
        """
        self.logger = logger

    def calculate_importance(self, graph):
        """
        Calculate importance scores (PageRank or Katz) for the graph

        Args:
            graph (networkx.Graph): NetworkX graph to analyze

        Returns:
            Dictionary mapping node IDs to importance scores
        """
        if not graph or graph.number_of_nodes() == 0:
            if self.logger:
                self.logger.warning("Graph is empty or not provided. Skipping importance calculation")
            return {}

        try:
            if self.logger:
                self.logger.info(
                    f"... Calculating importance on the full graph ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)"
                )  # noqa

            # Calculate centrality based on configured metric
            ranked = {}
            try:
                if cfg.CENTRALITY_METRIC.lower() == "katz":
                    if self.logger:
                        self.logger.debug("Using Katz centrality for importance calculation on full graph")
                    ranked = self._calculate_katz(graph)
                elif cfg.CENTRALITY_METRIC.lower() == "pagerank":
                    if self.logger:
                        self.logger.debug("Using PageRank for importance calculation on full graph")
                    ranked = self._calculate_pagerank(graph)
                else:
                    if self.logger:
                        self.logger.error(f"Invalid centrality metric: {cfg.CENTRALITY_METRIC}")
                    return {}  # Return empty if metric is invalid
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"Centrality calculation on full graph failed: {str(e)}. Falling back to PageRank without weights"
                    )  # noqa
                try:
                    ranked = self._calculate_pagerank(graph, use_weights=False)
                except Exception as fallback_e:
                    if self.logger:
                        self.logger.error(f"Fallback PageRank calculation also failed: {fallback_e}")
                    return {}  # Return empty if fallback fails

            return ranked
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error during importance calculation: {str(e)}")
            return {}

    def _calculate_pagerank(self, graph, use_weights=True):
        """
        Calculate PageRank on the given graph

        Args:
            graph (networkx.Graph): NetworkX graph
            use_weights (bool): Whether to use edge weights

        Returns:
            Dictionary mapping node IDs to PageRank scores
        """
        weight_attr = "weight" if use_weights else None
        ranked = nx.pagerank(graph, weight=weight_attr, alpha=cfg.PAGERANK_ALPHA, max_iter=1000)
        if self.logger:
            self.logger.debug(
                f"Calculated PageRank for {len(ranked)} nodes " f"{'with' if use_weights else 'without'} edge weights"
            )
        return ranked

    def _calculate_katz(self, graph, use_weights=True):
        """
        Calculate Katz centrality on the given graph

        Args:
            graph (networkx.Graph): NetworkX graph
            use_weights (bool): Whether to use edge weights

        Returns:
            Dictionary mapping node IDs to Katz centrality scores
        """
        # Initial centrality values (beta)
        # Use a uniform exogenous influence of 1.0 for all nodes
        beta = {n: 1.0 for n in graph.nodes()}

        # Calculate Katz centrality
        weight_attr = "weight" if use_weights else None
        try:
            ranked = nx.katz_centrality(
                graph, alpha=cfg.KATZ_ALPHA, beta=beta, normalized=False, weight=weight_attr, max_iter=1000
            )
            if self.logger:
                self.logger.debug(
                    f"Calculated Katz centrality for {len(ranked)} nodes {'with' if use_weights else 'without'} edge weights (alpha={cfg.KATZ_ALPHA})"
                )  # noqa
        except nx.PowerIterationFailedConvergence:
            if self.logger:
                self.logger.warning(
                    f"Katz centrality failed to converge with alpha={cfg.KATZ_ALPHA}. " f"Trying without weights."
                )
            # Fallback without edge weights
            ranked = nx.katz_centrality(graph, alpha=cfg.KATZ_ALPHA, beta=beta, normalized=False, max_iter=1000)
            if self.logger:
                self.logger.debug(
                    f"Calculated Katz centrality for {len(ranked)} nodes without edge weights (alpha={cfg.KATZ_ALPHA})"
                )  # noqa
        return ranked
