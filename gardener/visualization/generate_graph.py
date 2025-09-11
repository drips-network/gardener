"""
Graph visualization generation functions (returns HTML strings)
"""

import os
import tempfile


def _import_ipysigma(logger=None):
    try:
        from ipysigma import Sigma  # type: ignore

        return Sigma
    except Exception as e:  # ImportError if extras not installed
        if logger:
            logger.warning("Visualization extras not installed (ipysigma); skipping graph visualization")
            logger.debug(f"ipysigma import error: {e}")
        return None


from gardener.common.defaults import VisualizationConfig as cfg


def generate_graph_viz(graph, logger=None):
    """
    Generate the dependency graph as an interactive HTML visualization using ipysigma

    Args:
        graph (networkx.Graph): NetworkX graph to visualize
        logger (Logger): Optional logger instance

    Returns:
        HTML string of the visualization, or None if generation fails
    """
    if not graph:
        logger and logger.error("Cannot generate visualization: Graph hasn't been built")
        return None
    if graph.number_of_nodes() == 0:
        logger and logger.warning("Graph is empty, generating an empty visualization")
        return _generate_empty_graph_html()

    vis_graph = _get_visualization_subgraph(graph, logger)
    logger and logger.debug(
        f"Visualization graph contains {vis_graph.number_of_nodes()} nodes and " f"{vis_graph.number_of_edges()} edges"
    )

    # Prepare node attributes for visualization
    node_color, node_size, node_label, node_type_mapping, node_zindex = _prepare_node_attributes(vis_graph, logger)

    # Generate HTML using Sigma.write_html to a temporary file
    try:
        Sigma = _import_ipysigma(logger)
        if Sigma is None:
            return None
        color_palette = {
            "package": cfg.COLOR_PACKAGE,
            "package component": cfg.COLOR_COMPONENT,
            "file": cfg.COLOR_FILE,
            "identifier": cfg.COLOR_IDENTIFIER,
        }

        # Create a temporary file to write the HTML
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # Write to the temporary file with category filtering and z-index layering
            Sigma.write_html(
                graph=vis_graph,
                path=tmp_path,
                background_color="white",
                node_color=node_type_mapping,  # Use node type for filtering/legend
                node_color_palette=color_palette,
                node_zindex=node_zindex,
                node_size=node_size,
                node_label=node_label,
                label_font="cursive",
                node_border_color_from="node",
                node_size_scale=("pow", 1.03),  # Use power scale with higher exponent for clearer differentiation
                node_size_range=(3, 45),  # Much wider range for greater visual impact
                default_edge_type="curve",
                edge_size="weight",
                edge_size_range=(0.6, 4.5),
                height=800,
                fullscreen=True,
            )

            # Read the generated HTML
            with open(tmp_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            return html_content

        finally:
            # Clean up the temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        if logger:
            logger.error(f"Failed to generate graph visualization: {e}")
        return None


def _generate_empty_graph_html():
    """Generate a simple HTML page for empty graphs"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dependency Graph</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
            }
            .message {
                text-align: center;
                padding: 2em;
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h2>No Dependencies Found</h2>
            <p>The analysis did not find any external dependencies in this repository.</p>
        </div>
    </body>
    </html>
    """


def _get_visualization_subgraph(graph, logger=None):
    """
    Get a subgraph suitable for visualization, prioritizing important nodes
    and filtering out low-level language references for clearer dependency visualization

    Args:
        graph (networkx.Graph): Full graph to create subgraph from
        logger (Logger): Optional logger instance

    Returns:
        NetworkX subgraph with nodes filtered for visualization
    """
    # First, identify node types in the graph
    node_types = {}
    package_nodes = set()
    file_nodes = set()
    component_nodes = set()

    # Classify nodes by type
    for node_id, attrs in graph.nodes(data=True):
        node_type = attrs.get("type", "unknown")
        node_types[node_id] = node_type

        if node_type == "package":
            package_nodes.add(node_id)
        elif node_type == "file":
            file_nodes.add(node_id)
        elif node_type == "package_component":
            component_nodes.add(node_id)

    high_level_node_ids = list(package_nodes.union(file_nodes).union(component_nodes))

    # Apply node limit if necessary (None means no limit)
    limit = cfg.VISUALIZATION_FILTER_LIMIT
    if limit is not None and len(high_level_node_ids) > limit:
        filtered_nodes = [(node_id, graph.nodes[node_id].get("importance", 0)) for node_id in high_level_node_ids]
        sorted_nodes = sorted(filtered_nodes, key=lambda x: x[1], reverse=True)

        # Select top N nodes
        high_level_node_ids = [n for n, _ in sorted_nodes[:limit]]

    logger and logger.info(
        f"\nFiltered visualization graph from {graph.number_of_nodes()} to {len(high_level_node_ids)} nodes"
    )  # noqa

    subgraph = graph.subgraph(high_level_node_ids)

    # Copy node and edge attributes to ensure they're properly carried over
    for node_id in subgraph.nodes():
        # Make sure all nodes have a proper display name for labels
        if "name" not in subgraph.nodes[node_id]:
            subgraph.nodes[node_id]["name"] = _get_node_label(
                node_id, node_types.get(node_id, "unknown"), graph.nodes[node_id]
            )

    return subgraph


def _prepare_node_attributes(graph, logger=None):
    """
    Prepare node attributes for ipysigma visualization

    Args:
        graph (networkx.Graph): NetworkX graph to prepare
        logger (Logger): Optional logger instance

    Returns:
        Tuple of (node_color, node_size, node_label, node_type_mapping, node_zindex) dictionaries
    """
    node_color = {}
    node_size = {}
    node_label = {}
    node_type_mapping = {}  # For category legend and filtering
    node_zindex = {}  # For controlling which nodes appear on top

    # Use scaling factor from configuration
    scaling_factor = cfg.NODE_SIZE_SCALING_FACTOR

    for node_id, attrs in graph.nodes(data=True):
        node_type = attrs.get("type", "unknown")
        importance_score = attrs.get("importance", 0.0)  # Default to 0.0

        if node_type == "package":
            node_zindex[node_id] = 40  # Package nodes on top
            node_type_mapping[node_id] = "package"
            node_color[node_id] = cfg.COLOR_PACKAGE
        elif node_type == "package_component":
            node_zindex[node_id] = 30  # Component nodes second layer
            node_type_mapping[node_id] = "package component"
            node_color[node_id] = cfg.COLOR_COMPONENT
        elif node_type == "file":
            node_zindex[node_id] = 20  # File nodes third layer
            node_type_mapping[node_id] = "file"
            node_color[node_id] = cfg.COLOR_FILE
        else:  # Unknown type
            node_zindex[node_id] = 10  # Default layer
            node_type_mapping[node_id] = "unknown"
            node_color[node_id] = cfg.COLOR_DEFAULT

        if node_type == "package":
            node_size[node_id] = 6 + (importance_score * scaling_factor * 1.2)
        elif node_type == "package_component":
            node_size[node_id] = 6 + (importance_score * scaling_factor * 0.9)
        elif node_type == "file":
            node_size[node_id] = 6 + (importance_score * scaling_factor * 0.6)
        else:  # Default size for unknown types
            node_size[node_id] = 6 + (importance_score * scaling_factor * 0.333)

        label = _get_node_label(node_id, node_type, attrs)
        node_label[node_id] = label

    return node_color, node_size, node_label, node_type_mapping, node_zindex


def _get_node_label(node_id, node_type, node_attrs):
    """
    Generate a legible label for each node

    Args:
        node_id (str): Identifier of the node
        node_type (str): Type of the node
        node_attrs (dict): Node attributes

    Returns:
        Formatted label string for the node
    """
    name = node_attrs.get("name", node_id)  # Default to node_id if name attribute missing

    if node_type == "file":
        # Show relative path, truncated if too long
        label = node_id
        if len(label) > cfg.MAX_NODE_LABEL_LENGTH:
            return "..." + label[-cfg.NODE_LABEL_SUFFIX_LENGTH :]
        return label
    elif node_type == "package_component":
        # Show component name (part after last dot or :: for Rust)
        if "::" in name:
            label = name.split("::")[-1]
        elif "." in name:
            label = name.split(".")[-1]
        else:
            label = name
        return label[: cfg.MAX_NODE_LABEL_LENGTH] + ("..." if len(label) > cfg.MAX_NODE_LABEL_LENGTH else "")
    else:  # Package or Unknown
        label = node_id
        return label[: cfg.MAX_NODE_LABEL_LENGTH] + ("..." if len(label) > cfg.MAX_NODE_LABEL_LENGTH else "")
