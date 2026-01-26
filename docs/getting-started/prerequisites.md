# Prerequisites

Before setting up Zos, ensure you have the following.

---

## Required

### Python 3.11+

Zos requires Python 3.11 or later.

```bash
python --version
# Should show Python 3.11.x or higher
```

### pip

Python's package manager should be available:

```bash
pip --version
```

### Discord Account

You need a Discord account with permission to add bots to at least one server.

### Anthropic API Key

Zos uses Claude for reflection. You'll need an API key from [Anthropic](https://console.anthropic.com/).

---

## Recommended

### Virtual Environment

Use a virtual environment to isolate dependencies:

```bash
# Create environment
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### Git

For cloning the repository:

```bash
git --version
```

---

## Installation

Clone the repository and install in development mode:

```bash
git clone https://github.com/your-org/zos.git
cd zos
pip install -e .
```

Verify installation:

```bash
zos version
```

---

## Next Step

[Discord Setup](discord-setup.md) — Create your Discord bot application
