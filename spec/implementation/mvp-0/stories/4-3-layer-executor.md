# Story 4.3: Sequential Layer Executor

**Epic**: Reflection
**Status**: 🟢 Complete
**Estimated complexity**: Large

## Goal

Implement the sequential pipeline executor that processes layer nodes in order, passing context between them.

## Acceptance Criteria

- [x] Nodes execute in sequence
- [x] Context dict passes between nodes
- [x] Each node type has a handler
- [x] Errors are caught and logged (fail-forward)
- [x] Layer run records created with full audit
- [x] Tokens tracked per run
- [x] Dry runs detected and logged

## Technical Notes

### Executor Architecture

```python
# src/zos/executor.py
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

@dataclass
class ExecutionContext:
    """Context passed between nodes during execution."""
    topic: Topic
    layer: Layer
    run_id: str

    # Accumulated data
    messages: list[Message] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    llm_response: str | None = None

    # Tracking
    tokens_input: int = 0
    tokens_output: int = 0
    errors: list[dict] = field(default_factory=list)

    def add_tokens(self, input: int, output: int):
        self.tokens_input += input
        self.tokens_output += output

class LayerExecutor:
    """Executes layer pipelines sequentially."""

    def __init__(
        self,
        db: Database,
        ledger: SalienceLedger,
        templates: TemplateEngine,
        llm: ModelClient,
        config: Config,
    ):
        self.db = db
        self.ledger = ledger
        self.templates = templates
        self.llm = llm
        self.config = config

        # Node handlers
        self.handlers = {
            NodeType.FETCH_MESSAGES: self._handle_fetch_messages,
            NodeType.FETCH_INSIGHTS: self._handle_fetch_insights,
            NodeType.LLM_CALL: self._handle_llm_call,
            NodeType.STORE_INSIGHT: self._handle_store_insight,
            NodeType.REDUCE: self._handle_reduce,
            NodeType.OUTPUT: self._handle_output,
            NodeType.SYNTHESIZE_TO_GLOBAL: self._handle_synthesize_to_global,
            NodeType.UPDATE_SELF_CONCEPT: self._handle_update_self_concept,
        }
```

### Main Execution Loop

```python
    async def execute_layer(
        self,
        layer: Layer,
        topics: list[str],
    ) -> LayerRun:
        """Execute a layer for the given topics."""
        run_id = generate_id()
        started_at = datetime.utcnow()

        insights_created = 0
        targets_processed = 0
        targets_skipped = 0
        all_errors = []

        total_tokens_input = 0
        total_tokens_output = 0

        for topic_key in topics:
            topic = await self.db.get_topic(topic_key)
            if not topic:
                continue

            ctx = ExecutionContext(
                topic=topic,
                layer=layer,
                run_id=run_id,
            )

            try:
                # Execute each node in sequence
                for node in layer.nodes:
                    await self._execute_node(node, ctx)

                targets_processed += 1
                total_tokens_input += ctx.tokens_input
                total_tokens_output += ctx.tokens_output

                # Count insights created for this topic
                insights_created += len([
                    i for i in ctx.insights
                    if i.layer_run_id == run_id
                ])

            except Exception as e:
                log.warning(
                    "topic_execution_failed",
                    topic=topic_key,
                    layer=layer.name,
                    error=str(e),
                )
                targets_skipped += 1
                all_errors.append({
                    'topic': topic_key,
                    'error': str(e),
                    'node': node.name if node else None,
                })
                # Continue with next topic (fail-forward)

        # Determine status
        if targets_skipped == len(topics):
            status = LayerRunStatus.FAILED
        elif targets_skipped > 0:
            status = LayerRunStatus.PARTIAL
        elif insights_created == 0:
            status = LayerRunStatus.DRY
        else:
            status = LayerRunStatus.SUCCESS

        # Create run record
        run = LayerRun(
            id=run_id,
            layer_name=layer.name,
            layer_hash=self.loader.get_hash(layer.name),
            started_at=started_at,
            completed_at=datetime.utcnow(),
            status=status,
            targets_matched=len(topics),
            targets_processed=targets_processed,
            targets_skipped=targets_skipped,
            insights_created=insights_created,
            model_profile=self._get_primary_model_profile(layer),
            model_provider=None,  # Set by LLM call
            model_name=None,
            tokens_input=total_tokens_input,
            tokens_output=total_tokens_output,
            tokens_total=total_tokens_input + total_tokens_output,
            estimated_cost_usd=self._estimate_cost(
                total_tokens_input, total_tokens_output
            ),
            errors=all_errors if all_errors else None,
        )

        await self.db.insert_layer_run(run)

        log.info(
            "layer_executed",
            layer=layer.name,
            status=status.value,
            targets=targets_processed,
            insights=insights_created,
        )

        return run

    async def _execute_node(self, node: Node, ctx: ExecutionContext):
        """Execute a single node."""
        handler = self.handlers.get(node.type)
        if not handler:
            raise ValueError(f"Unknown node type: {node.type}")

        log.debug(
            "executing_node",
            node=node.name,
            type=node.type.value,
            topic=ctx.topic.key,
        )

        await handler(node, ctx)
```

