"""Configuration and tenancy management for MCP server.

Supports multiple OCI profiles/tenancies with automatic discovery
from ~/.oci/config file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import configparser


@dataclass
class TenancyProfile:
    """Represents an OCI tenancy profile configuration."""

    name: str
    config_file: str = "~/.oci/config"
    region: Optional[str] = None
    compartment_id: Optional[str] = None
    tenancy_id: Optional[str] = None
    user_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "region": self.region,
            "compartment_id": self.compartment_id,
            "tenancy_id": self.tenancy_id,
        }


class TenancyManager:
    """Manages multiple OCI tenancy profiles."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize tenancy manager.

        Args:
            config_file: Path to OCI config file. Defaults to ~/.oci/config
        """
        self.config_file = config_file or os.getenv(
            "OCI_CONFIG_FILE", os.path.expanduser("~/.oci/config")
        )
        self._profiles: Dict[str, TenancyProfile] = {}
        self._active_profile: Optional[str] = None
        self._loaded = False

    def discover_profiles(self) -> List[str]:
        """Discover available OCI profiles from config file.

        Returns:
            List of profile names
        """
        profiles = []
        config_path = Path(self.config_file).expanduser()

        if not config_path.exists():
            return profiles

        try:
            # Use RawConfigParser to avoid DEFAULT section being treated specially
            # and to preserve case sensitivity of profile names
            config = configparser.RawConfigParser()
            config.read(config_path)

            # Get all sections including DEFAULT
            # RawConfigParser.sections() still doesn't include DEFAULT,
            # so we need to check for it explicitly
            all_sections = config.sections()

            # Check if DEFAULT section exists by looking for its keys
            # in the raw file content
            with open(config_path, 'r') as f:
                content = f.read()
                if '[DEFAULT]' in content:
                    all_sections = ['DEFAULT'] + all_sections

            for section in all_sections:
                profiles.append(section)
                self._profiles[section] = TenancyProfile(
                    name=section,
                    config_file=str(config_path),
                    region=config.get(section, "region", fallback=None),
                    tenancy_id=config.get(section, "tenancy", fallback=None),
                    user_id=config.get(section, "user", fallback=None),
                )

            self._loaded = True
        except Exception as e:
            print(f"Error reading OCI config: {e}")

        return profiles

    def get_profile(self, name: str) -> Optional[TenancyProfile]:
        """Get a specific profile by name.

        Args:
            name: Profile name

        Returns:
            TenancyProfile or None
        """
        if not self._loaded:
            self.discover_profiles()
        return self._profiles.get(name)

    def list_profiles(self) -> List[Dict[str, Any]]:
        """List all available profiles.

        Returns:
            List of profile info dicts
        """
        if not self._loaded:
            self.discover_profiles()

        return [
            {
                "name": p.name,
                "region": p.region,
                "active": p.name == self._active_profile,
            }
            for p in self._profiles.values()
        ]

    def set_active_profile(self, name: str) -> bool:
        """Set the active profile for operations.

        Args:
            name: Profile name to activate

        Returns:
            True if successful
        """
        if not self._loaded:
            self.discover_profiles()

        if name in self._profiles:
            self._active_profile = name
            # Also set environment variable for OCI SDK
            os.environ["OCI_CLI_PROFILE"] = name
            return True
        return False

    def get_active_profile(self) -> Optional[TenancyProfile]:
        """Get the currently active profile.

        Returns:
            Active TenancyProfile or None
        """
        if self._active_profile:
            return self._profiles.get(self._active_profile)

        # Try to get from environment
        env_profile = os.getenv("OCI_CLI_PROFILE", "DEFAULT")
        if env_profile in self._profiles:
            self._active_profile = env_profile
            return self._profiles[env_profile]

        # Return first available
        if self._profiles:
            first = next(iter(self._profiles.values()))
            self._active_profile = first.name
            return first

        return None


# Global tenancy manager instance
_tenancy_manager: Optional[TenancyManager] = None


def get_tenancy_manager() -> TenancyManager:
    """Get the global tenancy manager instance."""
    global _tenancy_manager
    if _tenancy_manager is None:
        _tenancy_manager = TenancyManager()
        _tenancy_manager.discover_profiles()
    return _tenancy_manager
