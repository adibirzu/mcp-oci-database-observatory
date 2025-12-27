import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from src.mcp.config import McpServerConfig, load_mcp_config

@pytest.fixture
def mock_config_file(tmp_path):
    config_data = {
        "servers": [
            {
                "id": "test-stdio",
                "name": "Test Stdio Server",
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "mcp_server"],
                "description": "A test server"
            },
            {
                "id": "test-http",
                "name": "Test HTTP Server",
                "transport": "http",
                "url": "http://localhost:8080/mcp",
                "description": "A test http server"
            },
            {
                "id": "test-env-var",
                "name": "Test Env Var",
                "transport": "stdio",
                "command": "${TEST_CMD_PATH}",
                "args": ["${TEST_ARG}"],
                "description": "Testing env var expansion"
            }
        ],
        "tool_ttl_overrides": {
            "static": {
                "tools": ["list_stuff"],
                "ttl_seconds": 3600
            }
        }
    }
    
    config_file = tmp_path / "mcp-servers.json"
    with open(config_file, "w") as f:
        json.dump(config_data, f)
    return config_file

def test_load_mcp_config_success(mock_config_file):
    """Test loading a valid configuration file."""
    with patch.dict(os.environ, {"TEST_CMD_PATH": "/usr/bin/test", "TEST_ARG": "--flag"}):
        config = load_mcp_config(mock_config_file)
        
        assert isinstance(config, McpServerConfig)
        assert len(config.servers) == 3
        
        # Check Stdio server
        stdio_server = next(s for s in config.servers if s.id == "test-stdio")
        assert stdio_server.transport == "stdio"
        assert stdio_server.command == "python"
        assert stdio_server.args == ["-m", "mcp_server"]
        
        # Check HTTP server
        http_server = next(s for s in config.servers if s.id == "test-http")
        assert http_server.transport == "http"
        assert str(http_server.url) == "http://localhost:8080/mcp"

        # Check Env Var Expansion
        env_server = next(s for s in config.servers if s.id == "test-env-var")
        assert env_server.command == "/usr/bin/test"
        assert env_server.args == ["--flag"]

def test_load_mcp_config_file_not_found():
    """Test loading a non-existent configuration file."""
    with pytest.raises(FileNotFoundError):
        load_mcp_config(Path("non_existent_file.json"))

def test_load_mcp_config_invalid_json(tmp_path):
    """Test loading a file with invalid JSON."""
    bad_file = tmp_path / "bad.json"
    with open(bad_file, "w") as f:
        f.write("{invalid_json")
    
    with pytest.raises(json.JSONDecodeError):
        load_mcp_config(bad_file)
