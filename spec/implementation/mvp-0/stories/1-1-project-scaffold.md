# Story 1.1: Project Scaffold

**Epic**: Foundation
**Status**: 🟢 Complete
**Estimated complexity**: Small

## Goal

Establish the project structure, dependencies, and basic CLI entrypoint so all subsequent work has a foundation to build on.

## Acceptance Criteria

- [x] `pyproject.toml` with all dependencies defined
- [x] Directory structure matches the flat module layout
- [x] `python -m zos --help` shows available commands
- [x] `python -m zos version` prints version
- [x] Basic logging configured (structured JSON)
- [x] `.gitignore` covers Python artifacts, .env, data/
- [x] Tests run with `pytest`

## Dependencies

```toml
[project]
name = "zos"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "pyyaml>=6.0",
    "jinja2>=3.1.0",
    "discord.py>=2.3.0",
    "apscheduler>=3.10.0",
    "anthropic>=0.18.0",
    "httpx>=0.26.0",
    "python-ulid>=2.2.0",
    "structlog>=24.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
]
```

## Directory Structure

```
zos/
├── pyproject.toml
├── README.md
├── .gitignore
├── .env.example
├── config.yaml.example
├── data/
│   └── self-concept.md      # Already exists
├── spec/                     # Already exists
├── src/
│   └── zos/
│       ├── __init__.py      # Version, package metadata
│       ├── __main__.py      # CLI entrypoint
│       ├── cli.py           # Click/Typer CLI commands
│       ├── logging.py       # Structured logging setup
│       └── (other modules created in later stories)
└── tests/
    ├── __init__.py
    ├── conftest.py          # Pytest fixtures
    └── test_cli.py          # Basic CLI tests
```

## Technical Notes

### CLI Framework

Use `click` for CLI — simple, well-documented, no magic:

```python
# src/zos/cli.py
import click

@click.group()
def cli():
    """Zos — Discord agent with temporal depth."""
    pass

@cli.command()
def version():
    """Print version."""
    from zos import __version__
    click.echo(f"zos {__version__}")

# Future commands: serve, observe, reflect, db
```

### Logging

Use `structlog` for structured JSON logging:

```python
# src/zos/logging.py
import structlog

def setup_logging(json_output: bool = True):
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
```

### __main__.py

```python
# src/zos/__main__.py
from zos.cli import cli
from zos.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    cli()
```

## Files to Create

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata and dependencies |
| `.gitignore` | Ignore patterns |
| `.env.example` | Example environment variables |
| `config.yaml.example` | Example configuration |
| `src/zos/__init__.py` | Package init with version |
| `src/zos/__main__.py` | CLI entrypoint |
| `src/zos/cli.py` | CLI commands |
| `src/zos/logging.py` | Logging configuration |
| `tests/conftest.py` | Pytest fixtures |
| `tests/test_cli.py` | CLI smoke tests |

## Definition of Done

- [x] Can run `pip install -e .` successfully (using uv sync)
- [x] `python -m zos --help` works
- [x] `pytest` runs (7 tests passing)
- [x] Logging outputs structured JSON

---

**Blocks**: All other stories (this is the foundation)
