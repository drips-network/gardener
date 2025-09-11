"""
TypeScript-specific visitors and handlers
"""

from gardener.treewalk.javascript import JavaScriptLanguageHandler


class TypeScriptLanguageHandler(JavaScriptLanguageHandler):
    """
    Handler for TypeScript files

    Extends JavaScript handler with TypeScript-specific configuration
    """

    def __init__(self, logger):
        super().__init__(logger)
        self.language = "typescript"
        self.logger = logger

    def get_file_extensions(self):
        """
        Get the file extensions handled by this language handler

        Returns:
            List of file extensions including '.ts' and '.tsx'
        """
        return [".ts", ".tsx"]

    def process_config_file(self, config_file_path):
        """
        Process TypeScript config file for module resolution settings

        TypeScript configs (tsconfig.json) are handled the same way as jsconfig.json
        by the parent class, so we just delegate to the parent method

        Args:
            config_file_path (str): Path to the tsconfig.json file
        """
        self.logger.debug(f"Processing TypeScript config: {config_file_path}")
        # The parent class handles both jsconfig.json and tsconfig.json
        return super().process_config_file(config_file_path)
