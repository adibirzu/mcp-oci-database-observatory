"""LLM provider registry with fallback support."""

from typing import Any

from src.core import get_logger
from src.observability import create_span

from .anthropic import AnthropicProvider
from .base import LLMProvider, LLMResponse, ToolDefinition
from .oca import OCAProvider
from .openai import OpenAIProvider

logger = get_logger("llm.registry")


class ProviderRegistry:
    """Registry for LLM providers with fallback logic."""

    def __init__(self) -> None:
        """Initialize provider registry."""
        self._providers: dict[str, LLMProvider] = {}
        self._fallback_order: list[str] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default providers."""
        # Register all providers
        self._providers["oracle_code_assist"] = OCAProvider()
        self._providers["anthropic"] = AnthropicProvider()
        self._providers["openai"] = OpenAIProvider()

        # Default fallback order
        self._fallback_order = [
            "oracle_code_assist",
            "anthropic",
            "openai",
        ]

    def register(self, name: str, provider: LLMProvider) -> None:
        """Register a custom provider.

        Args:
            name: Provider name
            provider: Provider instance
        """
        self._providers[name] = provider
        logger.info("Provider registered", provider=name)

    def get(self, name: str) -> LLMProvider | None:
        """Get a provider by name.

        Args:
            name: Provider name

        Returns:
            Provider or None
        """
        return self._providers.get(name)

    def set_fallback_order(self, order: list[str]) -> None:
        """Set the fallback order for providers.

        Args:
            order: List of provider names in priority order
        """
        self._fallback_order = order

    def list_available(self) -> list[str]:
        """List available providers.

        Returns:
            List of available provider names
        """
        return [
            name for name, provider in self._providers.items()
            if provider.is_available()
        ]

    def get_primary(self) -> LLMProvider | None:
        """Get the primary available provider.

        Returns:
            First available provider in fallback order
        """
        for name in self._fallback_order:
            provider = self._providers.get(name)
            if provider and provider.is_available():
                return provider
        return None

    async def generate_with_fallback(
        self,
        messages: list[dict[str, Any]],
        preferred_provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate with automatic fallback.

        Args:
            messages: Conversation messages
            preferred_provider: Preferred provider name
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            tools: Tool definitions
            **kwargs: Additional options

        Returns:
            LLM response

        Raises:
            RuntimeError: If all providers fail
        """
        with create_span(
            "llm.generate_with_fallback",
            component="llm_registry",
        ):
            # Build provider order
            order = list(self._fallback_order)
            if preferred_provider and preferred_provider in order:
                order.remove(preferred_provider)
                order.insert(0, preferred_provider)

            errors = []
            for name in order:
                provider = self._providers.get(name)
                if not provider or not provider.is_available():
                    continue

                try:
                    logger.debug("Trying provider", provider=name)
                    response = await provider.generate(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tools=tools if provider.supports_tools() else None,
                        **kwargs,
                    )
                    logger.info(
                        "Provider succeeded",
                        provider=name,
                        model=response.model,
                    )
                    return response
                except Exception as e:
                    logger.warning(
                        "Provider failed, trying fallback",
                        provider=name,
                        error=str(e),
                    )
                    errors.append(f"{name}: {e}")

            raise RuntimeError(
                f"All providers failed: {'; '.join(errors)}"
            )

    def get_tool_capable_provider(self) -> LLMProvider | None:
        """Get first available provider with tool support.

        Returns:
            Provider with native tool calling or None
        """
        for name in self._fallback_order:
            provider = self._providers.get(name)
            if (
                provider
                and provider.is_available()
                and provider.supports_tools()
            ):
                return provider
        return None
