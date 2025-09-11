"""
Abstract base class for persistence backends
"""

from abc import ABC, abstractmethod


class PersistenceInterface(ABC):
    """
    Abstract interface for persisting Gardener analysis results

    This allows for different storage backends (file system, database, cloud storage, etc.)
    while keeping the core analysis logic independent of storage concerns
    """

    @abstractmethod
    def save_analysis_results(self, results, identifier):
        """
        Save the main analysis results (JSON data)

        Args:
            results (dict): Dictionary containing analysis results
            identifier (str): Unique identifier for this analysis (e.g., output prefix)
        """
        pass

    @abstractmethod
    def save_graph_visualization(self, graph_html, identifier):
        """
        Save the interactive graph visualization

        Args:
            graph_html (str): HTML content of the graph visualization
            identifier (str): Unique identifier for this analysis
        """
        pass

    @abstractmethod
    def get_output_path(self, identifier, suffix):
        """
        Get the output path/URI for a given identifier and suffix

        Args:
            identifier (str): Unique identifier for this analysis
            suffix (str): File suffix (e.g., '_dependency_analysis.json')

        Returns:
            Path or URI where the file will be/was saved
        """
        pass
