"""Oracle Code Assist (OCA) LLM provider with SSO."""

import asyncio
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any, AsyncIterator

import aiohttp

from src.core import get_logger, settings
from src.observability import create_span

from .base import LLMProvider, LLMResponse, ToolDefinition

logger = get_logger("llm.oca")


class OCAAuth:
    """Oracle Code Assist PKCE OAuth handler."""

    TOKEN_CACHE_FILE = Path.home() / ".oca_token_cache.json"

    def __init__(self) -> None:
        """Initialize OCA auth."""
        self.idcs_url = settings.oca_idcs_url
        self.client_id = settings.oca_client_id
        self.redirect_uri = settings.oca_redirect_uri or "http://localhost:3001/api/oca/callback"
        self._token: dict | None = None
        self._load_cached_token()

    def _load_cached_token(self) -> None:
        """Load token from cache file."""
        if self.TOKEN_CACHE_FILE.exists():
            try:
                with open(self.TOKEN_CACHE_FILE) as f:
                    self._token = json.load(f)
                    # Check if expired
                    if self._is_token_expired():
                        self._token = None
            except Exception as e:
                logger.warning("Failed to load token cache", error=str(e))

    def _save_token(self, token: dict) -> None:
        """Save token to cache file."""
        self._token = token
        try:
            with open(self.TOKEN_CACHE_FILE, "w") as f:
                json.dump(token, f)
            os.chmod(self.TOKEN_CACHE_FILE, 0o600)
        except Exception as e:
            logger.warning("Failed to save token cache", error=str(e))

    def _is_token_expired(self) -> bool:
        """Check if current token is expired."""
        if not self._token:
            return True
        expires_at = self._token.get("expires_at", 0)
        return time.time() >= expires_at - 300  # 5 min buffer

    def generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge.

        Returns:
            Tuple of (verifier, challenge)
        """
        verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    def get_auth_url(self, state: str, code_challenge: str) -> str:
        """Get OAuth authorization URL.

        Args:
            state: CSRF state token
            code_challenge: PKCE challenge

        Returns:
            Authorization URL
        """
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid offline_access",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.idcs_url}/oauth2/v1/authorize?{urllib.parse.urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> dict:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code
            code_verifier: PKCE verifier

        Returns:
            Token response
        """
        async with aiohttp.ClientSession() as session:
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": code_verifier,
            }
            async with session.post(
                f"{self.idcs_url}/oauth2/v1/token",
                data=data,
            ) as resp:
                token = await resp.json()
                token["expires_at"] = time.time() + token.get("expires_in", 3600)
                self._save_token(token)
                return token

    async def refresh_token(self) -> dict | None:
        """Refresh the access token.

        Returns:
            New token or None
        """
        if not self._token or "refresh_token" not in self._token:
            return None

        async with aiohttp.ClientSession() as session:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self.client_id,
            }
            async with session.post(
                f"{self.idcs_url}/oauth2/v1/token",
                data=data,
            ) as resp:
                if resp.status == 200:
                    token = await resp.json()
                    token["expires_at"] = time.time() + token.get("expires_in", 3600)
                    self._save_token(token)
                    return token
                return None

    async def get_valid_token(self) -> str | None:
        """Get a valid access token, refreshing if needed.

        Returns:
            Access token or None
        """
        if self._is_token_expired():
            await self.refresh_token()

        if self._token and "access_token" in self._token:
            return self._token["access_token"]
        return None

    def start_browser_auth(self) -> tuple[str, str]:
        """Start browser-based authentication.

        Returns:
            Tuple of (state, verifier) for callback handling
        """
        state = secrets.token_urlsafe(32)
        verifier, challenge = self.generate_pkce()
        auth_url = self.get_auth_url(state, challenge)
        webbrowser.open(auth_url)
        return state, verifier


class OCAProvider(LLMProvider):
    """Oracle Code Assist LLM provider."""

    provider_name = "oracle_code_assist"

    def __init__(self) -> None:
        """Initialize OCA provider."""
        self.auth = OCAAuth()
        self.base_url = settings.oca_api_url
        self.default_model = settings.oca_default_model or "oci.generativeai.cohere.command-r-plus"

    async def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response using OCA.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            tools: Tool definitions (ReAct format)
            **kwargs: Additional options

        Returns:
            LLM response
        """
        with create_span(
            "llm.oca.generate",
            component="llm_provider",
            attributes={"model": model or self.default_model},
        ):
            token = await self.auth.get_valid_token()
            if not token:
                raise RuntimeError("OCA authentication required")

            # Build request
            payload = {
                "model": model or self.default_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # Add tools in ReAct format if provided
            if tools:
                payload["tools"] = self._format_tools_react(tools)

            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                async with session.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        raise RuntimeError(f"OCA error: {error}")

                    data = await resp.json()
                    choice = data.get("choices", [{}])[0]
                    message = choice.get("message", {})

                    return LLMResponse(
                        content=message.get("content", ""),
                        model=data.get("model", model or self.default_model),
                        provider=self.provider_name,
                        usage=data.get("usage", {}),
                        tool_calls=message.get("tool_calls", []),
                        finish_reason=choice.get("finish_reason", "stop"),
                        raw_response=data,
                    )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response from OCA.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional options

        Yields:
            Response chunks
        """
        token = await self.auth.get_valid_token()
        if not token:
            raise RuntimeError("OCA authentication required")

        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            async with session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                async for line in resp.content:
                    line = line.decode().strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    def is_available(self) -> bool:
        """Check if OCA is available."""
        return bool(
            settings.oca_idcs_url
            and settings.oca_client_id
            and settings.oca_api_url
        )

    def supports_tools(self) -> bool:
        """OCA uses ReAct format for tools."""
        return False  # Native tool calling not supported

    def _format_tools_react(self, tools: list[ToolDefinition]) -> str:
        """Format tools as ReAct-style prompt injection.

        Args:
            tools: Tool definitions

        Returns:
            ReAct format tools string
        """
        tool_descriptions = []
        for tool in tools:
            params = ", ".join(tool.parameters.get("required", []))
            tool_descriptions.append(
                f"- {tool.name}({params}): {tool.description}"
            )
        return "\n".join(tool_descriptions)
