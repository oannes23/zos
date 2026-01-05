"""Configuration endpoint with secrets redacted."""

from typing import Any

from fastapi import APIRouter

from zos.api.dependencies import ConfigDep
from zos.config import ZosConfig

router = APIRouter()


def redact_config(config: ZosConfig) -> dict[str, Any]:
    """Redact sensitive values from config.

    Args:
        config: The full ZosConfig.

    Returns:
        Dictionary with secrets replaced by "***REDACTED***".
    """
    result: dict[str, Any] = {
        "discord": {
            "token": "***REDACTED***" if config.discord.token else None,
            "guilds": config.discord.guilds,
            "excluded_channels": config.discord.excluded_channels,
            "output_channels": config.discord.output_channels,
            "tracking_opt_in_role": config.discord.tracking_opt_in_role,
        },
        "database": {"path": str(config.database.path)},
        "budget": config.budget.model_dump(),
        "salience": config.salience.model_dump(),
        "logging": {
            "level": config.logging.level,
            "format": config.logging.format,
            "file": str(config.logging.file) if config.logging.file else None,
        },
        "layers_dir": str(config.layers_dir),
        "enabled_layers": config.enabled_layers,
        "api": config.api.model_dump(),
    }

    # Redact LLM config
    if config.llm:
        llm_config: dict[str, Any] = {
            "default_provider": config.llm.default_provider,
            "default_model": config.llm.default_model,
        }
        if config.llm.openai:
            llm_config["openai"] = {
                "api_key": "***REDACTED***" if config.llm.openai.api_key else None,
                "base_url": config.llm.openai.base_url,
                "default_model": config.llm.openai.default_model,
            }
        if config.llm.anthropic:
            llm_config["anthropic"] = {
                "api_key": "***REDACTED***" if config.llm.anthropic.api_key else None,
                "default_model": config.llm.anthropic.default_model,
            }
        if config.llm.ollama:
            llm_config["ollama"] = {
                "base_url": config.llm.ollama.base_url,
                "default_model": config.llm.ollama.default_model,
            }
        if config.llm.generic:
            llm_config["generic"] = {
                name: {
                    "base_url": gc.base_url,
                    "default_model": gc.default_model,
                    "api_key": "***REDACTED***" if gc.api_key else None,
                }
                for name, gc in config.llm.generic.items()
            }
        result["llm"] = llm_config
    else:
        result["llm"] = None

    return result


@router.get("", response_model=dict[str, Any])
async def get_config(config: ConfigDep) -> dict[str, Any]:
    """Get current configuration with secrets redacted.

    Returns the full configuration with sensitive values like API keys
    and tokens replaced with "***REDACTED***".
    """
    return redact_config(config)
