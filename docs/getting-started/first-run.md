# First Run

Start Zos and verify everything is working correctly.

---

## Initialize the Database

Before starting Zos, initialize the database:

```bash
zos db migrate
```

Expected output:
```
Migrated from version 0 to 5
```

Check database status:
```bash
zos db status
```

---

## Start Observation

In the first terminal, start the Discord observation bot:

```bash
zos observe
```

Expected log output:
```json
{"timestamp": "...", "level": "info", "event": "bot_starting"}
{"timestamp": "...", "level": "info", "event": "discord_ready", "user": "Zos#1234", "guilds": 1}
```

The bot is now connected and observing your Discord servers.

### Verify Discord Connection

In Discord:
1. Check that the bot appears online in your server
2. Try the `/ping` slash command
3. The bot should respond with "Pong!"

---

## Start the API

In a second terminal, start the introspection API:

```bash
zos api
```

Expected output:
```json
{"timestamp": "...", "level": "info", "event": "api_command_invoked", "host": "127.0.0.1", "port": 8000}
{"timestamp": "...", "level": "info", "event": "api_starting"}
```

### Verify API

Check the health endpoint:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "...",
  "database": "ok",
  "scheduler": "ok"
}
```

Visit `http://localhost:8000/docs` for interactive API documentation.

---

## Test Observation

1. Send a message in a channel the bot can see
2. Wait for the polling interval (default: 60 seconds)
3. Check logs for:
   ```json
   {"event": "poll_messages_tick_complete", "messages_processed": 1, ...}
   ```

---

## Operator Commands

If you configured your Discord user ID as an operator, try these slash commands:

| Command | Description |
|---------|-------------|
| `/ping` | Test that the bot is responsive |
| `/status` | Show operational status |
| `/topics` | List top topics by salience |
| `/insights <topic>` | Show insights for a topic |

---

## Understanding the Output

### Console Logs

With `log_json: false`:
```
2024-01-15 10:00:00 [info] discord_ready user=Zos#1234 guilds=1
```

### JSON Logs

With `log_json: true` (default):
```json
{"timestamp": "2024-01-15T10:00:00.000000Z", "level": "info", "event": "discord_ready", "user": "Zos#1234", "guilds": 1}
```

---

## Stopping Zos

Press `Ctrl+C` in each terminal for graceful shutdown:

```json
{"event": "shutdown_initiated"}
{"event": "shutdown_complete"}
```

---

## Troubleshooting First Run

### Bot doesn't come online

- Verify `DISCORD_TOKEN` is set correctly
- Check that all three Privileged Gateway Intents are enabled
- Review logs for error messages

### Slash commands don't appear

- Commands sync automatically on first startup
- May take up to an hour to propagate globally
- For immediate testing, the bot syncs to the first guild on startup

### No messages being processed

- Verify the bot has "Read Message History" permission
- Check channel-specific permission overrides
- Ensure `polling_interval_seconds` hasn't been set too high

See [Troubleshooting](../operations/troubleshooting.md) for more solutions.

---

## Next Steps

- [Monitor operations](../operations/monitoring.md)
- [Read log patterns](../operations/log-patterns.md)
- [Explore the API](../operations/api-reference.md)
- [Understand how Zos thinks](../concepts/how-zos-thinks.md)
