# Log Patterns

Understanding Zos logs for monitoring and debugging.

---

## Log Formats

### JSON Format (Default)

Production-ready format for log aggregation:

```json
{"timestamp": "2024-01-15T10:00:00.000000Z", "level": "info", "event": "discord_ready", "user": "Zos#1234", "guilds": 1}
```

Enable with `log_json: true` in config (default).

### Console Format

Human-readable format for development:

```
2024-01-15 10:00:00 [info] discord_ready user=Zos#1234 guilds=1
```

Enable with `log_json: false` or `--no-log-json` CLI flag.

---

## Log Structure

All log entries include:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `level` | Log level (debug, info, warning, error) |
| `event` | Event identifier |
| `component` | Source component (when set) |

Additional fields vary by event type.

---

## Startup Events

### Bot Starting

```json
{"event": "bot_starting"}
```

Initial startup signal.

### Discord Ready

```json
{"event": "discord_ready", "user": "Zos#1234", "guilds": 2}
```

Successfully connected to Discord.

### Commands Synced

```json
{"event": "commands_synced"}
```

Slash commands registered with Discord.

### Cog Loaded

```json
{"event": "cog_loaded", "cog": "OperatorCommands"}
```

Command handler module loaded.

### API Starting

```json
{"event": "api_starting"}
```

API server initialization.

---

## Observation Events

### Poll Tick Complete

```json
{
  "event": "poll_messages_tick_complete",
  "messages_processed": 15,
  "channels_polled": 8,
  "duration_ms": 234
}
```

Regular polling cycle completed. Key metric for observation health.

### Message Stored

```json
{
  "event": "message_stored",
  "message_id": "123456789",
  "channel_id": "987654321",
  "author_id": "456789123"
}
```

Individual message captured (debug level).

### Media Analyzed

```json
{
  "event": "media_analyzed",
  "message_id": "123456789",
  "media_type": "image",
  "analysis_length": 150
}
```

Image or attachment processed by vision model.

### Link Summarized

```json
{
  "event": "link_summarized",
  "url": "https://example.com/article",
  "summary_length": 200
}
```

External link content fetched and summarized.

### Links Queued

```json
{
  "event": "links_queued",
  "message_id": "123456789"
}
```

Message content queued for link analysis (debug level).

### Links Processed

```json
{
  "event": "links_processed",
  "message_id": "123456789",
  "links_count": 2
}
```

Link analysis completed for a queued message (debug level).

---

## Reflection Events

### Layer Run Started

```json
{
  "event": "layer_triggered",
  "layer": "nightly-user-reflection",
  "trigger": "schedule"
}
```

Layer execution beginning. `trigger` is `schedule` or `manual`.

### Topics Selected

```json
{
  "event": "topics_selected",
  "layer": "nightly-user-reflection",
  "count": 12,
  "highest_salience": 45.2
}
```

Target selection complete.

### Node Completed

```json
{
  "event": "node_completed",
  "layer": "nightly-user-reflection",
  "node": "reflect",
  "topic": "server:123:user:456",
  "tokens_used": 543
}
```

Individual pipeline step finished (debug level).

### Insight Stored

```json
{
  "event": "insight_stored",
  "id": "01HN...",
  "topic": "server:123:user:456",
  "category": "user_reflection",
  "strength": 5.2
}
```

New insight created and persisted.

### Layer Run Completed

```json
{
  "event": "layer_run_completed",
  "layer": "nightly-user-reflection",
  "status": "success",
  "targets_processed": 12,
  "insights_created": 12,
  "duration_seconds": 150.5,
  "tokens_total": 8543,
  "estimated_cost_usd": 0.0234
}
```

Layer execution summary.

---

## Salience Events

### Topic Created

```json
{
  "event": "topic_created",
  "topic_key": "server:123:user:456",
  "category": "user"
}
```

New topic registered in the system.

### Salience Earned

```json
{
  "event": "salience_earned",
  "topic": "server:123:user:456",
  "amount": 1.0,
  "reason": "message",
  "new_balance": 23.5
}
```

Topic gained salience (debug level).

### Salience Spent

