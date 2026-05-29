"""Tests for function visibility validator functionality."""

import tempfile
from pathlib import Path

import pytest

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
