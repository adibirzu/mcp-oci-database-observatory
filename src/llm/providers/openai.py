"""OpenAI LLM provider."""

import json
from typing import Any, AsyncIterator

from src.core import get_logger, settings
from src.observability import create_span

from .base import LLMProvider, LLMResponse, ToolDefinition

logger = get_logger("llm.openai")


class OpenAIProvider(LLMProvider):
    """OpenAI GPT LLM provider."""

    provider_name = "openai"

    def __init__(self) -> None:
        """Initialize OpenAI provider."""
        self._client = None
        self.default_model = "gpt-4o"

    @property
    def client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:
                raise RuntimeError("openai package not installed")
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
        """Generate response using GPT.

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
            "llm.openai.generate",
            component="llm_provider",
            attributes={"model": model or self.default_model},
        ):
            params: dict[str, Any] = {
                "model": model or self.default_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            # Add tools if provided
            if tools:
                params["tools"] = self._format_tools(tools)

            response = await self.client.chat.completions.create(**params)
            choice = response.choices[0]

            # Extract tool calls
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments),
                        },
                    })

            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0,
                },
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
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
        """Stream response from GPT.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional options

        Yields:
            Response chunks
        """
        response = await self.client.chat.completions.create(
            model=model or self.default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def is_available(self) -> bool:
        """Check if OpenAI is available."""
        return bool(settings.openai_api_key)

    def supports_tools(self) -> bool:
        """OpenAI supports native tool calling."""
        return True

    def _format_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        """Format tools for OpenAI API.

        Args:
            tools: Tool definitions

        Returns:
            OpenAI-formatted tools
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]
