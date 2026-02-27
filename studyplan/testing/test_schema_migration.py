import pytest

from studyplan.schema_migration import MigrationRegistry, ensure_schema_version


def test_migration_path_exists():
    """Test checking if a migration path is available."""
    assert MigrationRegistry.can_migrate(1, 2)
    assert not MigrationRegistry.can_migrate(1, 5)


def test_migration_apply():
    """Test applying a migration."""
    payload = {"schema_version": 1, "data": {}}
    result = MigrationRegistry.migrate(payload, 1, 2)
    assert "data" in result


def test_ensure_schema_version_no_upgrade_needed():
    """Test that no migration is applied when version matches."""
    payload = {"schema_version": 1, "data": {}}
    result = ensure_schema_version(payload, target_version=1)
    assert result["schema_version"] == 1


def test_ensure_schema_version_with_upgrade():
    """Test upgrading schema version."""
    payload = {"data": {}}
    result = ensure_schema_version(payload, target_version=2)
    assert result["schema_version"] == 2
