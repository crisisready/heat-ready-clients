"""Exceptions raised by the HeatReady client."""


class HeatReadyError(Exception):
    """An error response from the HeatReady API.

    Attributes:
        message: Human-readable error text from the API's `error` field.
        code: Stable, machine-readable identifier from the API's `code` field
            (e.g. `"project_not_found"`, `"rate_limit_exceeded"`). Branch on
            this, not on `message` text, which may change wording between
            API versions.
        status_code: The HTTP status code returned.
    """

    def __init__(self, message: str, code: str | None, status_code: int):
        super().__init__(f"{message} (code={code}, http={status_code})")
        self.message = message
        self.code = code
        self.status_code = status_code
