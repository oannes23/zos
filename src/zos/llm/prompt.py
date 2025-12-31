"""Prompt loading and rendering for LLM layers.

Prompts are stored as Jinja2 templates in:
    layers/<layer_name>/prompts/<prompt_name>.j2

Versioned prompts can be created by appending _v<N>:
    layers/<layer_name>/prompts/summarize.j2      (default)
    layers/<layer_name>/prompts/summarize_v2.j2   (version 2)
"""

from pathlib import Path
from typing import Any

import jinja2

from zos.exceptions import LLMError
from zos.logging import get_logger

logger = get_logger("llm.prompt")


class PromptLoader:
    """Loads and renders Jinja2 prompt templates.

    Prompts are organized by layer and stored as .j2 files.
    Each prompt can have multiple versions (e.g., prompt.j2, prompt_v2.j2).
    """

    def __init__(self, layers_dir: Path) -> None:
        """Initialize the prompt loader.

        Args:
            layers_dir: Base directory containing layer definitions.
        """
        self.layers_dir = layers_dir
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(layers_dir)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def get_prompt_path(
        self,
        layer_name: str,
        prompt_name: str,
        version: int | None = None,
    ) -> Path:
        """Get the path to a prompt template file.

        Args:
            layer_name: Name of the layer.
            prompt_name: Name of the prompt (without .j2 extension).
            version: Optional version number (e.g., 2 for prompt_v2.j2).

        Returns:
            Path to the prompt template file.
        """
        if version:
            filename = f"{prompt_name}_v{version}.j2"
        else:
            filename = f"{prompt_name}.j2"

        return self.layers_dir / layer_name / "prompts" / filename

    def prompt_exists(
        self,
        layer_name: str,
        prompt_name: str,
        version: int | None = None,
    ) -> bool:
        """Check if a prompt template exists.

        Args:
            layer_name: Name of the layer.
            prompt_name: Name of the prompt.
            version: Optional version number.

        Returns:
            True if the prompt template file exists.
        """
        return self.get_prompt_path(layer_name, prompt_name, version).exists()

    def load(
        self,
        layer_name: str,
        prompt_name: str,
        context: dict[str, Any],
        version: int | None = None,
    ) -> str:
        """Load and render a prompt template.

        Args:
            layer_name: Name of the layer (e.g., "channel_digest").
            prompt_name: Name of the prompt (e.g., "system", "summarize").
            context: Dictionary of variables to pass to the template.
            version: Optional version number for versioned prompts.

        Returns:
            Rendered prompt string.

        Raises:
            LLMError: If template not found or rendering fails.
        """
        # Build template path relative to layers_dir
        if version:
            template_path = f"{layer_name}/prompts/{prompt_name}_v{version}.j2"
        else:
            template_path = f"{layer_name}/prompts/{prompt_name}.j2"

        try:
            template = self._jinja_env.get_template(template_path)
            return template.render(**context)
        except jinja2.TemplateNotFound:
            full_path = self.layers_dir / template_path
            raise LLMError(
                f"Prompt template not found: {full_path}\n"
                f"Create the file at: {full_path}"
            ) from None
        except jinja2.TemplateError as e:
            raise LLMError(f"Failed to render prompt '{template_path}': {e}") from e

    def list_prompts(self, layer_name: str) -> list[str]:
        """List available prompts for a layer.

        Args:
            layer_name: Name of the layer.

        Returns:
            List of prompt names (without .j2 extension, includes versions).
        """
        prompts_dir = self.layers_dir / layer_name / "prompts"
        if not prompts_dir.exists():
            return []

        prompts = []
        for path in prompts_dir.glob("*.j2"):
            prompts.append(path.stem)

        return sorted(prompts)

    def list_prompt_versions(
        self,
        layer_name: str,
        prompt_name: str,
    ) -> list[int | None]:
        """List available versions of a prompt.

        Args:
            layer_name: Name of the layer.
            prompt_name: Base name of the prompt (without version suffix).

        Returns:
            List of version numbers (None for base version, 2, 3, etc.).
        """
        prompts_dir = self.layers_dir / layer_name / "prompts"
        if not prompts_dir.exists():
            return []

        versions: list[int | None] = []

        # Check for base version
        if (prompts_dir / f"{prompt_name}.j2").exists():
            versions.append(None)

        # Check for numbered versions
        for path in prompts_dir.glob(f"{prompt_name}_v*.j2"):
            # Extract version number from filename like "prompt_v2.j2"
            stem = path.stem
            suffix = stem.replace(f"{prompt_name}_v", "")
            try:
                version_num = int(suffix)
                versions.append(version_num)
            except ValueError:
                continue

        return sorted(versions, key=lambda x: (x is not None, x or 0))

    def load_raw(
        self,
        layer_name: str,
        prompt_name: str,
        version: int | None = None,
    ) -> str:
        """Load a prompt template without rendering.

        Useful for inspecting or debugging templates.

        Args:
            layer_name: Name of the layer.
            prompt_name: Name of the prompt.
            version: Optional version number.

        Returns:
            Raw template string.

        Raises:
            LLMError: If template not found.
        """
        path = self.get_prompt_path(layer_name, prompt_name, version)
        if not path.exists():
            raise LLMError(f"Prompt template not found: {path}")

        return path.read_text()
