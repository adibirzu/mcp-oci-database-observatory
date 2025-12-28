"""Anthropic LLM provider."""

from typing import Any, AsyncIterator

from src.core import get_logger, settings
from src.observability import create_span

from .base import LLMProvider, LLMResponse, ToolDefinition

logger = get_logger("llm.anthropic")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""

    provider_name = "anthropic"

    def __init__(self) -> None:
        """Initialize Anthropic provider."""
        self._client = None
        self.default_model = settings.llm_model or "claude-sonnet-4-20250514"

    @property
    def client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
                self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed")
        return self._client

    async def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response using Claude.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            tools: Tool definitions
            **kwargs: Additional options

        Returns:
            LLM response
        """
        with create_span(
            "llm.anthropic.generate",
            component="llm_provider",
            attributes={"model": model or self.default_model},
        ):
            # Extract system message
            system = None
            filtered_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    system = msg.get("content", "")
                else:
                    filtered_messages.append(msg)

            # Build request params
            params: dict[str, Any] = {
                "model": model or self.default_model,
                "messages": filtered_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if system:
                params["system"] = system

            # Add tools if provided
            if tools:
                params["tools"] = self._format_tools(tools)

            response = await self.client.messages.create(**params)

            # Extract content
            content = ""
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": block.input,
                        },
                    })

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                tool_calls=tool_calls,
                finish_reason=response.stop_reason or "stop",
                raw_response=response,
            )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response from Claude.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional options

        Yields:
            Response chunks
        """
        # Extract system message
        system = None
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content", "")
            else:
                filtered_messages.append(msg)

        params: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": filtered_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if system:
            params["system"] = system

        async with self.client.messages.stream(**params) as stream:
            async for text in stream.text_stream:
                yield text

    def is_available(self) -> bool:
        """Check if Anthropic is available."""
        return bool(settings.anthropic_api_key)

    def supports_tools(self) -> bool:
        """Anthropic supports native tool calling."""
        return True

    def _format_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        """Format tools for Anthropic API.

        Args:
            tools: Tool definitions

        Returns:
            Anthropic-formatted tools
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]
