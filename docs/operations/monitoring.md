# Monitoring

Health checks, metrics, and alerting for Zos instances.

---

## Health Endpoint

The primary health check:

```bash
curl http://localhost:8000/health
```

**Healthy response:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2024-01-15T10:00:00.000000Z",
  "database": "ok",
  "scheduler": "ok"
}
```

**Degraded response:**
```json
{
  "status": "degraded",
  "version": "0.1.0",
  "timestamp": "2024-01-15T10:00:00.000000Z",
  "database": "error",
  "scheduler": "ok"
}
```

---

## Key Metrics

### Observation Health

Check that messages are being processed:

```bash
# Look for recent poll completions
grep "poll_messages_tick_complete" /var/log/zos/observe.log | tail -5
```

Healthy indicators:
- `poll_messages_tick_complete` events every polling interval
- `messages_processed` > 0 when there's channel activity
- No repeated `channel_forbidden` warnings

### Reflection Health

Check layer run statistics:

```bash
curl "http://localhost:8000/runs/stats/summary?days=7"
```

Healthy indicators:
- `successful_runs` increasing over time
- `failed_runs` = 0 or rare
- `dry_runs` occasional (normal when no topics qualify)
- `insights_created` growing with community activity

### Salience Distribution

Check that salience is accumulating across topics:

```bash
curl "http://localhost:8000/salience/groups"
```

Healthy indicators:
- Multiple budget groups have `topic_count` > 0
- `total_salience` reflects recent activity
- No single topic dominating (check `top_topics`)

---

## Monitoring Scripts

### Simple Health Check

```bash
#!/bin/bash
# health-check.sh

response=$(curl -s http://localhost:8000/health)
status=$(echo "$response" | jq -r '.status')

if [ "$status" = "ok" ]; then
    echo "OK"
    exit 0
else
    echo "DEGRADED: $response"
    exit 1
fi
```

### Daily Summary

```bash
#!/bin/bash
# daily-summary.sh

echo "=== Zos Daily Summary ==="
echo

echo "Health:"
curl -s http://localhost:8000/health | jq .

echo
echo "Message Stats:"
curl -s "http://localhost:8000/messages/stats" | jq '{total, top_channels: .by_channel[:3], top_authors: .by_author[:3]}'

echo
echo "Layer Run Stats (24h):"
curl -s "http://localhost:8000/runs/stats/summary?days=1" | jq '{
  total_runs,
  successful_runs,
  failed_runs,
  total_insights,
  total_cost_usd
}'

echo
echo "Top Topics:"
curl -s "http://localhost:8000/salience?limit=5" | jq '.[] | {topic_key, balance}'
```

---

## Alerting Conditions

### Critical

Alert immediately:
- Health endpoint returns non-200
- `status: "degraded"` persists > 5 minutes
- No `poll_messages_tick_complete` events for > 5 polling intervals
- `level: "error"` events in logs

### Warning

Alert for review:
- `failed_runs` > 0 in daily stats
- Repeated `channel_forbidden` warnings
- `dry_runs` for multiple consecutive days
- Single topic > 80% of budget group salience

### Informational

Log for trending:
- `total_cost_usd` per day
- `insights_created` per day
- `tokens_total` per day

---

## Process Monitoring

### Systemd

If running as a systemd service:

```bash
# Check service status
systemctl status zos-observe
systemctl status zos-api

# View recent logs
journalctl -u zos-observe -n 50
journalctl -u zos-api -n 50
```

### Docker

If running in containers:

```bash
# Check container health
docker ps | grep zos

# View logs
docker logs zos-observe --tail 50
docker logs zos-api --tail 50
```

### Manual

For manual runs:

```bash
# Check process
pgrep -f "zos observe"
pgrep -f "zos api"
```

---

## Database Monitoring

### Size Growth

```bash
# Check database size
ls -lh ./data/zos.db
```

Expected growth: ~1MB per 1000 messages + insights.

### Migration Status

```bash
zos db status
```

Ensure no pending migrations after updates.

---

## Cost Tracking

### Budget Dashboard

The web UI provides a visual budget dashboard at `/ui/budget` showing:
- Total cost summary (30 days)
- Daily cost chart with bar visualization
- Cost breakdown by layer, model, and call type
- Token usage statistics

### API Endpoints

Monitor LLM API costs via the runs endpoint:

```bash
# Weekly cost
curl -s "http://localhost:8000/runs/stats/summary?days=7" | jq '.total_cost_usd'

# Monthly estimate
curl -s "http://localhost:8000/runs/stats/summary?days=30" | jq '.total_cost_usd'
```

Cost is estimated from token counts and current model pricing.

---

## Log Aggregation

For production deployments, consider:

1. **Structured logging** to a collector (Loki, Elasticsearch)
2. **Dashboards** with Grafana or similar
3. **Alerting** via PagerDuty, Opsgenie, or email

Example Loki query for error rate:
```
rate({job="zos"} |= "error" [5m])
```

---

## Uptime Monitoring

External uptime services can poll:

- `/health` endpoint for API availability
- Discord bot status via Discord's API

Note: The observation bot doesn't expose an HTTP endpoint — monitor via logs or Discord status.
