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
    async def test_validate_infers_function_coverage_from_test_exception_evidence(
        self,
        temp_project_dir: Path,
    ) -> None:
        """A test call plus local exception evidence can satisfy coverage."""
        (temp_project_dir / "service.py").write_text("""
def load_config(reader):
    try:
        return reader()
    except FileNotFoundError:
        return {}
""")
        (temp_project_dir / "test_service.py").write_text("""
from service import load_config


def test_load_config_handles_missing_file():
    def missing_file():
        raise FileNotFoundError("missing")

    assert load_config(missing_file) == {}
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_infers_coverage_from_exception_constructor_evidence(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Exception instances passed through test helpers count as evidence."""
        (temp_project_dir / "service.py").write_text("""
def request_status(fetcher):
    try:
        return fetcher()
    except RuntimeError:
        return "unavailable"
""")
        (temp_project_dir / "test_service.py").write_text("""
from service import request_status


def test_request_status_handles_runtime_error():
    error = RuntimeError("broker unavailable")

    def fetcher():
        raise error

    assert request_status(fetcher) == "unavailable"
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_infers_method_coverage_from_instance_call(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Instance method calls can cover broad exception handlers."""
        (temp_project_dir / "worker.py").write_text("""
class Worker:
    def run(self, callback):
        try:
            callback()
        except Exception:
            return "failed"
        return "ok"
""")
        (temp_project_dir / "test_worker.py").write_text("""
from worker import Worker


def test_worker_handles_runtime_error():
    def fail():
        raise RuntimeError("boom")

    worker = Worker()
    assert worker.run(fail) == "failed"
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_infers_package_root_module_alias_coverage(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Service-dir imports can cover monorepo-root requirement targets."""
        service_dir = (
            temp_project_dir
            / "services"
            / "worker-service"
            / "control_plane_service"
        )
        test_dir = service_dir / "__tests__"
        test_dir.mkdir(parents=True)
        (service_dir / "__init__.py").write_text("")
        (service_dir / "payloads.py").write_text("""
def body_payload(data):
    try:
        return {"text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"binary": True}
""")
        (test_dir / "test_payloads.py").write_text("""
import pytest
from control_plane_service import payloads as payloads_module


def test_body_payload_handles_binary_body():
    with pytest.raises(UnicodeDecodeError):
        b"\\xff".decode("utf-8")

    assert payloads_module.body_payload(b"\\xff") == {"binary": True}
""")

        validator = ExceptionCoverageValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

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
        assert (
            "FileNotFoundError' in service.load_config is not marked"
            not in result.output
        )

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
        assert (
            "no production function with except handlers matches that name"
            in result.output
        )

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

    @pytest.mark.asyncio
    async def test_validate_respects_configured_ignore_paths(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Configured ignore paths exclude production and test files."""
        generated_dir = temp_project_dir / "generated"
        generated_dir.mkdir()
        (generated_dir / "service.py").write_text("""
def load_config():
    try:
        return read_config()
    except FileNotFoundError:
        return {}
""")

        validator = ExceptionCoverageValidator(
            path=temp_project_dir,
            ignore_paths=["generated/"],
        )
        result = await validator.validate()

        assert result.success
        assert result.output == "All except handlers are marked as tested"

    @pytest.mark.asyncio
    async def test_validate_uses_ignored_tests_as_coverage_sources(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Ignored test files can prove production exception coverage."""
        ignored_tests_dir = temp_project_dir / "ignored_tests"
        ignored_tests_dir.mkdir()
        (temp_project_dir / "service.py").write_text("""
def parse_int(value):
    try:
        return int(value)
    except ValueError:
        return 0
""")
        (ignored_tests_dir / "test_service.py").write_text("""
import pytest
from service import parse_int


def test_parse_int_handles_invalid_value():
    with pytest.raises(ValueError):
        int("bad")

    assert parse_int("bad") == 0
""")

        validator = ExceptionCoverageValidator(
            path=temp_project_dir,
            ignore_paths=["ignored_tests/"],
        )
        result = await validator.validate()

        assert result.success

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
