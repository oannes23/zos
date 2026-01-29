# API Reference

The Zos introspection API provides endpoints for querying messages, insights, salience, and operational state.

---

## Base URL

```
http://localhost:8000
```

Start the API with `zos api`. Interactive documentation is available at `/docs` (Swagger UI) and `/redoc`.

A web UI is also available at `/ui/` for browsing messages, insights, users, channels, salience, and layer runs.

---

## Health

### GET /health

Check system health status.

**Response:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2024-01-15T10:00:00.000000Z",
  "database": "ok",
  "scheduler": "ok"
}
```

**Status values:**
- `ok` — All components healthy
- `degraded` — One or more components have issues

---

## Messages

### GET /messages

List stored Discord messages with optional filters.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel_id` | string | — | Filter by channel |
| `author_id` | string | — | Filter by author |
| `server_id` | string | — | Filter by server |
| `since` | datetime | — | Only messages after this time |
| `until` | datetime | — | Only messages before this time |
| `readable` | bool | false | Replace IDs with human-readable names |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
curl "http://localhost:8000/messages?channel_id=123456&limit=10"
```

**Response:**
```json
{
  "readable": false,
  "messages": [
    {
      "id": "1234567890",
      "channel_id": "123456",
      "channel_name": null,
      "server_id": "789012",
      "server_name": null,
      "author_id": "456789",
      "author_name": null,
      "content": "Hello everyone!",
      "created_at": "2024-01-15T10:30:00.000000Z",
      "visibility_scope": "public",
      "reactions_aggregate": {"👍": 3, "❤️": 1},
      "reply_to_id": null,
      "thread_id": null,
      "has_media": false,
      "has_links": false,
      "temporal_marker": "2 days ago"
    }
  ],
  "total": 1542,
  "offset": 0,
  "limit": 10
}
```

With `readable=true`, the response includes resolved names:
```json
{
  "readable": true,
  "messages": [
    {
      "id": "1234567890",
      "channel_id": "123456",
      "channel_name": "general",
      "server_id": "789012",
      "server_name": "My Server",
      "author_id": "456789",
      "author_name": "Alice",
      "content": "Hello everyone!",
      ...
    }
  ],
  ...
}
```

---

### GET /messages/search

Search messages by content.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query (min 2 chars) |
| `channel_id` | string | — | Filter by channel |
| `author_id` | string | — | Filter by author |
| `server_id` | string | — | Filter by server |
| `readable` | bool | false | Replace IDs with human-readable names |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
curl "http://localhost:8000/messages/search?q=hello&readable=true"
```

---

### GET /messages/{message_id}

Get a single message by ID.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `readable` | bool | false | Replace IDs with human-readable names |

**Example:**
```bash
curl "http://localhost:8000/messages/1234567890?readable=true"
```

---

### GET /messages/stats

Get message statistics by channel and author.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `server_id` | string | — | Filter by server |
| `readable` | bool | false | Replace IDs with human-readable names |

**Response:**
```json
{
  "total": 5432,
  "by_channel": [
    {"channel_id": "123", "channel_name": "general", "count": 2100},
    {"channel_id": "456", "channel_name": "random", "count": 1500}
  ],
  "by_author": [
    {"author_id": "789", "author_name": "Alice", "count": 450},
    {"author_id": "012", "author_name": "Bob", "count": 320}
  ]
}
```

---

## Insights

### GET /insights

List recent insights with optional filters.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `category` | string | — | Filter by insight category |
| `since` | datetime | — | Only include insights after this time |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
curl "http://localhost:8000/insights?category=user_reflection&limit=5"
```

**Response:**
```json
{
  "insights": [
    {
      "id": "01HN...",
      "topic_key": "server:123:user:456",
      "category": "user_reflection",
      "content": "Alice expresses warmth through thoughtful responses...",
      "created_at": "2024-01-15T03:00:00.000000Z",
      "temporal_marker": "clear memory from 2 days ago",
      "strength": 5.2,
      "confidence": 0.8,
      "importance": 0.7,
      "novelty": 0.6,
      "valence": {
        "joy": 0.3,
        "concern": null,
        "curiosity": 0.5,
        "warmth": 0.7,
        "tension": null
      }
    }
  ],
  "total": 42,
  "offset": 0,
  "limit": 5
}
```

---

### GET /insights/search

Search insights by content.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query (min 2 chars) |
| `category` | string | — | Filter by category |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
curl "http://localhost:8000/insights/search?q=music&limit=10"
```

