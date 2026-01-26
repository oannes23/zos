# CLI Reference

Complete reference for the `zos` command-line interface.

---

## Global Options

These options apply to all commands:

```bash
zos [OPTIONS] COMMAND [ARGS]
```

| Option | Description |
|--------|-------------|
| `-c, --config-file PATH` | Path to configuration file |
| `--log-level LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `--log-json / --no-log-json` | Override JSON logging format |

---

## Core Commands

### `zos version`

Print version information.

```bash
zos version
```

Output:
```
zos 0.1.0
```

---

### `zos observe`

Start the Discord observation bot.

```bash
zos observe
```

Connects to Discord and begins observing community conversations. This is the "eyes and ears" of Zos — attentive presence in communities.

**Requirements:**
- `DISCORD_TOKEN` environment variable must be set

**Behavior:**
- Polls Discord channels at the configured interval
- Stores messages and reactions
- Accumulates salience for topics
- Handles media analysis (images, links)

**Shutdown:**
- Press `Ctrl+C` or send `SIGTERM` for graceful shutdown

**Example with options:**
```bash
zos --config-file ./custom-config.yaml --log-level DEBUG observe
```

---

### `zos api`

Start the introspection API server.

```bash
zos api [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | 127.0.0.1 | Host to bind |
| `--port` | 8000 | Port to bind |

**Examples:**
```bash
# Default: localhost only
zos api

# Bind to all interfaces on port 9000
zos api --host 0.0.0.0 --port 9000
```

**Endpoints:**
- `GET /health` — Health check
- `GET /docs` — Interactive API documentation
- `GET /insights` — Query insights
- `GET /salience` — Query salience
- `GET /runs` — Layer run history

See [API Reference](api-reference.md) for full endpoint documentation.

---

## Database Commands

### `zos db status`

Show database migration status.

```bash
zos db status
```

Output:
```
Database: ./data/zos.db
Current version: 5
Available migrations: 5
No pending migrations
```

---

### `zos db migrate`

Apply pending database migrations.

```bash
zos db migrate [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--target VERSION` | Migrate to specific version (default: latest) |

**Examples:**
```bash
# Migrate to latest
zos db migrate

# Migrate to specific version
zos db migrate --target 3
```

Output:
```
Migrated from version 0 to 5
```

---

## Configuration Commands

### `zos config check`

Validate configuration file.

```bash
zos config check [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-c, --config-file` | config.yaml | Path to configuration file |

**Example:**
```bash
zos config check -c ./my-config.yaml
```

Output:
```
Configuration valid: ./my-config.yaml
  Data directory: ./data
  Database path: ./data/zos.db
  Log level: INFO
  Model profiles: 9
  Model aliases: reflection, conversation, synthesis, self_reflection, review, vision, default
```

---

## Salience Commands

### `zos salience decay`

Manually trigger salience decay.

```bash
zos salience decay
```

Applies decay to all inactive topics. Topics are considered inactive if they haven't had activity in the configured threshold (default: 7 days).

Output:
```
Decayed 12 topics, total 3.45 salience
  Threshold: 7 days
  Decay rate: 1.0% per day
```

**Note:** In production, decay runs automatically via the scheduler. This command is useful for testing or manual maintenance.

---

## Layer Commands

### `zos layer list`

List all available layers.

```bash
zos layer list [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | layers | Layers directory |

Output:
```
Found 2 layer(s):

  nightly-user-reflection: user (0 3 * * *)
  weekly-self-reflection: self (0 4 * * 0)
```

---

### `zos layer validate`

Validate a specific layer by name.

```bash
zos layer validate NAME [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | layers | Layers directory |

**Example:**
```bash
zos layer validate nightly-user-reflection
```

Output:
```
Layer 'nightly-user-reflection' is valid
  Category: user
  Nodes: 4
  Hash: a1b2c3d4...
  Schedule: 0 3 * * *
  Target filter: salience > 30
  Max targets: 15

  Description:
    Reflect on each user's recent activity to build understanding.
    Runs nightly at 3 AM, targeting users with highest salience.
```

---

## Reflection Commands

### `zos reflect trigger`

Manually trigger a layer execution.

```bash
zos reflect trigger LAYER_NAME [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | layers | Layers directory |

Bypasses the schedule and executes the specified layer immediately.

**Example:**
```bash
zos reflect trigger nightly-user-reflection
```

Output:
```
Layer executed: success
  Targets matched: 15
  Targets processed: 12
  Insights created: 12
  Tokens used: 8543
  Estimated cost: $0.0234
```

---

### `zos reflect jobs`

List layers with cron schedules.

```bash
zos reflect jobs [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | layers | Layers directory |

Output:
```
Scheduled reflection layers (2):

  nightly-user-reflection
    Category: user
    Schedule: 0 3 * * * (cron, UTC)
    Max targets: 15

  weekly-self-reflection
    Category: self
    Schedule: 0 4 * * 0 (cron, UTC)
    Threshold trigger: 10 insights
    Max targets: 1

Manual layers (0):
```

---

## Command Patterns

### Running in Development

```bash
# Verbose logging
zos --log-level DEBUG --no-log-json observe

# Custom config
zos -c dev-config.yaml api
```

### Running in Production

```bash
# JSON logs for aggregation
zos --log-json observe 2>&1 | tee -a /var/log/zos/observe.log

# Bind API to all interfaces
zos api --host 0.0.0.0 --port 8000
```

### Checking Before Running

```bash
# Validate everything
zos config check
zos db status
zos layer list
```
