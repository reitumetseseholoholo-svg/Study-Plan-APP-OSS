from dataclasses import dataclass
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SchemaMigration:
    """Describes a schema version migration."""
    from_version: int
    to_version: int
    description: str

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply migration logic."""
        logger.info(f"applying migration {self.from_version} -> {self.to_version}")
        # Migration logic here
        return payload


class MigrationRegistry:
    """Centralized schema version migrations."""

    _migrations = {
        (1, 2): SchemaMigration(
            from_version=1,
            to_version=2,
            description="add recovery_mode and recovery_hints to CognitiveState",
        ),
    }

    @classmethod
    def migrate(cls, payload: dict[str, Any], from_version: int, to_version: int) -> dict[str, Any]:
        """Apply sequential migrations from one version to another."""
        current = from_version
        while current < to_version:
            next_version = current + 1
            key = (current, next_version)
            if key not in cls._migrations:
                raise ValueError(f"no migration path {current} -> {next_version}")
            migration = cls._migrations[key]
            payload = migration.apply(payload)
            current = next_version
        return payload

    @classmethod
    def can_migrate(cls, from_version: int, to_version: int) -> bool:
        """Check if migration path exists."""
        current = from_version
        while current < to_version:
            next_version = current + 1
            if (current, next_version) not in cls._migrations:
                return False
            current = next_version
        return True


def ensure_schema_version(payload: dict[str, Any], target_version: int = 1) -> dict[str, Any]:
    """Ensure payload is at target schema version, migrating if needed."""
    current_version = payload.get("schema_version", 1)
    if current_version == target_version:
        return payload
    if current_version > target_version:
        logger.warning(f"payload version {current_version} > target {target_version}")
        return payload
    migrated = MigrationRegistry.migrate(payload, current_version, target_version)
    migrated["schema_version"] = target_version
    logger.info(f"migrated schema {current_version} -> {target_version}")
    return migrated