---

### GET /insights/{topic_key}

Get insights for a specific topic.

**Path Parameters:**
- `topic_key` — The topic key (e.g., `server:123:user:456`)

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile` | string | balanced | Retrieval profile |
| `limit` | int | 10 | Maximum results (1-100) |
| `include_quarantined` | bool | false | Include quarantined insights |

**Retrieval Profiles:**
- `recent` — Emphasizes recency
- `balanced` — Mix of recent and strong
- `deep` — Emphasizes strength/importance
- `comprehensive` — Broad historical view

**Example:**
```bash
curl "http://localhost:8000/insights/server:123:user:456?profile=recent&limit=5"
```

---

## Salience

### GET /salience

List topics by salience balance (descending).

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `group` | string | — | Filter by budget group |
| `limit` | int | 50 | Maximum results (1-200) |

**Budget Groups:**
- `social` — Server users, dyads
- `global` — Global users, global dyads
- `spaces` — Channels, threads
- `semantic` — Subjects
- `culture` — Emoji
- `self` — Self topics

**Example:**
```bash
curl "http://localhost:8000/salience?group=social&limit=10"
```

**Response:**
```json
[
  {
    "topic_key": "server:123:user:456",
    "balance": 45.2,
    "cap": 100,
    "last_activity": "2024-01-15T09:30:00.000000Z",
    "budget_group": "social"
  }
]
```

---

### GET /salience/groups

Get summary of each budget group.

**Response:**
```json
[
  {
    "group": "social",
    "allocation": 0.30,
    "total_salience": 234.5,
    "topic_count": 42,
    "top_topics": [
      {
        "topic_key": "server:123:user:456",
        "balance": 45.2,
        "cap": 100,
        "last_activity": "2024-01-15T09:30:00.000000Z",
        "budget_group": "social"
      }
    ]
  }
]
```

---

### GET /salience/{topic_key}

Get salience details for a specific topic.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transaction_limit` | int | 20 | Max transactions to return |

**Example:**
```bash
curl "http://localhost:8000/salience/server:123:user:456"
```

**Response:**
```json
{
  "topic_key": "server:123:user:456",
  "balance": 45.2,
  "cap": 100,
  "utilization": 0.452,
  "last_activity": "2024-01-15T09:30:00.000000Z",
  "budget_group": "social",
  "recent_transactions": [
    {
      "id": "01HN...",
      "topic_key": "server:123:user:456",
      "transaction_type": "earn",
      "amount": 1.0,
      "reason": "message",
      "source_topic": null,
      "created_at": "2024-01-15T09:30:00.000000Z"
    }
  ]
}
```

---

## Layer Runs

### GET /runs

List recent layer runs.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `layer_name` | string | — | Filter by layer name |
| `status` | string | — | Filter by status |
| `since` | datetime | — | Only runs after this time |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 20 | Maximum results (1-100) |

**Status values:**
- `success` — Completed successfully
- `failed` — Error occurred
- `dry` — Completed but produced no insights

**Example:**
```bash
curl "http://localhost:8000/runs?layer_name=nightly-user-reflection&limit=5"
```

**Response:**
```json
{
  "runs": [
    {
      "id": "01HN...",
      "layer_name": "nightly-user-reflection",
      "status": "success",
      "started_at": "2024-01-15T03:00:00.000000Z",
      "completed_at": "2024-01-15T03:02:30.000000Z",
      "duration_seconds": 150.5,
      "targets_processed": 12,
      "insights_created": 12,
      "tokens_total": 8543,
      "estimated_cost_usd": 0.0234
    }
  ],
  "total": 30,
  "offset": 0,
  "limit": 5
}
```

