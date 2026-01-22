# Data Model

**Status**: 🔴 Not started
**Last verified**: —

---

## Overview

This document defines the core entities, their relationships, and storage approach.

---

## Entity Relationship Summary

```
<!-- ASCII diagram of entity relationships -->
{{Entity A}} ─────< {{Entity B}}
     │
     └────< {{Entity C}}
```

---

## Core Entities

### {{Entity 1}}

**Purpose**: {{Why this entity exists}}

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Primary key |
| {{field}} | {{type}} | {{yes/no}} | {{notes}} |

**Relationships**:
- Has many: {{Related entity}}
- Belongs to: {{Parent entity}}

### {{Entity 2}}

**Purpose**: {{Why this entity exists}}

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Primary key |

---

## Storage Approach

### MVP 0
- {{Storage choice and rationale}}

### MVP 1
- {{Upgraded storage if applicable}}

---

## ID Strategy

- **Format**: {{UUID/ULID/sequential}}
- **Rationale**: {{Why this format}}

---

## Indexing Strategy

| Entity | Index | Purpose |
|--------|-------|---------|
| {{Entity}} | {{fields}} | {{query pattern}} |

---

_Last updated: 2026-01-22_
