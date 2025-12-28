"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Response from LLM provider."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    raw_response: Any = None


@dataclass
class ToolDefinition:
    """Tool definition for LLM."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            messages: List of message dictionaries
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Optional tool definitions
            **kwargs: Additional provider-specific options

        Returns:
            LLM response
        """
        pass

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ):
        """Stream a response from the LLM.

        Args:
            messages: List of message dictionaries
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific options

        Yields:
            Response chunks
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available.

        Returns:
            True if provider is configured and accessible
        """
        pass

    @abstractmethod
    def supports_tools(self) -> bool:
        """Check if the provider supports tool calling.

        Returns:
            True if native tool calling is supported
        """
        pass

    @property
    def name(self) -> str:
        """Get provider name."""
        return self.provider_name