---

### GET /runs/stats/summary

Get aggregate statistics for recent runs.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 7 | Number of days to include (1-30) |

**Response:**
```json
{
  "period_days": 7,
  "total_runs": 14,
  "successful_runs": 12,
  "failed_runs": 1,
  "dry_runs": 1,
  "total_insights": 120,
  "total_tokens": 45000,
  "total_cost_usd": 0.15,
  "by_layer": {
    "nightly-user-reflection": {
      "runs": 7,
      "insights": 84
    },
    "weekly-self-reflection": {
      "runs": 1,
      "insights": 1
    }
  }
}
```

---

### GET /runs/{run_id}

Get details of a specific layer run.

**Response:**
```json
{
  "id": "01HN...",
  "layer_name": "nightly-user-reflection",
  "layer_hash": "a1b2c3d4...",
  "status": "success",
  "started_at": "2024-01-15T03:00:00.000000Z",
  "completed_at": "2024-01-15T03:02:30.000000Z",
  "duration_seconds": 150.5,
  "targets_matched": 15,
  "targets_processed": 12,
  "targets_skipped": 3,
  "insights_created": 12,
  "model_profile": "reflection",
  "model_provider": "anthropic",
  "model_name": "claude-sonnet-4-20250514",
  "tokens_input": 7000,
  "tokens_output": 1543,
  "tokens_total": 8543,
  "estimated_cost_usd": 0.0234,
  "errors": null
}
```

---

## Development Endpoints

These endpoints are only available when `development.dev_mode: true` in config.

### POST /dev/insights

Create a new insight manually.

### PATCH /dev/insights/{insight_id}

Update an existing insight.

### DELETE /dev/insights/{insight_id}

Delete an insight (hard delete).

### POST /dev/insights/bulk-delete

Bulk delete insights matching criteria.

### GET /dev/create-insight

HTML form for manual insight creation.

---

## Web UI

The web UI provides a browser-based interface for exploring Zos data at `/ui/`.

### Navigation

| Path | Description |
|------|-------------|
| `/ui/` | Dashboard with top topics, recent insights, and recent runs |
| `/ui/messages` | Browse and search stored messages |
| `/ui/insights` | Browse and search insights by category |
| `/ui/users` | Browse users sorted by insight count |
| `/ui/channels` | Browse channels sorted by message count |
| `/ui/salience` | View salience balances by budget group |
| `/ui/budget` | Track API costs, token usage, and spending over time |
| `/ui/runs` | View layer run history and statistics |

### Users Browser

The users browser (`/ui/users`) displays all tracked users sorted by insight count.

**Features:**
- Search users by name
- Click a user to see their detail page with:
  - Overview stats (messages, bio, pronouns, join date)
  - Insights about this user
  - Relationship insights (dyads involving this user)
  - Recent messages
- Links to filtered message views

### Channels Browser

The channels browser (`/ui/channels`) displays all tracked channels sorted by message count.

**Features:**
- Search channels by name
- Click a channel to see its detail page with:
  - Overview stats (messages, active users, type, created date)
  - Related insights
  - Recent messages
  - Top users by message count
- Links to filtered message views

### Budget Dashboard

The budget dashboard (`/ui/budget`) provides cost tracking and visualization.

**Features:**
- Summary cards showing total cost, tokens, runs, calls, and insights (30 days)
- Daily cost chart with bar visualization
- Cost breakdown by layer (percentage of total, tokens, runs, insights)
- Cost breakdown by model (provider, profile, tokens in/out, calls)
- Cost breakdown by call type (reflection, vision, conversation, etc.)
- All data filterable by time period (default 30 days)

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message describing the problem"
}
```

**Common status codes:**
- `400` — Bad request (invalid parameters)
- `403` — Forbidden (dev mode not enabled)
- `404` — Not found
- `500` — Internal server error