### Node Handlers

```python
    async def _handle_fetch_messages(self, node: Node, ctx: ExecutionContext):
        """Fetch messages for the topic."""
        params = node.params
        lookback_hours = params.get('lookback_hours', 24)
        limit = params.get('limit_per_channel', 50)

        since = datetime.utcnow() - timedelta(hours=lookback_hours)

        messages = await self.db.get_messages_for_topic(
            ctx.topic.key,
            since=since,
            limit=limit,
        )

        ctx.messages = messages

    async def _handle_fetch_insights(self, node: Node, ctx: ExecutionContext):
        """Fetch prior insights for the topic."""
        params = node.params
        profile = params.get('retrieval_profile', 'balanced')
        max_per_topic = params.get('max_per_topic', 5)

        insights = await self.db.get_insights_for_topic(
            ctx.topic.key,
            profile=profile,
            limit=max_per_topic,
        )

        ctx.insights = insights

    async def _handle_llm_call(self, node: Node, ctx: ExecutionContext):
        """Call the LLM with rendered prompt."""
        params = node.params
        template_path = params['prompt_template']
        model_profile = params.get('model', 'default')
        max_tokens = params.get('max_tokens', 500)

        # Render template
        prompt = self.templates.render(
            template_path,
            {
                'topic': ctx.topic,
                'messages': format_messages_for_prompt(ctx.messages, {}),
                'insights': format_insights_for_prompt(ctx.insights),
            }
        )

        # Call LLM
        response, usage = await self.llm.complete(
            prompt=prompt,
            model_profile=model_profile,
            max_tokens=max_tokens,
        )

        ctx.llm_response = response
        ctx.add_tokens(usage.input_tokens, usage.output_tokens)

    async def _handle_store_insight(self, node: Node, ctx: ExecutionContext):
        """Parse LLM response and store insight."""
        params = node.params
        category = params['category']

        if not ctx.llm_response:
            raise ValueError("No LLM response to store")

        # Parse JSON from response
        insight_data = self._parse_insight_response(ctx.llm_response)

        # Calculate salience spent
        salience_spent = await self.ledger.spend(
            ctx.topic.key,
            ctx.tokens_input * self.config.salience.cost_per_token,
            reason=f"reflection:{ctx.run_id}",
        )

        # Create insight
        insight = Insight(
            id=generate_id(),
            topic_key=ctx.topic.key,
            category=category,
            content=insight_data['content'],
            sources_scope_max=self._determine_scope(ctx.messages),
            created_at=datetime.utcnow(),
            layer_run_id=ctx.run_id,
            salience_spent=salience_spent,
            strength_adjustment=insight_data.get('strength_adjustment', 1.0),
            strength=salience_spent * insight_data.get('strength_adjustment', 1.0),
            confidence=insight_data.get('confidence', 0.5),
            importance=insight_data.get('importance', 0.5),
            novelty=insight_data.get('novelty', 0.5),
            valence_joy=insight_data.get('valence', {}).get('joy'),
            valence_concern=insight_data.get('valence', {}).get('concern'),
            valence_curiosity=insight_data.get('valence', {}).get('curiosity'),
            valence_warmth=insight_data.get('valence', {}).get('warmth'),
            valence_tension=insight_data.get('valence', {}).get('tension'),
        )

        await self.db.insert_insight(insight)
        ctx.insights.append(insight)

    def _parse_insight_response(self, response: str) -> dict:
        """Parse JSON insight from LLM response."""
        import json
        import re

        # Find JSON block in response
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # Try parsing whole response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback: extract content as plain text
            return {
                'content': response,
                'confidence': 0.5,
                'importance': 0.5,
                'novelty': 0.5,
                'strength_adjustment': 1.0,
                'valence': {'curiosity': 0.5},
            }
```

