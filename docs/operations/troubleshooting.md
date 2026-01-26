# Troubleshooting

Common issues and their solutions.

---

## Connection Issues

### Bot doesn't come online

**Symptoms:**
- Bot shows offline in Discord
- No `discord_ready` log event

**Solutions:**
1. Verify `DISCORD_TOKEN` is set and correct
2. Check that the token hasn't been regenerated in Discord Developer Portal
3. Ensure all three Privileged Gateway Intents are enabled:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent

### Bot keeps disconnecting

**Symptoms:**
- Repeated `discord_disconnected` events
- `discord_resumed` followed by `discord_disconnected`

**Solutions:**
1. Check network stability
2. Verify Discord isn't having an outage (status.discord.com)
3. Ensure the bot isn't rate limited (too many connections)
4. Check for memory issues on the host

### API won't start

**Symptoms:**
- `api_failed` error on startup
- "Address already in use" error

**Solutions:**
1. Check if another process is using the port: `lsof -i :8000`
2. Use a different port: `zos api --port 8001`
3. Kill the existing process or wait for it to terminate

---

## Permission Issues

### Slash commands don't appear

**Symptoms:**
- Commands not showing in Discord
- "Unknown command" errors

**Solutions:**
1. Commands sync on first startup — wait up to an hour for global propagation
2. Ensure bot has `applications.commands` scope
3. Check that the bot is invited to the server
4. Try removing and re-adding the bot

### Bot can't read channels

**Symptoms:**
- `channel_forbidden` warnings in logs
- Messages not being captured

**Solutions:**
1. Verify bot has "Read Messages/View Channels" permission
2. Check channel-specific permission overrides
3. Ensure bot's role isn't below channel restrictions
4. For private channels, explicitly add the bot

### Operator commands denied

**Symptoms:**
- "Not authorized" when using slash commands

**Solutions:**
1. Verify your Discord user ID is in `config.yaml`:
   ```yaml
   discord:
     operators:
       user_ids:
         - "YOUR_USER_ID"
   ```
2. Alternatively, configure an operator role
3. Reload config and restart the bot

---

## Reflection Issues

### No insights being created

**Symptoms:**
- `dry_runs` in stats
- `insights_created: 0` in layer runs

**Solutions:**
1. Check that topics have sufficient salience: `zos salience`
2. Verify the target filter isn't too restrictive (default: `salience > 30`)
3. Ensure there's recent message activity to reflect on
4. Check for LLM API errors in logs

### Layer runs failing

**Symptoms:**
- `status: "failed"` in run history
- `layer_run_failed` errors in logs

**Solutions:**
1. Check the error details: `curl http://localhost:8000/runs/{run_id}`
2. Common causes:
   - LLM API rate limits: wait and retry
   - Invalid API key: check `ANTHROPIC_API_KEY`
   - Network issues: verify connectivity
3. Try manual trigger to see detailed errors: `zos reflect trigger <layer>`

### Reflection not running on schedule

**Symptoms:**
- No layer runs at expected times
- Missing `layer_triggered` events

**Solutions:**
1. Verify layer schedule: `zos reflect jobs`
2. Check that observation process is running (scheduler runs within it)
3. Ensure system clock is accurate
4. Check for scheduler errors in logs

---

## Database Issues

### Migration errors

**Symptoms:**
- Errors on `zos db migrate`
- Version mismatch warnings

**Solutions:**
1. Check current status: `zos db status`
2. Backup database before retrying
3. For corrupt databases, restore from backup

### Database locked

**Symptoms:**
- "database is locked" errors
- Slow queries

**Solutions:**
1. Ensure only one observation process is running
2. Check for long-running transactions
3. Consider enabling WAL mode (advanced)

### Database growing too large

**Symptoms:**
- Disk space warnings
- Slow startup

**Solutions:**
1. Check database size: `ls -lh ./data/zos.db`
2. Consider pruning old message history (future feature)
3. Archive old databases periodically

---

## Performance Issues

### High memory usage

**Symptoms:**
- OOM errors
- Slow response times

**Solutions:**
1. Reduce media analysis concurrency
2. Lower polling frequency
3. Limit insight retrieval counts
4. Add memory limits to container/service

### High API costs

**Symptoms:**
- Unexpected billing
- High `total_cost_usd` in stats

**Solutions:**
1. Review layer schedules — are they running too often?
2. Reduce `max_targets` in layer definitions
3. Use lower-tier models for simple tasks
4. Monitor daily cost: `curl http://localhost:8000/runs/stats/summary?days=1`

### Slow polling

**Symptoms:**
- `poll_messages_tick_complete` taking too long
- Messages being missed

**Solutions:**
1. Reduce number of channels being observed
2. Increase `polling_interval_seconds`
3. Check network latency to Discord

---

## Configuration Issues

### Config validation errors

**Symptoms:**
- Errors on `zos config check`
- Startup failures

**Solutions:**
1. Check YAML syntax (indentation, special characters)
2. Validate against the example: `diff config.yaml config.yaml.example`
3. Ensure all required fields are present

### Environment variables not loading

**Symptoms:**
- "DISCORD_TOKEN not set" errors
- API key errors

**Solutions:**
1. Verify variables are set: `echo $DISCORD_TOKEN`
2. For systemd, add to service file or use `EnvironmentFile`
3. For Docker, use `-e` flags or `--env-file`

---

## Getting Help

If issues persist:

1. **Check logs** with debug level: `zos --log-level DEBUG observe`
2. **Verify configuration** with: `zos config check`
3. **Test components** individually:
   - Database: `zos db status`
   - Layers: `zos layer validate <name>`
   - API: `curl http://localhost:8000/health`
4. **Gather information**:
   - Zos version: `zos version`
   - Python version: `python --version`
   - Recent log output
   - Configuration (redact tokens)

Report issues at the project's issue tracker with this information.
