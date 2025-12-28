"""LLM router routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import get_llm_router, get_provider_registry
from src.llm import LLMRouter, ProviderRegistry
from src.llm.router.router import TaskType
from src.observability import create_span

router = APIRouter(prefix="/llm", tags=["llm"])


class GenerateRequest(BaseModel):
    """LLM generation request."""

    messages: list[dict[str, Any]]
    provider: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    task_type: str | None = None


class GenerateResponse(BaseModel):
    """LLM generation response."""

    content: str
    model: str
    provider: str
    usage: dict[str, int]
    finish_reason: str


@router.get("/providers")
async def list_providers(
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
) -> dict[str, Any]:
    """List available LLM providers."""
    available = registry.list_available()
    return {
        "available": available,
        "primary": available[0] if available else None,
    }


@router.get("/providers/{name}")
async def get_provider_info(
    name: str,
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
) -> dict[str, Any]:
    """Get information about a specific provider."""
    provider = registry.get(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider not found: {name}")

    return {
        "name": provider.name,
        "available": provider.is_available(),
        "supports_tools": provider.supports_tools(),
    }


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    llm_router: Annotated[LLMRouter, Depends(get_llm_router)],
) -> GenerateResponse:
    """Generate a response using the LLM router."""
    with create_span(
        "api.llm.generate",
        component="api",
    ):
        try:
            # Parse task type if provided
            task_type = None
            if request.task_type:
                try:
                    task_type = TaskType(request.task_type)
                except ValueError:
                    pass

            # Extract query for classification
            query = ""
            for msg in reversed(request.messages):
                if msg.get("role") == "user":
                    query = msg.get("content", "")
                    break

            response = await llm_router.route(
                query=query,
                messages=request.messages,
                task_type=task_type,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            return GenerateResponse(
                content=response.content,
                model=response.model,
                provider=response.provider,
                usage=response.usage,
                finish_reason=response.finish_reason,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/routing-rules")
async def get_routing_rules(
    llm_router: Annotated[LLMRouter, Depends(get_llm_router)],
) -> dict[str, Any]:
    """Get current routing rules."""
    rules = {}
    for task_type in TaskType:
        rule = llm_router.get_rule(task_type)
        rules[task_type.value] = {
            "provider": rule.provider,
            "model": rule.model,
            "temperature": rule.temperature,
            "max_tokens": rule.max_tokens,
        }
    return {"rules": rules}


@router.post("/classify")
async def classify_query(
    query: str,
    llm_router: Annotated[LLMRouter, Depends(get_llm_router)],
) -> dict[str, Any]:
    """Classify a query to determine task type."""
    task_type = llm_router.classify_task(query)
    rule = llm_router.get_rule(task_type)
    return {
        "query": query,
        "task_type": task_type.value,
        "routing": {
            "provider": rule.provider,
            "model": rule.model,
            "temperature": rule.temperature,
        },
    }
