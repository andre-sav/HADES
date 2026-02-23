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


# --- ZoomInfo errors ---


class ZoomInfoError(PipelineError):
    """Base for all ZoomInfo API errors.

    Catch this to distinguish ZoomInfo failures from other pipeline
    errors (e.g., BudgetExceededError). Otherwise catch PipelineError.
    """

    pass


class ZoomInfoAuthError(ZoomInfoError):
    """Authentication failed."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            user_message="ZoomInfo authentication failed. Please check your API credentials.",
            recoverable=False,
        )


class ZoomInfoRateLimitError(ZoomInfoError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int = 60, detail: str = ""):
        self.retry_after = retry_after
        if retry_after >= 60:
            wait_display = f"{retry_after // 60} minute{'s' if retry_after >= 120 else ''}"
        else:
            wait_display = f"{retry_after} seconds"
        msg = f"Rate limit reached. Try again in {wait_display}."
        # detail is logged in technical message only, not shown to user
        super().__init__(
            message=f"Rate limit exceeded. Retry after {retry_after} seconds. {detail}".strip(),
            user_message=msg,
            recoverable=True,
        )


class ZoomInfoAPIError(ZoomInfoError):
    """General API error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(
            message=f"API error {status_code}: {message}",
            user_message=f"ZoomInfo API error ({status_code}). Check logs for details.",
            recoverable=status_code >= 500,
        )


# --- Budget errors ---


class BudgetExceededError(PipelineError):
    """Raised when a query would exceed the budget cap."""

    def __init__(self, workflow_type: str, current_usage: int, cap: int, requested: int):
        self.workflow_type = workflow_type
        self.current_usage = current_usage
        self.cap = cap
        self.requested = requested
        self.remaining = cap - current_usage

        super().__init__(
            message=(
                f"{workflow_type} budget would be exceeded. "
                f"Current: {current_usage}, Cap: {cap}, Requested: {requested}, "
                f"Remaining: {self.remaining}"
            ),
            user_message=(
                f"{workflow_type.title()} weekly budget exceeded. "
                f"{current_usage} of {cap} credits used this week. "
                f"This query needs ~{requested} credits. Resets Monday."
            ),
            recoverable=False,
        )


# --- Zoho errors ---


class ZohoAPIError(PipelineError):
    """Zoho API error with status code."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(
            message=message,
            user_message=f"Zoho CRM error (HTTP {status_code}). Check logs for details.",
            recoverable=status_code >= 500 or status_code == 0,
        )
