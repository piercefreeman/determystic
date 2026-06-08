"""Tests for the validate CLI orchestration helpers."""

from determystic.cli.validate import _create_validation_jobs, _target_label
from determystic.project_discovery import ValidationTarget


def test_create_validation_jobs_scopes_inherited_config_to_target_root(tmp_path) -> None:
    """Workspace-inherited config runs validators against the member root."""
    root_pyproject = tmp_path / "pyproject.toml"
    root_pyproject.write_text(
        """
[project]
name = "workspace"

[tool.determystic]
enabled = ["hanging_functions"]
ignore_paths = ["generated/"]
"""
    )
    member_root = tmp_path / "packages" / "api"
    member_root.mkdir(parents=True)
    (member_root / "pyproject.toml").write_text("[project]\nname = \"api\"\n")
    target = ValidationTarget(
        project_root=member_root,
        config_path=root_pyproject,
        extra_ignore_paths=("nested-member",),
    )

    jobs = _create_validation_jobs([target], tmp_path)

    assert len(jobs) == 1
    assert jobs[0].target_label == "packages/api"
    assert jobs[0].validator.path == member_root
    assert getattr(jobs[0].validator, "ignore_paths") == [
        "generated/",
        "nested-member",
    ]


def test_create_validation_jobs_uses_unique_keys_for_duplicate_validator_names(tmp_path) -> None:
    """Repeated validator names from static tool split do not overwrite results."""
    root_pyproject = tmp_path / "pyproject.toml"
    root_pyproject.write_text(
        """
[project]
name = "single"

[tool.determystic]
enabled = ["static_analysis"]
"""
    )
    target = ValidationTarget(project_root=tmp_path, config_path=root_pyproject)

    jobs = _create_validation_jobs([target], tmp_path)

    assert [job.validator.name for job in jobs] == [
        "static_analysis",
        "static_analysis",
    ]
    assert len({job.key for job in jobs}) == 2


# determystic: tested-exceptions[determystic.cli.validate._target_label: ValueError]
def test_target_label_uses_absolute_path_for_targets_outside_requested_path(tmp_path) -> None:
    """Target labels fall back to absolute paths for unrelated roots."""
    requested_root = tmp_path / "requested"
    outside_root = tmp_path / "outside"
    requested_root.mkdir()
    outside_root.mkdir()
    target = ValidationTarget(
        project_root=outside_root,
        config_path=outside_root / "pyproject.toml",
    )

    assert _target_label(target, requested_root) == str(outside_root.resolve())
