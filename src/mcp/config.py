from pathlib import Path
from typing import Literal
import os
import json
import re

from pydantic import BaseModel, Field, field_validator

class ServerConfig(BaseModel):
    id: str
    name: str
    transport: Literal["stdio", "http"]
    # For stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    # For http
    url: str | None = None
    description: str | None = None

    @field_validator("command")
    @classmethod
    def validate_command(cls, v, info):
        if info.data.get("transport") == "stdio" and not v:
            raise ValueError("Command is required for stdio transport")
        return v
    
    @field_validator("url")
    @classmethod
    def validate_url(cls, v, info):
        if info.data.get("transport") == "http" and not v:
            raise ValueError("URL is required for http transport")
        return v

class ToolTtlConfig(BaseModel):
    tools: list[str]
    ttl_seconds: int

class McpServerConfig(BaseModel):
    servers: list[ServerConfig]
    tool_ttl_overrides: dict[str, ToolTtlConfig] = Field(default_factory=dict)

def _expand_env_vars(value: str) -> str:
    """Expand environment variables in a string (e.g., ${VAR_NAME})."""
    if not value:
        return value
    
    pattern = re.compile(r'\$\{([^}]+)\}')
    
    def replace(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    
    return pattern.sub(replace, value)

def load_mcp_config(path: Path | str) -> McpServerConfig:
    """Load and validate MCP configuration from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
        
    with open(path, "r") as f:
        data = json.load(f)
    
    # Pre-process for env var expansion
    def recursive_expand(obj):
        if isinstance(obj, dict):
            return {k: recursive_expand(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [recursive_expand(v) for v in obj]
        elif isinstance(obj, str):
            return _expand_env_vars(obj)
        else:
            return obj
            
    expanded_data = recursive_expand(data)
    
    return McpServerConfig(**expanded_data)
