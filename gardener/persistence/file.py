"""
File system implementation of the persistence interface
"""

import json
import os

from gardener.common.utils import Logger
from gardener.persistence.interface import PersistenceInterface


class FilePersistence(PersistenceInterface):
    """
    File system implementation of the persistence interface

    This maintains backward compatibility with the original file-based output
    """

    def __init__(self, output_dir="output", verbose=True):
        """
        Args:
            output_dir (str): Directory where files will be saved
            verbose (bool): Enable verbose logging
        """
        self.output_dir = output_dir
        self.logger = Logger(verbose=verbose)
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

    def save_analysis_results(self, results, identifier):
        """Save analysis results as JSON file"""
        output_path = self.get_output_path(identifier, "_dependency_analysis.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        self.logger.info(f"\nAnalysis results saved to: {output_path}")

    def save_graph_visualization(self, graph_html, identifier):
        """Save graph visualization as HTML file"""
        output_path = self.get_output_path(identifier, "_dependency_graph.html")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(graph_html)

        self.logger.info(f"Interactive dependency graph saved to: {output_path}")

    def get_output_path(self, identifier, suffix):
        """Get the full file path for a given identifier and suffix"""
        # Handle cases where identifier already includes 'output/' prefix
        if identifier.startswith("output/"):
            base_path = identifier
        else:
            base_path = os.path.join(self.output_dir, identifier)

        return f"{base_path}{suffix}"
