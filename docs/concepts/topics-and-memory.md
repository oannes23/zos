# Topics and Memory

How Zos organizes understanding around canonical entities.

---

## What Are Topics?

Topics are the entities Zos can think about — the units around which understanding accumulates.

Every insight attaches to exactly one primary topic. Topics provide consistent keys for:
- Earning salience
- Storing insights
- Retrieving context
- Tracking relationships

---

## Topic Keys

Topics are identified by string keys with parseable structure:

### Social Topics

```
server:123:user:456           # A person in a server
server:123:channel:789        # A space
server:123:thread:012         # A nested conversation
server:123:role:345           # A Discord role
server:123:dyad:456:789       # A relationship (IDs sorted)
server:123:user_in_channel:789:456  # Person's presence in a space
server:123:dyad_in_channel:789:456:012  # Relationship in context
```

### Semantic Topics

```
server:123:subject:music      # An emergent theme
server:123:emoji:custom_123   # A custom emoji
```

### Self Topics

```
self:zos                      # Global self-understanding
server:123:self:zos           # Contextual self in a community
```

### Global Topics

```
user:456                      # Unified understanding across servers
dyad:456:789                  # Unified relationship understanding
```

---

## Topic Categories

Each topic belongs to a category:

| Category | Examples | Description |
|----------|----------|-------------|
| user | server:123:user:456 | Individual people |
| dyad | server:123:dyad:456:789 | Relationships |
| channel | server:123:channel:789 | Spaces |
| thread | server:123:thread:012 | Nested conversations |
| subject | server:123:subject:music | Emergent themes |
| role | server:123:role:345 | Discord roles |
| emoji | server:123:emoji:custom | Custom emoji |
| self | self:zos | Self-understanding |

Categories affect:
- Which reflection layers process the topic
- Budget group allocation
- Salience caps

---

## Server-Scoped vs Global

Most topics are server-scoped:
```
server:123:user:456   # Alice in Server A
server:789:user:456   # Alice in Server B
```

These are distinct topics. Zos may understand Alice differently in different contexts.

Global topics unify cross-server understanding:
```
user:456              # Alice across all servers
dyad:456:789          # Alice-Bob relationship across servers
self:zos              # Core identity
```

Global topics receive:
- DM-derived insights directly
- Synthesized understanding from server-scoped insights

---

## Understanding Accumulation

Insights accumulate on topics over time:

```
Topic: server:123:user:456 (Alice)

Insight 1 (Day 1):
  "Alice expresses enthusiasm about photography..."

Insight 2 (Day 5):
  "I notice Alice offers encouragement to newcomers..."

Insight 3 (Day 12):
  "Alice has a careful way of disagreeing..."
```

Insights are append-only — new understanding creates new records. The full history is preserved.

### Retrieval Profiles

When retrieving understanding, profiles balance recency and strength:

| Profile | Emphasis |
|---------|----------|
| recent | Newer insights |
| balanced | Mix of recent and strong |
| deep | Strong/important insights |
| comprehensive | Broad historical view |

---

## Hierarchical Topics

Some topics have hierarchical relationships:

```
user:456                      # Global Alice
├── server:123:user:456       # Alice in Server A
└── server:789:user:456       # Alice in Server B

self:zos                      # Core identity
├── server:123:self:zos       # Zos in Server A
└── server:789:self:zos       # Zos in Server B
```

Understanding flows:
- **Up**: Server-scoped insights synthesize to global topics
- **Down**: Global understanding informs server-scoped responses

---

## Dyads

Relationship topics track pairs of users:

```
server:123:dyad:456:789
```

User IDs are sorted alphabetically, so the dyad is canonical regardless of who initiated.

Dyads capture:
- Interaction patterns
- Relationship dynamics
- Asymmetry metrics (who initiates more, etc.)

---

## Subject Topics

Subject topics represent emergent themes:

```
server:123:subject:photography
server:123:subject:cooking
```

Subject names are LLM-generated during reflection. Subjects are:
- Server-scoped (not global)
- Subject to consolidation pressure
- Created when themes emerge across conversations

---

## Provisional Topics

Topics can be created provisionally when:
- An insight references a non-existent topic
- A subject is first mentioned
- Cross-references are discovered

Provisional topics are marked for review and either:
- Promoted (flag removed)
- Merged with similar topics
- Deleted if spurious

---

## Memory Characteristics

### Persistence

Understanding never disappears:
- Insights are append-only
- Deleted messages are soft-deleted (retained for context)
- History is always available

### Forgetting

Natural forgetting through:
- Salience decay (attention fades)
- Effective strength reduction (insights become dimmer)
- Retrieval prioritization (strong insights surface)

### Consolidation

Understanding consolidates through:
- Regular reflection (daily, weekly)
- Synthesis of conflicting insights
- Self-concept updates

---

## Topic Discovery

Topics are created automatically when:
- A user sends a message (user topic)
- A channel is polled (channel topic)
- A thread is encountered (thread topic, if enabled)
- Two users interact (dyad topic)
- A subject emerges (subject topic)

Operators don't manually create topics — they emerge from observation.

---

## Viewing Topics

Via API:
```bash
# Top topics by salience
curl http://localhost:8000/salience

# Insights for a topic
curl http://localhost:8000/insights/server:123:user:456
```

Via Discord:
```
/topics          # List top topics by salience
/insights alice  # Show insights for a topic
```
