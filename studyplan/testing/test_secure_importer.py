import pytest
import tempfile
import json
from pathlib import Path

from studyplan.secure_importer import SecureImporter, ImportSecurityError
from studyplan.config import Config


def test_secure_import_valid_json(tmp_path):
    """Test loading a valid JSON from whitelisted directory."""
    # Temporarily modify config to allow tmp_path
    original_dirs = Config.SECURE_IMPORT_ALLOWED_DIRS
    Config.SECURE_IMPORT_ALLOWED_DIRS = [str(tmp_path)]

    test_file = tmp_path / "test.json"
    test_data = {"key": "value"}
    test_file.write_text(json.dumps(test_data))

    result = SecureImporter.validate_and_load(str(test_file))
    assert result == test_data

    Config.SECURE_IMPORT_ALLOWED_DIRS = original_dirs


def test_secure_import_disallowed_extension(tmp_path):
    """Test rejection of disallowed file extensions."""
    original_dirs = Config.SECURE_IMPORT_ALLOWED_DIRS
    Config.SECURE_IMPORT_ALLOWED_DIRS = [str(tmp_path)]

    test_file = tmp_path / "test.txt"
    test_file.write_text("not json")

    with pytest.raises(ImportSecurityError, match="extension"):
        SecureImporter.validate_and_load(str(test_file))

    Config.SECURE_IMPORT_ALLOWED_DIRS = original_dirs


def test_secure_import_disallowed_path(tmp_path):
    """Test rejection of paths outside whitelist."""
    test_file = tmp_path / "test.json"
    test_file.write_text(json.dumps({"key": "value"}))

    with pytest.raises(ImportSecurityError, match="whitelist"):
        SecureImporter.validate_and_load(str(test_file))
