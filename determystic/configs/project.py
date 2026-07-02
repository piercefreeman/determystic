"""Project configuration management for determystic validators."""

from determystic.compat import tomllib
from typing import Any, ClassVar, Literal, TypeVar
from pathlib import Path

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from determystic.configs.base import BaseConfig
from determystic.io import detect_git_root, detect_pyproject_path

ValidatorAgentPreference = Literal["auto", "codex", "claude"]
ConfigModelT = TypeVar("ConfigModelT", bound=BaseModel)
VALIDATOR_METADATA_FIELDS = {
    "name",
    "validator_path",
    "test_path",
    "created_at",
    "description",
    "config",
}


class ValidatorFile(BaseModel):
    """Represents a validator file in the project."""
    name: str = Field(description="Name of the validator file (without extension)")
    validator_path: str = Field(description="Relative path to the validator file")
    test_path: str | None = Field(default=None, description="Relative path to the test file")
    description: str | None = Field(default=None, description="Description of what this validator checks")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Validator-specific configuration payload.",
    )


class ProjectSettings(BaseModel):
    """Project-specific settings stored under [tool.determystic.settings]."""

    validator_agent: ValidatorAgentPreference = Field(
        default="auto",
        description="Local coding agent used to generate validators: auto, codex, or claude",
    )

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def migrate_agent_alias(cls, data: Any) -> Any:
        """Accept legacy `agent` config while persisting the documented key."""
        if not isinstance(data, dict):
            return data

        values = dict(data)
        if "validator_agent" not in values and "agent" in values:
            values["validator_agent"] = values.pop("agent")
        return values

    @field_validator("validator_agent", mode="before")
    @classmethod
    def normalize_validator_agent(cls, value: Any) -> Any:
        """Normalize the configured local agent preference before Literal validation."""
        if value is None or value == "":
            return "auto"
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ProjectConfigManager(BaseConfig):
    """Configuration for a determystic project stored in pyproject.toml."""

    TOOL_SECTION: ClassVar[str] = "determystic"
    _config_path: Path | None = PrivateAttr(default=None)
    _project_root: Path | None = PrivateAttr(default=None)
    _isolation_paths: list[str] = PrivateAttr(default_factory=list)
    
    version: str = Field(default="1.0", description="Configuration version")
    project_name: str | None = Field(default=None, description="Name of the project")

    exclude: list[str] = Field(default_factory=list, description="List of validators to exclude from validation")
    enabled: list[str] = Field(
        default_factory=list,
        description="List of bundled validators to enable. Custom validators are enabled by default.",
    )
    ignore_paths: list[str] = Field(
        default_factory=list,
        description="Project-relative files, directories, or glob patterns to ignore during validation.",
    )
    
    # Validator files tracking
    validators: dict[str, ValidatorFile] = Field(
        default_factory=dict,
        description="Map of validator names to their file information"
    )
    validator_configs: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        exclude=True,
        description="Internal map of validator names to typed configuration payloads.",
    )
    
    # Project settings
    settings: ProjectSettings = Field(
        default_factory=ProjectSettings,
        description="Project-specific settings"
    )

    runtime_custom_path: ClassVar[Path | None] = None

    @model_validator(mode="before")
    @classmethod
    def migrate_project_config(cls, data: Any) -> Any:
        """Normalize project config aliases and split validator metadata from config."""
        if not isinstance(data, dict):
            return data

        values = dict(data)
        if "ignore_paths" not in values and "ignored_paths" in values:
            values["ignore_paths"] = values.pop("ignored_paths")
        values = cls._split_validator_config_sections(values)
        return values

    @staticmethod
    def _split_validator_config_sections(values: dict[str, Any]) -> dict[str, Any]:
        raw_validators = values.get("validators")
        if not isinstance(raw_validators, dict):
            return values

        custom_validators: dict[str, Any] = {}
        validator_configs = dict(values.get("validator_configs", {}))

        for validator_name, raw_entry in raw_validators.items():
            if not isinstance(raw_entry, dict):
                custom_validators[validator_name] = raw_entry
                continue

            entry = dict(raw_entry)
            nested_config = entry.get("config", {})
            if not isinstance(nested_config, dict):
                nested_config = {}

            direct_config = {
                key: value
                for key, value in entry.items()
                if key not in VALIDATOR_METADATA_FIELDS
            }
            combined_config = {**direct_config, **nested_config}
            if combined_config:
                validator_configs[validator_name] = combined_config

            if "validator_path" not in entry:
                continue

            custom_validators[validator_name] = {
                key: value
                for key, value in entry.items()
                if key in VALIDATOR_METADATA_FIELDS
            }
            custom_validators[validator_name].setdefault("name", validator_name)
            if combined_config:
                custom_validators[validator_name]["config"] = combined_config

        values["validators"] = custom_validators
        values["validator_configs"] = validator_configs
        return values

    @classmethod
    def set_runtime_custom_path(cls, path: Path) -> None:
        """
        Set by the CLI layer to allow for custom paths to be set at runtime.

        """
        path = path.absolute()
        cls.runtime_custom_path = detect_pyproject_path(path) or path
        cls._found_path = None

    @classmethod
    def get_possible_config_paths(cls):
        """
        Get the custom path set by the CLI layer.
        """
        if cls.runtime_custom_path is not None:
            return [cls.runtime_custom_path / "pyproject.toml"]

        pyproject_root = detect_pyproject_path(Path.cwd())
        if pyproject_root:
            return [pyproject_root / "pyproject.toml"]

        git_root = detect_git_root(Path.cwd())
        if git_root:
            return [git_root / "pyproject.toml"]

        return [Path.cwd() / "pyproject.toml"]

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the project pyproject.toml path."""
        if cls._found_path is None:
            possible_paths = cls.get_possible_config_paths()
            for path in possible_paths:
                if path.exists():
                    cls._found_path = path
                    break
            else:
                cls._found_path = possible_paths[0]
        return cls._found_path

    @classmethod
    def load_from_disk(cls) -> "ProjectConfigManager":
        """Load determystic configuration from [tool.determystic]."""
        config_path = cls.get_config_path()
        return cls.load_from_config_path(config_path)

    @classmethod
    def load_from_config_path(
        cls,
        config_path: Path,
        *,
        project_root: Path | None = None,
        extra_ignore_paths: list[str] | tuple[str, ...] | None = None,
    ) -> "ProjectConfigManager":
        """Load determystic configuration from an explicit pyproject path."""
        config_path = config_path.resolve()
        config_data: dict[str, Any] = {}

        if config_path.exists():
            with config_path.open("rb") as f:
                pyproject_data = tomllib.load(f)
            tool_data = pyproject_data.get("tool", {})
            config_data = tool_data.get(cls.TOOL_SECTION, {})

        config = cls.model_validate(config_data)
        config._config_path = config_path
        config._project_root = (
            project_root.resolve()
            if project_root is not None
            else config_path.parent
        )
        if extra_ignore_paths:
            config._isolation_paths = [
                ignore_path
                for ignore_path in extra_ignore_paths
                if ignore_path.strip()
            ]
            config.ignore_paths = [
                *config.ignore_paths,
                *config._isolation_paths,
            ]
        return config

    def save_to_disk(self) -> None:
        """Save determystic configuration under [tool.determystic]."""
        config_path = self.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)

        pyproject_data: dict[str, Any] = {}
        if config_path.exists():
            with config_path.open("rb") as f:
                pyproject_data = tomllib.load(f)

        tool_data = pyproject_data.setdefault("tool", {})
        determystic_data = self.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"validator_configs", "validators"},
            exclude_defaults=True,
        )
        validators_data: dict[str, dict[str, Any]] = {}
        for validator_name, validator_file in self.validators.items():
            validator_data = self._validator_metadata_to_save(validator_file)
            if validator_file.config:
                validator_data["config"] = validator_file.config
            if validator_data:
                validators_data[validator_name] = validator_data

        for validator_name, validator_config in self.validator_configs.items():
            if not validator_config:
                continue
            validator_data = dict(validators_data.get(validator_name, {}))
            validator_data["config"] = validator_config
            validators_data[validator_name] = validator_data
        if validators_data:
            determystic_data["validators"] = validators_data

        tool_data[self.TOOL_SECTION] = determystic_data

        with config_path.open("wb") as f:
            tomli_w.dump(pyproject_data, f)
    
    def new_validation(self, name: str, validator_script: str, test_script: str, description: str | None = None) -> ValidatorFile:
        """Add a new validator to the project configuration.
        
        Args:
            name: Name of the validator file (without extension)
            validator_path: Relative path to the validator file
            test_path: Optional relative path to the test file
            description: Optional description of what this validator checks
            
        Returns:
            The created ValidatorFile instance
        """
        config_root = self.config_root / ".determystic"
        
        # We don't want to bundle .py files since these get picked up by the static analysis validators
        validator_path = config_root / "validations" / f"{name}.determystic"
        validator_path.parent.mkdir(parents=True, exist_ok=True)

        test_path = config_root / "tests" / f"{name}.determystic"
        test_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the validator script to the validator path
        validator_path.write_text(validator_script)
        test_path.write_text(test_script)

        validator_file = ValidatorFile(
            name=name,
            validator_path=str(validator_path.relative_to(self.config_root)),
            test_path=str(test_path.relative_to(self.config_root)),
            description=description
        )
        
        self.validators[name] = validator_file
        
        return validator_file
    
    def delete_validation(self, name: str) -> bool:  # determystic: used
        """Remove a validator from the project configuration and disk.

        Args:
            name: Name of the validator to remove

        Returns:
            True if the validator was removed, False if it didn't exist
        """
        validator_file = self.get_custom_validators().get(name)
        if validator_file is None:
            return False

        self.validators.pop(name, None)

        self.resolve_project_path(validator_file.validator_path).unlink(missing_ok=True)
        if validator_file.test_path is not None:
            self.resolve_project_path(validator_file.test_path).unlink(missing_ok=True)

        return True

    def resolve_project_path(self, path: str | Path) -> Path:
        """Resolve a project-relative path from the pyproject configuration."""
        path = Path(path)
        if path.is_absolute():
            return path
        return self.config_root / path

    def get_validator_config(
        self,
        name: str,
        config_model: type[ConfigModelT],
    ) -> ConfigModelT:
        """Validate project config for a validator against a Pydantic model."""
        return config_model.model_validate(self._get_validator_config_data(name))

    @property
    def project_root(self) -> Path:
        """
        Get the root being validated.
        """
        if self._project_root is not None:
            return self._project_root
        return self.config_root

    @property
    def config_path(self) -> Path:
        """Get the pyproject.toml path that supplied this configuration."""
        if self._config_path is not None:
            return self._config_path
        return self.get_config_path()

    @property
    def config_root(self) -> Path:
        """Get the directory containing the pyproject.toml configuration."""
        return self.config_path.parent

    @property
    def isolation_paths(self) -> list[str]:
        """Get project-relative paths that isolate nested validation scopes."""
        return self._isolation_paths

    def get_custom_validators(self) -> dict[str, ValidatorFile]:
        """Return custom validators from legacy config metadata and discovered files."""
        validators = dict(self.validators)

        validations_dir = self.config_root / ".determystic" / "validations"
        if not validations_dir.is_dir():
            return validators

        for validator_path in sorted(validations_dir.glob("*.determystic")):
            validator_name = validator_path.stem
            test_path = self._default_test_path(validator_name)
            discovered = ValidatorFile(
                name=validator_name,
                validator_path=self._relative_project_path(validator_path),
                test_path=(
                    self._relative_project_path(test_path)
                    if test_path.exists()
                    else None
                ),
            )

            existing = validators.get(validator_name)
            if existing is None:
                validators[validator_name] = discovered
            elif existing.test_path is None and discovered.test_path is not None:
                validators[validator_name] = existing.model_copy(
                    update={"test_path": discovered.test_path}
                )

        return validators

    def _get_validator_config_data(self, name: str) -> dict[str, Any]:
        """Return raw per-validator configuration for a validator name."""
        config_data = dict(self.validator_configs.get(name, {}))
        validator_file = self.validators.get(name)
        if validator_file is not None:
            config_data.update(validator_file.config)
        return config_data

    def _validator_metadata_to_save(self, validator_file: ValidatorFile) -> dict[str, Any]:
        """Return explicit metadata only when the validator uses nonstandard paths."""
        validator_data: dict[str, Any] = {}
        default_validator_path = self._default_validator_path(validator_file.name)
        default_test_path = self._default_test_path(validator_file.name)

        if validator_file.validator_path != self._relative_project_path(default_validator_path):
            validator_data["validator_path"] = validator_file.validator_path
        if (
            validator_file.test_path is not None
            and validator_file.test_path != self._relative_project_path(default_test_path)
        ):
            validator_data["test_path"] = validator_file.test_path
        return validator_data

    def _default_validator_path(self, name: str) -> Path:
        return self.config_root / ".determystic" / "validations" / f"{name}.determystic"

    def _default_test_path(self, name: str) -> Path:
        return self.config_root / ".determystic" / "tests" / f"{name}.determystic"

    def _relative_project_path(self, path: Path) -> str:
        return str(path.relative_to(self.config_root))
