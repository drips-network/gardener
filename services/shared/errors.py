"""
Error definitions for the Gardener microservice
"""

from enum import Enum


class AnalysisErrorType(Enum):
    """
    Enumeration of specific error types that can occur during analysis

    Used to provide better debugging information and error tracking
    """

    CLONE_FAILED = "CLONE_FAILED"
    PARSE_ERROR = "PARSE_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_REPO = "INVALID_REPO"


class AnalysisError(Exception):
    """
    Base exception for analysis-related errors

    Provides structured error information with categorized error types
    for better debugging and error handling in the analysis pipeline
    """

    def __init__(self, error_type, message):
        """
        Args:
            error_type (AnalysisErrorType): AnalysisErrorType enum indicating the category of error
            message (str): Human-readable error description
        """
        self.error_type = error_type
        super().__init__(message)