### Self-Concept Update Handler

```python
    async def _handle_update_self_concept(self, node: Node, ctx: ExecutionContext):
        """Update the self-concept document."""
        params = node.params
        document_path = Path(params['document_path'])

        if not ctx.llm_response:
            raise ValueError("No LLM response to write")

        # Write the new self-concept
        document_path.write_text(ctx.llm_response)

        log.info(
            "self_concept_updated",
            path=str(document_path),
        )
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/executor.py` | LayerExecutor class |
| `tests/test_executor.py` | Executor tests |

## Test Cases

1. Nodes execute in sequence
2. Context passes between nodes
3. LLM call stores tokens
4. Insight parsed and stored
5. Error in one topic doesn't stop others
6. Dry run detected correctly
7. Layer run record created

## Definition of Done

- [x] All node types have handlers
- [x] Fail-forward works
- [x] Layer runs recorded
- [x] Token tracking accurate

---

## Design Decisions (Resolved 2026-01-23)

### Q1: LLM Response Parsing
**Decision**: Accept graceful fallback with defaults
- Always produce *something* — accept content as plain text with default metrics (0.5)
- Audit quality separately during prompt development
- Good for early iteration — never lose content, fix metrics later
- Log fallback cases for prompt tuning

### Q2: Salience Spending Point
**Decision**: On success only
- Failed attempts are "free" — topics can retry without draining budget
- Add retry limit per topic per cycle to prevent infinite attempts
- Rationale: failures shouldn't penalize topics that were important enough to select

**Implementation note**: Track attempts per topic per layer run, cap at configurable limit (e.g., 3)

### Q3: Context Window Limits
**Decision**: Per-topic truncation via node params
- Layer YAML specifies limits: `limit_per_channel: 50`, `max_per_topic: 5`
- If prompt still exceeds context, truncate oldest content
- Log when truncation occurs for visibility
- More sophisticated token estimation is post-MVP enhancement

### Q4: Node Failure Granularity
**Decision**: Skip topic (current)
- Any node failure = abandon topic for this cycle
- Simple, predictable behavior
- Fetched data is minimal cost compared to LLM calls
- Partial context could produce confusing insights

---

## Additional Decisions (Resolved 2026-01-24)

### Q5: Messages for Topic — Selection Logic
**Decision**: Topic-type-specific selection

| Topic Type | Message Selection |
|------------|-------------------|
| **user:X** | Messages in threads the user participated in (broader context) |
| **channel:X** | Messages where `channel_id == X` (straightforward) |
| **dyad:A:B** | Messages by A or B where reply_to is the other, OR in same thread together (captures interaction) |
| **subject:X** | Two-phase: (1) messages linked via `subject_message_sources` junction table, (2) recent messages from source topics (users/channels that surfaced the subject) |
| **self:zos** | Self-insights and layer run logs (no messages in MVP 0) |

**Implementation**:
```python
async def get_messages_for_topic(self, topic_key: str, since: datetime, limit: int) -> list[Message]:
    category = extract_category(topic_key)

    if category == 'user':
        user_id = extract_user_id(topic_key)
        # Get threads user participated in
        thread_ids = await self.get_user_thread_ids(user_id, since)
        return await self.get_messages_in_threads(thread_ids, since, limit)

    elif category == 'channel':
        channel_id = extract_channel_id(topic_key)
        return await self.get_messages_by_channel(channel_id, since, limit)

    elif category == 'dyad':
        user_a, user_b = extract_dyad_users(topic_key)
        return await self.get_dyad_messages(user_a, user_b, since, limit)

    elif category == 'subject':
        # Phase 1: Messages directly associated via subject_message_sources junction table
        # Phase 2: Recent messages from source topics (users/channels that surfaced this subject)
        return await self.get_subject_messages_two_phase(topic_key, since, limit)
```

### Q6: Topic-Specific Message Context Limits
**Decision**: Generic `limit` parameter
- Layer YAML uses generic `limit` (or `max_messages`)
- The selection logic handles topic-type-specific semantics
- Same limit applies regardless of topic type — simpler configuration

---

**Requires**: Stories 4.1, 4.2, 4.4 (layers, templates, LLM)
**Blocks**: Stories 4.6-4.8 (layers need executor)
