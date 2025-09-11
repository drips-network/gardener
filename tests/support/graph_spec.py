"""
Graph spec loader and matcher (minimal implementation)
"""

import json

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None


def load_graph_spec(path):
    """
    Load a YAML or JSON spec describing required nodes/edges
    """
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if yaml is None:
        raise RuntimeError("pyyaml is not installed; cannot load YAML spec")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def assert_graph_matches_spec(graph_data, spec, lax=True):
    """
    Assert that a graph contains at least the nodes/edges required by the spec

    Args:
        graph_data (dict): node_link_data structure
        spec (dict): spec with sections like {'nodes': {'file': {'include': [...]}}}
        lax (bool): if True, ignore extra nodes/edges
    """
    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])

    by_id = {n.get("id"): n for n in nodes}

    # Nodes
    for node_type, rules in (spec.get("nodes") or {}).items():
        include = rules.get("include", [])
        for nid in include:
            if nid not in by_id:
                raise AssertionError(f"Missing required node: {nid}")
            n = by_id[nid]
            if node_type and n.get("type") != node_type:
                raise AssertionError(f"Node {nid} expected type {node_type} but got {n.get('type')}")

    # Edges
    for edge_type, pairs in (spec.get("edges") or {}).items():
        for src, dst in pairs:
            match = False
            for e in links:
                if e.get("source") == src and e.get("target") == dst and e.get("type") == edge_type:
                    match = True
                    break
            if not match:
                raise AssertionError(f"Missing required edge: {src} -[{edge_type}]-> {dst}")
