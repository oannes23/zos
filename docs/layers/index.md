# Understanding Layers

Layers are Zos's cognitive pipelines — declarative definitions of how observations become understanding.

---

## What Are Layers?

A layer is a YAML file that defines:
- **When** to run (schedule or trigger)
- **What** to process (target selection)
- **How** to process (node sequence)
- **Where** to store results (insight storage)

Layers make cognition inspectable. You can read a layer file and understand exactly what the system does when it "thinks about" users, relationships, or itself.

---

## Why Declarative Cognition?

Traditional systems bury their reasoning in code. Layers externalize it:

- **Inspectable**: Read what the system does
- **Modifiable**: Change behavior without changing code
- **Auditable**: Every run is tracked with its layer hash
- **Eventually self-modifiable**: The system can propose changes to its own cognition

---

## Layer Types

### Reflection Layers

Scheduled processing that converts observations into insights.

- Run on cron schedules (typically nightly)
- Process batches of topics by salience
- Produce insights that persist
- Spend salience budget

Reflection is the "nighttime" mode — analogous to sleep consolidation.

### Conversation Layers (MVP 1)

Real-time response triggered by impulse.

- Triggered when chattiness exceeds threshold
- Process single context (message, channel)
- Produce speech output
- Draw on accumulated insights

Conversation is the "waking" mode.

---

## Layer Execution Flow

```
1. Trigger (schedule or manual)
       ↓
2. Target Selection (salience-based)
       ↓
3. For each target:
   ├── Fetch context (messages, insights)
   ├── LLM processing (reflection)
   └── Store results (insights)
       ↓
4. Audit (layer run record)
```

---

## Documentation

- [Anatomy of a Layer](anatomy-of-a-layer.md) — Layer YAML structure explained
- [Built-in Layers](built-in-layers.md) — The default layers
- [Reflection Flow](reflection-flow.md) — Visual walkthrough of reflection

---

## Quick Reference

### List Available Layers

```bash
zos layer list
```

### Validate a Layer

```bash
zos layer validate nightly-user-reflection
```

### Trigger Manually

```bash
zos reflect trigger nightly-user-reflection
```

### View Scheduled Jobs

```bash
zos reflect jobs
```
