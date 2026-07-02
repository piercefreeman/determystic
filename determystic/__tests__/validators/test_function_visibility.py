"""Tests for function visibility validator functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.compat import tomllib
from determystic.configs.project import ProjectConfigManager
from determystic.validators.function_visibility import FunctionVisibilityValidator


class TestFunctionVisibilityValidator:
    """Test suite for FunctionVisibilityValidator."""

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

        validators = FunctionVisibilityValidator.create_validators(config_manager)

        assert len(validators) == 1
        assert isinstance(validators[0], FunctionVisibilityValidator)
        assert validators[0].name == "function_visibility"

    @pytest.mark.asyncio
    async def test_validate_passes_when_public_function_precedes_private_helper(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Externally used functions may call underscored helpers below them."""
        (temp_project_dir / "service.py").write_text("""
def public_api():
    return _helper()


def _helper():
    return "ok"
""")
        (temp_project_dir / "consumer.py").write_text("""
from service import public_api

value = public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert result.output == "No function visibility issues found"

    @pytest.mark.asyncio
    async def test_validate_flags_internal_module_helper_without_underscore_and_before_public(
        self,
        temp_project_dir: Path,
    ) -> None:
        """A helper used only in its file must be underscored and below public functions."""
        (temp_project_dir / "service.py").write_text("""
def helper():
    return "ok"


def public_api():
    return helper()
""")
        (temp_project_dir / "consumer.py").write_text("""
from service import public_api

value = public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "Function 'helper' is only used within this file" in result.output
        assert "prefix it with '_'" in result.output
        assert "Public function 'public_api' should be defined before" in result.output

    @pytest.mark.asyncio
    async def test_validate_resolves_module_import_aliases(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Module aliases should mark imported functions as externally used."""
        (temp_project_dir / "service.py").write_text("""
def public_api():
    return _helper()


def _helper():
    return "ok"
""")
        (temp_project_dir / "consumer.py").write_text("""
import service as svc

value = svc.public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_resolves_relative_imports(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Relative imports should participate in external reference tracking."""
        package_dir = temp_project_dir / "pkg"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("")
        (package_dir / "service.py").write_text("""
def public_api():
    return _helper()


def _helper():
    return "ok"
""")
        (package_dir / "consumer.py").write_text("""
from .service import public_api

value = public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_resolves_package_root_imports_under_service_directory(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Monorepo service packages are often imported from their package root."""
        service_package = (
            temp_project_dir / "services" / "worker-service" / "control_plane_service"
        )
        service_package.mkdir(parents=True)
        (service_package / "__init__.py").write_text("")
        (service_package / "redaction.py").write_text("""
def redact_text(value):
    return value
""")
        (service_package / "runtime.py").write_text("""
from control_plane_service.redaction import redact_text as _redact_text

value = _redact_text("secret")
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success, result.output

    @pytest.mark.asyncio
    async def test_validate_uses_ignored_files_and_plugin_attributes_as_references(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Ignored runtime files can still reference plugin methods via registries."""
        package_dir = temp_project_dir / "app"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("")
        (package_dir / "plugins.py").write_text("""
from dataclasses import dataclass, field

from app.tracing import TracePlugin

@dataclass
class RuntimePlugins:
    tracing: TracePlugin = field(default_factory=TracePlugin)
""")
        (package_dir / "tracing.py").write_text("""
class TracePlugin:
    def create_context_trace(self):
        return "trace"
""")
        (package_dir / "runtime.py").write_text("""
from app.plugins import RuntimePlugins

class Runtime:
    def __init__(self):
        self.plugins = RuntimePlugins()

    def create(self):
        return self.plugins.tracing.create_context_trace()
""")

        validator = FunctionVisibilityValidator(
            path=temp_project_dir,
            ignore_paths=["app/runtime.py"],
        )
        result = await validator.validate()

        assert result.success, result.output

    @pytest.mark.asyncio
    async def test_validate_treats_unresolved_attribute_calls_as_external_methods(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Composition through untyped writer attributes should not force private names."""
        (temp_project_dir / "writer.py").write_text("""
class TraceWriter:
    def record(self, event):
        return event
""")
        (temp_project_dir / "actions.py").write_text("""
class ActionRecorder:
    def __init__(self, writer):
        self._writer = writer

    def action_started(self):
        return self._writer.record("started")
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success, result.output

    @pytest.mark.asyncio
    async def test_validate_flags_internal_class_method_without_underscore_and_before_public(
        self,
        temp_project_dir: Path,
    ) -> None:
        """A method used only through self should be underscored and below public methods."""
        (temp_project_dir / "service.py").write_text("""
class Worker:
    def helper(self):
        return "ok"

    def run(self):
        return self.helper()
""")
        (temp_project_dir / "consumer.py").write_text("""
from service import Worker

result = Worker().run()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "Method 'Worker.helper' is only used within its class" in result.output
        assert "Public method 'Worker.run' should be defined before" in result.output

    @pytest.mark.asyncio
    async def test_validate_treats_same_file_method_call_outside_class_as_public(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Calling a method from outside its class makes it public even in the same file."""
        (temp_project_dir / "service.py").write_text("""
class Worker:
    def run(self):
        return "ok"


worker = Worker()
result = worker.run()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success

    @pytest.mark.asyncio
    async def test_validate_ignores_test_files(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test files should not influence or fail visibility validation."""
        (temp_project_dir / "test_service.py").write_text("""
def helper():
    return "ok"


def public_api():
    return helper()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert result.output == "No Python files found"

    @pytest.mark.asyncio
    async def test_validate_respects_configured_ignore_paths(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Configured ignore paths exclude Python files from visibility analysis."""
        generated_dir = temp_project_dir / "generated"
        generated_dir.mkdir()
        (generated_dir / "service.py").write_text("""
def helper():
    return "ok"


def public_api():
    return helper()
""")

        validator = FunctionVisibilityValidator(
            path=temp_project_dir,
            ignore_paths=["generated/"],
        )
        result = await validator.validate()

        assert result.success
        assert result.output == "No Python files found"

    # determystic: tested-exceptions[determystic.validators.function_visibility.FunctionVisibilityValidator._build_project_index: SyntaxError, UnicodeDecodeError]
    def test_build_project_index_skips_unparseable_files(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Project indexing skips files that cannot be parsed as Python."""
        bad_syntax_file = temp_project_dir / "bad_syntax.py"
        bad_syntax_file.write_text("def broken(:\n")
        bad_unicode_file = temp_project_dir / "bad_unicode.py"
        bad_unicode_file.write_bytes(b"\xff")
        good_file = temp_project_dir / "service.py"
        good_file.write_text("""
def public_api():
    return "ok"
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        index = validator._build_project_index(
            [bad_syntax_file, bad_unicode_file, good_file]
        )

        assert list(index.modules_by_path) == ["service.py"]

    # determystic: tested-exceptions[determystic.validators.function_visibility.FunctionVisibilityValidator._get_script_entrypoints: TOMLDecodeError, KeyError, ValueError]
    def test_get_script_entrypoints_handles_pyproject_parse_errors(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Malformed entrypoint configuration is treated as no entrypoints."""
        pyproject_file = temp_project_dir / "pyproject.toml"
        pyproject_file.write_text("[project]\n")
        validator = FunctionVisibilityValidator(path=temp_project_dir)

        parse_errors = [
            tomllib.TOMLDecodeError("bad toml", "bad", 0),
            KeyError("scripts"),
            ValueError("bad script"),
        ]
        for parse_error in parse_errors:
            with patch(
                "determystic.validators.function_visibility.tomllib.load",
                side_effect=parse_error,
            ):
                assert validator._get_script_entrypoints(temp_project_dir) == set()

    @pytest.mark.asyncio
    async def test_validate_respects_function_visibility_suppression_block(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Function visibility findings can be suppressed with shared comments."""
        (temp_project_dir / "service.py").write_text("""
# determystic: ignore-start[function-visibility]
def helper():
    return "ok"


def public_api():
    return helper()
# determystic: ignore-end[function-visibility]
""")
        (temp_project_dir / "consumer.py").write_text("""
from service import public_api

value = public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert result.output == "No function visibility issues found"

    @pytest.mark.asyncio
    async def test_validate_respects_specific_function_visibility_suppressions(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Specific suppression codes can target naming or ordering separately."""
        (temp_project_dir / "service.py").write_text("""
def helper():  # determystic: ignore[private-prefix]
    return "ok"


# determystic: ignore[function-order]
def public_api():
    return helper()
""")
        (temp_project_dir / "consumer.py").write_text("""
from service import public_api

value = public_api()
""")

        validator = FunctionVisibilityValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert result.output == "No function visibility issues found"

    def test_display_name_property(self, temp_project_dir: Path) -> None:
        """Test display name formatting."""
        validator = FunctionVisibilityValidator(path=temp_project_dir)

        assert validator.display_name == "Function Visibility"
