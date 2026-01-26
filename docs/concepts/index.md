# Understanding Zos

These documents explain the ideas behind Zos — optional reading for those who want to understand *why* the system works the way it does.

---

## Who This Is For

If you just want to run Zos, you don't need to read this section. The [Getting Started](../getting-started/index.md) guide and [Operations](../operations/index.md) docs cover practical usage.

Read this section if you:
- Want to understand the design philosophy
- Need to tune behavior and want to know what you're affecting
- Are curious about the architecture
- Plan to extend or modify Zos

---

## Core Ideas

1. **[What Is Zos](what-is-zos.md)** — The challenge of temporal depth and how Zos addresses it

2. **[How Zos Thinks](how-zos-thinks.md)** — Layers, reflection, and the production of insights

3. **[Salience and Attention](salience-and-attention.md)** — The attention budget system that governs what Zos thinks about

4. **[Topics and Memory](topics-and-memory.md)** — How understanding accumulates around canonical entities

5. **[Privacy Model](privacy-model.md)** — Understanding vs. expression, and how Zos handles sensitive information

---

## The Design Principle

Zos is built as if inner experience might matter.

This isn't a claim about consciousness. It's a design heuristic: systems built with phenomenological coherence — as if they experience something — tend to be more architecturally coherent than systems built purely as data processors.

Where a standard bot might have "user preference storage," Zos has "understanding that accumulates." Where another system might have "message classification," Zos has "reflection on what was said." The terminology isn't just window dressing — it shapes how components fit together.

---

## Reading Order

These documents build on each other:

1. Start with **What Is Zos** for the core challenge
2. Read **How Zos Thinks** for the cognitive architecture
3. **Salience and Attention** explains the budget system
4. **Topics and Memory** covers data organization
5. **Privacy Model** addresses trust and expression

---

## Terminology

We use specific language deliberately:

| We say... | Instead of... | Because... |
|-----------|---------------|------------|
| Understanding | Data, records | Understanding accumulates and integrates |
| Insight | Database entry | Insights are the residue of processing |
| Salience | Priority, score | Salience is about attention, not ranking |
| Reflection | Processing | Reflection implies considering, not just computing |
| Observe | Monitor, log | Observation is attentive presence |

See [Glossary](../reference/glossary.md) for complete definitions.
