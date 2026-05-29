"""Tests for exception coverage validator functionality."""

import tempfile
import tokenize
from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.configs.project import ProjectConfigManager
from determystic.validators.exception_coverage import (
    ExceptionCoverageValidator,
    _parse_test_markers,
)


class TestExceptionCoverageValidator:
    """Test suite for ExceptionCoverageValidator."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    def test_create_validators(self, temp_project_dir: Path) -> None:
        """Test create_validators factory method."""
        config_path = temp_project_dir / "pyproject.toml"
        config_path.write_text("""
[tool.determystic]
version = "1.0"
""")

        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        config_manager = ProjectConfigManager.load_from_disk()

        validators = ExceptionCoverageValidator.create_validators(config_manager)

        assert len(validators) == 1
        assert isinstance(validators[0], ExceptionCoverageValidator)
        assert validators[0].name == "exception_coverage"

    @pytest.mark.asyncio
    async def test_validate_passes_when_except_handler_has_test_marker(
        self,
        temp_project_dir: Path,
    ) -> None:
        """A matching test marker satisfies a production except handler."""
        (temp_project_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except FileNotFoundError:
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
# determystic: tested-exceptions[service.load_config: FileNotFoundError]
def test_load_config_handles_missing_file():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert result.output == "All except handlers are marked as tested"

    @pytest.mark.asyncio
    async def test_validate_flags_missing_test_marker(
        self,
        temp_project_dir: Path,
    ) -> None:
        """An unmarked production except handler is reported."""
        (temp_project_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except FileNotFoundError:
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
def test_load_config_handles_missing_file():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "service.py:5:" in result.output
        assert "service.load_config" in result.output
        assert "FileNotFoundError" in result.output

    @pytest.mark.asyncio
    async def test_validate_requires_each_exception_in_tuple_handler(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Tuple handlers require coverage markers for each listed exception."""
        (temp_project_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except (FileNotFoundError, ValueError):
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
# determystic: tested-exceptions[service.load_config: FileNotFoundError]
def test_load_config_handles_missing_file():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "ValueError" in result.output
        assert "FileNotFoundError' in service.load_config is not marked" not in result.output

    @pytest.mark.asyncio
    async def test_validate_accepts_marker_above_decorator(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Markers can sit above decorators attached to the test function."""
        (temp_project_dir / "service.py").write_text("""
async def fetch():
    try:
        return await request()
    except TimeoutError:
        return None
""")
        (temp_project_dir / "test_service.py").write_text("""
import pytest

# determystic: tested-exceptions[service.fetch: TimeoutError]
@pytest.mark.asyncio
async def test_fetch_handles_timeout():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_flags_stale_test_markers(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Markers must target an existing except handler."""
        (temp_project_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except FileNotFoundError:
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
# determystic: tested-exceptions[service.load_config: KeyError; service.missing: ValueError]
def test_load_config_handles_missing_file():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "does not catch that exception" in result.output
        assert "no production function with except handlers matches that name" in result.output

    @pytest.mark.asyncio
    async def test_validate_requires_marker_above_test_function(
        self,
        temp_project_dir: Path,
    ) -> None:
        """A marker separated from the test function is not counted."""
        (temp_project_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except FileNotFoundError:
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
# determystic: tested-exceptions[service.load_config: FileNotFoundError]

def test_load_config_handles_missing_file():
    assert True
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "must be immediately above a test function" in result.output

    # determystic: tested-exceptions[determystic.validators.exception_coverage.ExceptionCoverageValidator._parse_python_file: SyntaxError, UnicodeDecodeError]
    def test_parse_python_file_skips_unparseable_files(self, tmp_path: Path) -> None:
        """The validator skips files it cannot parse as Python source."""
        syntax_error_file = tmp_path / "bad.py"
        syntax_error_file.write_text("def broken(:\n")
        unicode_error_file = tmp_path / "not_utf8.py"
        unicode_error_file.write_bytes(b"\xff")

        validator = ExceptionCoverageValidator(path=tmp_path)

        assert validator._parse_python_file(syntax_error_file) is None
        assert validator._parse_python_file(unicode_error_file) is None


# determystic: tested-exceptions[determystic.validators.exception_coverage._parse_test_markers: TokenError]
def test_parse_test_markers_handles_tokenize_errors() -> None:
    """Tokenization failures are reported as marker parse issues."""
    with patch(
        "determystic.validators.exception_coverage.tokenize.generate_tokens",
        side_effect=tokenize.TokenError("bad token", (1, 1)),
    ):
        markers = _parse_test_markers("def test_example():\n    pass\n")

    assert len(markers) == 1
    assert markers[0].error is not None
    assert "tokenization failed" in markers[0].error