```json
{
  "event": "salience_spent",
  "topic": "server:123:user:456",
  "amount": 5.0,
  "reason": "reflection",
  "new_balance": 18.5
}
```

Salience consumed during reflection.

### Decay Applied

```json
{
  "event": "decay_applied",
  "topics_decayed": 12,
  "total_decayed": 3.45
}
```

Scheduled decay processed.

---

## Warning Events

### Channel Forbidden

```json
{
  "level": "warning",
  "event": "channel_forbidden",
  "channel_id": "123456789"
}
```

Bot lacks permission to read a channel. Check role permissions.

### Topic Skipped

```json
{
  "level": "warning",
  "event": "topic_skipped",
  "topic": "server:123:user:456",
  "reason": "no_recent_messages"
}
```

Topic selected for reflection but had no data to process.

### Topic Not Found

```json
{
  "level": "warning",
  "event": "topic_not_found",
  "topic": "server:123:user:456",
  "layer": "nightly-user-reflection"
}
```

Referenced topic doesn't exist in database.

### Poll Channel Error

```json
{
  "level": "warning",
  "event": "poll_channel_error",
  "channel_id": "123456789",
  "error": "Missing Access"
}
```

Error reading a specific channel.

### Link Queue Near Full

```json
{
  "level": "warning",
  "event": "link_queue_near_full",
  "queue_size": 42,
  "max_size": 50
}
```

Link analysis queue is above 80% capacity. Consider increasing `link_queue_max_size` or `link_rate_limit_per_minute`.

### Link Queue Full

```json
{
  "level": "warning",
  "event": "link_queue_full",
  "message_id": "123456789",
  "queue_size": 50
}
```

Link analysis queue is full; message links were dropped. Increase `link_queue_max_size` or `link_rate_limit_per_minute`.

### Robots Blocked

```json
{
  "level": "warning",
  "event": "robots_blocked",
  "url": "https://example.com/page"
}
```

URL blocked by robots.txt during link fetching.

---

## Error Events

### Layer Failed

```json
{
  "level": "error",
  "event": "layer_run_failed",
  "layer": "nightly-user-reflection",
  "error": "API rate limit exceeded"
}
```

Layer execution failed. Check API quotas and network.

### Observe Failed

```json
{
  "level": "error",
  "event": "observe_failed",
  "error": "Connection reset"
}
```

Discord connection lost. Bot will attempt to reconnect.

### API Failed

```json
{
  "level": "error",
  "event": "api_failed",
  "error": "Address already in use"
}
```

API server couldn't start. Check port availability.

---

## Shutdown Events

### Shutdown Initiated

```json
{"event": "shutdown_initiated"}
```

Graceful shutdown starting (SIGTERM or Ctrl+C received).

### Shutdown Complete

```json
{"event": "shutdown_complete"}
```

All connections closed cleanly.

### Discord Disconnected

```json
{"event": "discord_disconnected"}
```

Lost connection to Discord gateway.

### Discord Resumed

```json
{"event": "discord_resumed"}
```

Reconnected to Discord after disconnection.

---

## Filtering and Analysis

### With jq

```bash
# Count events by type
cat zos.log | jq -s 'group_by(.event) | map({event: .[0].event, count: length}) | sort_by(.count) | reverse'

# Show errors only
cat zos.log | jq 'select(.level == "error")'

# Track layer runs
cat zos.log | jq 'select(.event | startswith("layer_"))'

# Recent insight creation
cat zos.log | jq 'select(.event == "insight_stored")'
```

### With grep

```bash
# All warnings and errors
grep -E '"level":"(warning|error)"' zos.log

# Specific layer activity
grep 'nightly-user-reflection' zos.log
```

---

## Log Levels

| Level | Description | When to Use |
|-------|-------------|-------------|
| DEBUG | Detailed tracing | Development, troubleshooting |
| INFO | Normal operations | Production monitoring |
| WARNING | Recoverable issues | Alerts for operators |
| ERROR | Failures | Immediate attention needed |

Set level in config or with `--log-level`:

```bash
zos --log-level DEBUG observe
```
