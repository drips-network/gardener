"""
Artifact builders for analysis outputs
"""

import json
import pickle

import networkx as nx

from services.shared.config import settings


def make_results_json_bytes(analysis_results):
    """
    Serialize analysis results without the dependency graph

    Args:
        analysis_results (dict): Full analysis results payload

    Returns:
        bytes: UTF-8 encoded JSON without the dependency graph
    """
    document = dict(analysis_results or {})
    document.pop("dependency_graph", None)
    json_str = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    return json_str.encode("utf-8")


def make_graph_pickle_bytes(graph_node_link):
    """
    Convert node-link graph data into a pickled NetworkX graph

    Args:
        graph_node_link (dict): Node-link representation of the graph

    Returns:
        bytes: Pickled NetworkX graph
    """
    graph = nx.node_link_graph(graph_node_link) if graph_node_link else nx.DiGraph()
    return pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL)


def build_artifact_key(canonical_url, commit_sha, job_id, artifact_name):
    """
    Construct a stable object storage key for an artifact

    Args:
        canonical_url (str): Canonical repository URL
        commit_sha (str): Commit SHA analyzed
        job_id (UUID|str): Analysis job identifier
        artifact_name (str): File name for the artifact

    Returns:
        str: Object key rooted under the configured artifacts prefix
    """
    prefix = settings.object_storage.ARTIFACTS_PREFIX.strip("/")
    repo_segment = canonical_url.strip("/").lower()
    sha_segment = (commit_sha or "unknown").strip()
    job_segment = str(job_id).strip()
    return f"{prefix}/{repo_segment}/{sha_segment}/{job_segment}/{artifact_name}"
