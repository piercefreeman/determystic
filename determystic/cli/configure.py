"""Configuration command for setting up API keys and other settings."""


import rich_click as click

from determystic.cli import ui
from determystic.configs.system import DeterministicSettings
from determystic.io import async_to_sync

console = ui.console


@click.command()
@async_to_sync
async def configure_command():
    """Configure API keys and other settings for the determystic tool."""
    ui.banner("configure", subtitle="set up API keys and preferences")

    # Load existing settings or create new ones
    settings = DeterministicSettings.load_from_disk(required=False)

    if not settings:
        settings = DeterministicSettings()

    # Convert existing values to a simple dict
    existing_values = settings.model_dump()

    # Iterate through all model fields
    for field_name, field_info in settings.model_fields.items():
        current_value = existing_values.get(field_name)
        description = field_info.description or f"Enter {field_name.replace('_', ' ')}"
        sensitive = _is_sensitive_field(field_name)

        # Show masked current value for sensitive fields; prefill the rest
        if current_value:
            masked_value = _mask_sensitive_value(str(current_value), field_name)
            description += f" (current: {masked_value})"

        new_value = await ui.text_input(
            field_name.replace('_', ' ').title(),
            description=description,
            password=sensitive,
            placeholder="press enter to keep current value" if current_value else None,
        )

        # Update the settings if a value was provided
        if new_value:
            setattr(settings, field_name, new_value)

    # Save configuration
    settings.save_to_disk()
    config_path = settings.get_config_path()

    console.print()
    ui.success("Configuration saved")
    ui.hint(str(config_path))

    # Show what was configured
    console.print()
    for field_name in settings.model_fields:
        current_value = getattr(settings, field_name)
        if current_value:
            masked_value = _mask_sensitive_value(str(current_value), field_name)
            ui.detail(field_name.replace('_', ' '), masked_value)

    console.print()
    ui.hint("try: determystic new-validator")


def _is_sensitive_field(field_name: str) -> bool:
    """Determine if a field contains sensitive information."""
    return any(term in field_name.lower() for term in ["key", "password", "secret", "token"])


def _mask_sensitive_value(value: str, field_name: str) -> str:
    """Mask sensitive values for display."""
    if _is_sensitive_field(field_name):
        return value[:7] + "..." + value[-4:] if len(value) > 10 else "***"
    return value
