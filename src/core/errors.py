"""Custom exception classes for the observatory framework."""


class AppError(Exception):
    """Base application error."""

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AgentError(AppError):
    """Error during agent execution."""

    def __init__(self, message: str, agent_type: str | None = None) -> None:
        super().__init__(message, "AGENT_ERROR", 500)
        self.agent_type = agent_type


class MCPError(AppError):
    """Error communicating with MCP server."""

    def __init__(self, message: str, server_id: str | None = None) -> None:
        super().__init__(message, "MCP_ERROR", 502)
        self.server_id = server_id


class ProviderError(AppError):
    """Error from LLM provider."""

    def __init__(self, message: str, provider_id: str | None = None) -> None:
        super().__init__(message, "PROVIDER_ERROR", 503)
        self.provider_id = provider_id


class ValidationError(AppError):
    """Input validation error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "VALIDATION_ERROR", 400)


class AuthenticationError(AppError):
    """Authentication failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "AUTH_ERROR", 401)


class RateLimitError(AppError):
    """Rate limit exceeded."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message, "RATE_LIMIT_ERROR", 429)
        self.retry_after = retry_after
