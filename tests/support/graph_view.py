"""
Stable facade over node_link_data for concise queries in tests
"""


class GraphView:
    """
    Thin wrapper around node_link_data dict
    """

    def __init__(self, graph_data):
        self.data = graph_data or {}
        self.nodes = self.data.get("nodes", [])
        self.links = self.data.get("links", [])

    def node_ids(self, where=None):
        where = where or {}
        out = []
        for n in self.nodes:
            if all(n.get(k) == v for k, v in where.items()):
                out.append(n.get("id"))
        return sorted(x for x in out if x is not None)

    def nodes_by_type(self, node_type):
        return [n for n in self.nodes if n.get("type") == node_type]

    def edge_exists(self, source, target, edge_type=None):
        for e in self.links:
            if e.get("source") == source and e.get("target") == target:
                if edge_type is None or e.get("type") == edge_type:
                    return True
        return False

    def count(self):
        return len(self.nodes)
