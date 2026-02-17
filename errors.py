"""
Pipeline error hierarchy.

All pipeline-level exceptions inherit from PipelineError, which provides:
- message: technical detail (for logs)
- user_message: safe string (for UI display, no PII)
- recoverable: whether the caller should retry
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    def __init__(self, message: str, user_message: str, recoverable: bool = True):
        self.message = message
        self.user_message = user_message
        self.recoverable = recoverable
        super().__init__(message)
