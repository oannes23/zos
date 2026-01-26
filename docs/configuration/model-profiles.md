# Model Profiles

Configure which LLM models Zos uses for different tasks.

---

## Overview

Model profiles provide a layer of indirection between what Zos wants to do (reflect, converse, review) and which specific model does it. This enables:

- **Cost optimization** — Use cheaper models for simple tasks
- **Capability matching** — Use powerful models where needed
- **Easy swapping** — Change models without touching layers
- **Provider flexibility** — Mix providers as needed

---

## Configuration Structure

```yaml
models:
  profiles:
    # Base profiles (actual models)
    simple:
      provider: anthropic
      model: claude-3-5-haiku-20241022
    moderate:
      provider: anthropic
      model: claude-sonnet-4-20250514
    complex:
      provider: anthropic
      model: claude-opus-4-20250514

    # Semantic aliases (reference other profiles)
    default: moderate
    reflection: moderate
    conversation: moderate
    synthesis: complex
    self_reflection: complex
    review: simple
    vision: moderate

  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
```

---

## Base Profiles

Base profiles map directly to provider/model combinations:

```yaml
simple:
  provider: anthropic
  model: claude-3-5-haiku-20241022
```

### Recommended Base Profiles

| Profile | Provider | Model | Use For |
|---------|----------|-------|---------|
| `simple` | anthropic | claude-3-5-haiku | Fast, cheap tasks |
| `moderate` | anthropic | claude-sonnet-4 | Balanced performance |
| `complex` | anthropic | claude-opus-4 | Deep reasoning |

---

## Semantic Aliases

Aliases reference other profiles, enabling task-based configuration:

```yaml
reflection: moderate      # User reflection uses moderate
self_reflection: complex  # Self-reflection needs deep reasoning
review: simple            # Output review is fast check
```

Layers reference these semantic names:

```yaml
# In a layer file
- name: reflect
  type: llm_call
  params:
    model: reflection    # Uses whatever "reflection" maps to
```

### Standard Semantic Aliases

| Alias | Purpose | Typical Mapping |
|-------|---------|-----------------|
| `default` | Fallback | moderate |
| `reflection` | User/topic reflection | moderate |
| `conversation` | Real-time responses | moderate |
| `synthesis` | Consolidating insights | complex |
| `self_reflection` | Self-understanding | complex |
| `review` | Output privacy check | simple |
| `vision` | Image analysis | moderate |

---

## Providers

Configure API access per provider:

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
  openai:
    api_key_env: OPENAI_API_KEY
```

### Anthropic

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
```

Available models:
- `claude-3-5-haiku-20241022` — Fast, affordable
- `claude-sonnet-4-20250514` — Balanced
- `claude-opus-4-20250514` — Most capable

### OpenAI (if needed)

```yaml
providers:
  openai:
    api_key_env: OPENAI_API_KEY
```

Available models:
- `gpt-4o` — Capable, multimodal
- `gpt-4o-mini` — Faster, cheaper

---

## Cost Optimization

### By Task Type

Map tasks to appropriate capability levels:

| Task | Recommended | Rationale |
|------|-------------|-----------|
| Output review | simple | Yes/no decision |
| User reflection | moderate | Nuanced but bounded |
| Self-reflection | complex | Deep introspection |
| Synthesis | complex | Reconciling conflicts |
| Vision | moderate | Description generation |

### Example Cost-Optimized Config

```yaml
profiles:
  # Cheap base
  simple:
    provider: anthropic
    model: claude-3-5-haiku-20241022

  # Mid-tier
  moderate:
    provider: anthropic
    model: claude-sonnet-4-20250514

  # Premium (use sparingly)
  complex:
    provider: anthropic
    model: claude-opus-4-20250514

  # Task mappings
  reflection: moderate
  conversation: moderate
  review: simple          # Cheap for simple checks
  self_reflection: complex  # Worth the cost
  synthesis: complex
```

---

## Changing Models

To swap a model across all tasks using it:

1. Update the base profile:
   ```yaml
   moderate:
     provider: anthropic
     model: claude-sonnet-4-20250514  # Change this
   ```

2. All aliases pointing to `moderate` automatically use the new model

To change a specific task without affecting others:

1. Create a new base profile
2. Update the semantic alias

---

## Resolution Chain

Profiles are resolved through aliases:

```
reflection → moderate → { provider: anthropic, model: claude-sonnet-4 }
```

Circular aliases are detected and rejected.

---

## Validation

Check your model configuration:

```bash
zos config check
```

Output shows:
```
Model profiles: 9
Model aliases: reflection, conversation, synthesis, self_reflection, review, vision, default
```

---

## Troubleshooting

### "Unknown model profile"

The layer references a profile that doesn't exist.

```yaml
# Layer file
model: reflection_deep  # Doesn't exist!

# Add to config.yaml
profiles:
  reflection_deep: complex
```

### "API key not found"

The provider's API key environment variable isn't set.

```bash
export ANTHROPIC_API_KEY=your_key
```

### High costs

- Check which profiles map to `complex`
- Consider mapping more tasks to `moderate` or `simple`
- Review layer `max_targets` settings
- Monitor via `/runs/stats/summary`
