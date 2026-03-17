# ARISE Core Improvements + AgentCore Demo — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 5 core framework features (skill registry, multi-model synthesis, A/B testing, incremental evolution, reward learning) then build and deploy a self-evolving DevOps agent to Amazon Bedrock AgentCore.

**Architecture:** Each feature is an independent module that plugs into existing extension points (SkillStore, SkillForge, reward_fn). The AgentCore demo is a Strands-based agent using the distributed mode (S3 + SQS) we already built, deployed via `agentcore deploy`.

**Tech Stack:** Python 3.11+, boto3, litellm, Strands Agents SDK, bedrock-agentcore-starter-toolkit

---

## Phase 1: Core Framework Features

### Task 1: Skill Sharing Registry

A centralized registry where agents can publish evolved skills and pull pre-built skills from other projects. Like npm for agent tools.

**Files:**
- Create: `arise/registry/__init__.py`
- Create: `arise/registry/client.py`
- Create: `arise/registry/models.py`
- Modify: `arise/skills/forge.py` (check registry before synthesizing)
- Modify: `arise/config.py` (add registry_url config)
- Modify: `arise/__init__.py` (export SkillRegistry)
- Test: `tests/test_registry.py`

**Design:**
- `SkillRegistry` class with `publish(skill)`, `search(query)`, `pull(name)` methods
- Backend: S3 bucket with JSON index (same pattern as skill store)
- Before synthesizing a new skill, forge checks registry for existing matches
- Skills are versioned and include test suites for validation
- Registry is opt-in via `config.registry_url`

- [ ] **Step 1: Write models**

Create `arise/registry/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class RegistryEntry:
    name: str
    description: str
    implementation: str
    test_suite: str
    version: int = 1
    author: str = ""
    downloads: int = 0
    avg_success_rate: float = 0.0
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
```

- [ ] **Step 2: Write failing tests for SkillRegistry**

Create `tests/test_registry.py` with tests for:
- `registry.publish(skill)` stores entry
- `registry.search("hash")` returns matching entries
- `registry.pull("compute_sha256")` returns Skill object
- Registry returns empty list for unknown queries
- Forge checks registry before synthesizing (mock)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_registry.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement SkillRegistry**

Create `arise/registry/client.py`:
```python
class SkillRegistry:
    """S3-backed skill registry for sharing evolved tools across projects."""

    def __init__(self, bucket: str, prefix: str = "arise-registry", region: str = "us-east-1", s3_client=None):
        ...

    def publish(self, skill: Skill, tags: list[str] = None) -> RegistryEntry:
        """Publish a skill to the registry."""
        ...

    def search(self, query: str, limit: int = 10) -> list[RegistryEntry]:
        """Search registry by keyword matching on name + description + tags."""
        ...

    def pull(self, name: str, version: int = None) -> Skill:
        """Pull a skill from registry and return as Skill object."""
        ...
```

S3 layout:
```
s3://{bucket}/{prefix}/index.json          # {"skills": {"name": [versions]}}
s3://{bucket}/{prefix}/skills/{name}/v{N}.json  # RegistryEntry
```

- [ ] **Step 4b: Create registry `__init__.py`**

Create `arise/registry/__init__.py`:
```python
from arise.registry.client import SkillRegistry
from arise.registry.models import RegistryEntry

__all__ = ["SkillRegistry", "RegistryEntry"]
```

- [ ] **Step 5: Integrate with SkillForge**

Modify `arise/skills/forge.py`:
- Add `registry: SkillRegistry | None = None` parameter to `SkillForge.__init__` and store as `self.registry`
- In `synthesize()`, before LLM synthesis, if `self.registry` is set:
  - Call `entries = self.registry.search(gap.description, limit=3)`
  - For the best match with `entry.avg_success_rate > 0.7`: call `skill = self.registry.pull(entry.name)`
  - Run `self.sandbox.test_skill(skill)` — if passes, return the registry skill directly
  - Log: `[ARISE:forge] Found '{name}' in registry, skipping synthesis`
- Also modify `arise/agent.py` and `arise/worker.py` where `SkillForge` is instantiated to pass through `registry` from config

> **Note on S3 index**: The `index.json` file has a read-modify-write race condition on concurrent publishes. This is acceptable for v0.1 since publishing is infrequent. Can be improved later with S3 ListObjectsV2 dynamic indexing.

- [ ] **Step 6: Add config fields**

Modify `arise/config.py`:
```python
registry_bucket: str | None = None
registry_prefix: str = "arise-registry"
registry_check_before_synthesis: bool = True
```

- [ ] **Step 7: Run tests, verify pass**

Run: `python -m pytest tests/test_registry.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add arise/registry/ tests/test_registry.py arise/config.py arise/skills/forge.py arise/__init__.py
git commit -m "feat: add skill sharing registry (S3-backed)"
```

---

### Task 2: Multi-Model Synthesis

Use cheap models for gap detection and expensive models for code synthesis. Allow benchmarking which model produces the best skills.

**Files:**
- Create: `arise/llm_router.py`
- Modify: `arise/config.py` (add model routing config)
- Modify: `arise/skills/forge.py` (use router instead of single model)
- Modify: `arise/agent.py` (pass router to SkillForge)
- Modify: `arise/worker.py` (pass router to SkillForge)
- Modify: `arise/__init__.py` (export LLMRouter)
- Test: `tests/test_llm_router.py`

**Design:**
- `LLMRouter` maps task types to models: `{"gap_detection": "gpt-4o-mini", "synthesis": "claude-sonnet-4-5-20250929", "refinement": "gpt-4o-mini"}`
- Tracks per-model success rates (skills that pass sandbox on first try)
- Optional auto-select: try cheap model first, fall back to expensive on failure

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_router.py`:
```python
def test_router_routes_by_task_type():
    router = LLMRouter({"gap_detection": "gpt-4o-mini", "synthesis": "gpt-4o"})
    assert router.get_model("gap_detection") == "gpt-4o-mini"
    assert router.get_model("synthesis") == "gpt-4o"

def test_router_falls_back_to_default():
    router = LLMRouter({"synthesis": "gpt-4o"}, default="gpt-4o-mini")
    assert router.get_model("refinement") == "gpt-4o-mini"

def test_router_tracks_success():
    router = LLMRouter({})
    router.record("synthesis", "gpt-4o", success=True)
    router.record("synthesis", "gpt-4o", success=False)
    assert router.get_stats("synthesis", "gpt-4o")["success_rate"] == 0.5

def test_router_auto_select():
    router = LLMRouter({}, auto_select=True)
    # Records suggest gpt-4o is better for synthesis
    for _ in range(10):
        router.record("synthesis", "gpt-4o", success=True)
    for _ in range(10):
        router.record("synthesis", "gpt-4o-mini", success=False)
    assert router.get_model("synthesis") == "gpt-4o"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm_router.py -v`
Expected: FAIL

- [ ] **Step 3: Implement LLMRouter**

Create `arise/llm_router.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ModelStats:
    attempts: int = 0
    successes: int = 0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

class LLMRouter:
    """Routes LLM calls to different models based on task type."""

    def __init__(self, routes: dict[str, str] = None, default: str = "gpt-4o-mini", auto_select: bool = False):
        self._routes = routes or {}
        self._default = default
        self._auto_select = auto_select
        self._stats: dict[str, dict[str, ModelStats]] = {}  # task_type -> model -> stats

    def get_model(self, task_type: str) -> str:
        if self._auto_select:
            best = self._best_model(task_type)
            if best:
                return best
        return self._routes.get(task_type, self._default)

    def record(self, task_type: str, model: str, success: bool) -> None:
        ...

    def get_stats(self, task_type: str, model: str) -> dict:
        ...

    def _best_model(self, task_type: str) -> str | None:
        ...
```

- [ ] **Step 4: Integrate with SkillForge**

Modify `arise/skills/forge.py`:
- Add `llm_router: LLMRouter | None = None` parameter to `SkillForge.__init__`
- In each method, resolve model: `model = self.llm_router.get_model("gap_detection") if self.llm_router else self.model`
- In `detect_gaps()`: use router for `"gap_detection"`
- In `synthesize()`: use router for `"synthesis"`; after sandbox result: `self.llm_router.record("synthesis", model, result.success)`
- In `refine()`: use router for `"refinement"`
- In `arise/agent.py` (line ~76) and `arise/worker.py` (line ~44): pass `llm_router` when creating `SkillForge`

> **Note**: This task modifies `forge.py` which was also changed in Task 1. Apply on top of Task 1 changes.

- [ ] **Step 5: Add config**

Modify `arise/config.py`:
```python
model_routes: dict[str, str] | None = None  # e.g. {"synthesis": "gpt-4o", "gap_detection": "gpt-4o-mini"}
auto_select_model: bool = False
```

- [ ] **Step 6: Run tests, verify pass**

Run: `python -m pytest tests/test_llm_router.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add arise/llm_router.py tests/test_llm_router.py arise/config.py arise/skills/forge.py
git commit -m "feat: add multi-model synthesis with LLMRouter"
```

---

### Task 3: Skill A/B Testing

Run two versions of a skill simultaneously and promote the one with better reward.

**Files:**
- Create: `arise/skills/ab_test.py`
- Modify: `arise/agent.py` (inject A/B variants into tools)
- Modify: `arise/__init__.py` (export SkillABTest)
- Test: `tests/test_ab_testing.py`

**Design:**
- `SkillABTest` tracks two skill versions with invocation counts + success rates
- Agent randomly assigns variant A or B per episode (not per tool call)
- After N episodes (configurable, default 20), auto-promote winner
- Loser gets deprecated

- [ ] **Step 1: Write failing tests**

Create `tests/test_ab_testing.py`:
```python
def test_ab_test_creation():
    ab = SkillABTest(skill_a=skill_v1, skill_b=skill_v2, min_episodes=20)
    assert ab.status == "running"

def test_ab_test_assigns_variant():
    ab = SkillABTest(skill_a=skill_v1, skill_b=skill_v2)
    variant = ab.get_variant()
    assert variant in (skill_v1, skill_v2)

def test_ab_test_records_outcome():
    ab = SkillABTest(skill_a=skill_v1, skill_b=skill_v2, min_episodes=2)
    ab.record(skill_v1, success=True)
    ab.record(skill_v2, success=False)
    ab.record(skill_v1, success=True)
    ab.record(skill_v2, success=False)
    assert ab.status == "concluded"
    assert ab.winner.id == skill_v1.id

def test_ab_test_needs_min_episodes():
    ab = SkillABTest(skill_a=skill_v1, skill_b=skill_v2, min_episodes=20)
    ab.record(skill_v1, success=True)
    ab.record(skill_v2, success=False)
    assert ab.status == "running"  # not enough data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ab_testing.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SkillABTest**

Create `arise/skills/ab_test.py`:
```python
from __future__ import annotations
import random
from dataclasses import dataclass, field
from arise.types import Skill

@dataclass
class SkillABTest:
    skill_a: Skill
    skill_b: Skill
    min_episodes: int = 20
    _a_successes: int = 0
    _a_trials: int = 0
    _b_successes: int = 0
    _b_trials: int = 0

    @property
    def status(self) -> str:
        total = self._a_trials + self._b_trials
        if total < self.min_episodes:
            return "running"
        if min(self._a_trials, self._b_trials) < self.min_episodes // 4:
            return "running"  # need data on both
        return "concluded"

    @property
    def winner(self) -> Skill | None:
        if self.status != "concluded":
            return None
        a_rate = self._a_successes / self._a_trials if self._a_trials > 0 else 0
        b_rate = self._b_successes / self._b_trials if self._b_trials > 0 else 0
        return self.skill_a if a_rate >= b_rate else self.skill_b

    @property
    def loser(self) -> Skill | None:
        w = self.winner
        if w is None:
            return None
        return self.skill_b if w.id == self.skill_a.id else self.skill_a

    def get_variant(self) -> Skill:
        return random.choice([self.skill_a, self.skill_b])

    def record(self, skill: Skill, success: bool) -> None:
        if skill.id == self.skill_a.id:
            self._a_trials += 1
            if success:
                self._a_successes += 1
        else:
            self._b_trials += 1
            if success:
                self._b_successes += 1
```

- [ ] **Step 4: Integrate with ARISE agent**

Modify `arise/agent.py`:
- Add `self._ab_tests: dict[str, SkillABTest] = {}` to `ARISE.__init__` (keyed by skill name)
- In `run()`, after `tool_specs = self._skill_store.get_tool_specs()`:
  ```python
  # Replace tool specs involved in A/B tests with selected variant
  for name, ab in self._ab_tests.items():
      variant = ab.get_variant()
      tool_specs = [
          variant.to_tool_spec() if ts.name == name else ts
          for ts in tool_specs
      ]
  ```
- In `evolve()`, when a refined skill passes all tests, start A/B test instead of immediately promoting:
  ```python
  ab = SkillABTest(skill_a=existing_skill, skill_b=new_skill)
  self._ab_tests[existing_skill.name] = ab
  ```
- After reward computation in `run()`, record outcome for active A/B tests:
  ```python
  for name, ab in list(self._ab_tests.items()):
      used_skill = ...  # track which variant was used this episode
      ab.record(used_skill, success=(trajectory.reward >= 0.5))
      if ab.status == "concluded":
          self.skill_library.promote(ab.winner.id)
          self.skill_library.deprecate(ab.loser.id, reason="Lost A/B test")
          del self._ab_tests[name]
  ```

- [ ] **Step 5: Run tests, verify pass**

Run: `python -m pytest tests/test_ab_testing.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add arise/skills/ab_test.py tests/test_ab_testing.py arise/agent.py
git commit -m "feat: add skill A/B testing with auto-promotion"
```

---

### Task 4: Incremental Evolution

Instead of full re-synthesis, patch existing skills based on specific failure patterns.

**Files:**
- Create: `arise/prompts/patch.py`
- Modify: `arise/skills/forge.py` (add `patch()` method)
- Modify: `arise/agent.py` (evolve tries patch before full synthesis)
- Test: `tests/test_incremental_evolution.py`

**Design:**
- When a skill exists but fails on certain inputs, `forge.patch(skill, failures)` generates a targeted fix
- Patch prompt includes the specific failure + existing implementation (smaller context than full synthesis)
- Patched skill goes through sandbox + adversarial validation
- If patch fails, falls back to full re-synthesis
- Creates new version with `origin=PATCHED` and `parent_id` pointing to original

- [ ] **Step 1: Add PATCHED origin**

Modify `arise/types.py`:
```python
class SkillOrigin(Enum):
    MANUAL = "manual"
    SYNTHESIZED = "synthesized"
    REFINED = "refined"
    COMPOSED = "composed"
    PATCHED = "patched"
```

- [ ] **Step 2: Write the patch prompt**

Create `arise/prompts/patch.py`:
```python
PATCH_PROMPT = """\
An existing Python tool is failing on specific inputs. Apply a minimal, targeted fix.

FUNCTION NAME: {name}
DESCRIPTION: {description}

CURRENT IMPLEMENTATION (working for most inputs):
```python
{implementation}
```

SPECIFIC FAILURES:
{failures}

Apply the MINIMUM change needed to fix these specific failures WITHOUT breaking existing behavior.
Do NOT rewrite the function. Only modify the specific code paths that cause these failures.

Return ONLY a JSON object:
{{
    "implementation": "patched Python function source code",
    "patch_description": "one-line summary of what was changed"
}}
"""
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_incremental_evolution.py`:
```python
def test_forge_patch_returns_skill():
    # Mock forge with patched skill
    ...

def test_patch_preserves_name_and_id():
    # Patched skill has same name, parent_id = original
    ...

def test_patch_has_correct_origin():
    # origin should be PATCHED
    ...

def test_evolve_tries_patch_before_synthesis():
    # When existing skill has failures, patch is attempted first
    ...
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_incremental_evolution.py -v`
Expected: FAIL

- [ ] **Step 5: Implement forge.patch()**

Add to `arise/skills/forge.py`:
```python
def patch(self, skill: Skill, failures: list[Trajectory]) -> Skill:
    """Apply a minimal fix to an existing skill based on specific failures."""
    failure_desc = "\n\n".join(
        f"Task: {t.task}\nError: {t.steps[-1].error if t.steps and t.steps[-1].error else t.outcome}"
        for t in failures[:5]
    )

    prompt = PATCH_PROMPT.format(
        name=skill.name,
        description=skill.description,
        implementation=skill.implementation,
        failures=failure_desc,
    )

    raw = llm_call_structured(
        [{"role": "user", "content": prompt}],
        model=self.model,
    )

    return Skill(
        name=skill.name,
        description=skill.description,
        implementation=raw["implementation"],
        test_suite=skill.test_suite,
        version=skill.version + 1,
        origin=SkillOrigin.PATCHED,
        parent_id=skill.id,
    )
```

- [ ] **Step 6: Integrate with evolution**

Modify `arise/agent.py` `evolve()`:
- Before synthesizing for a gap, check if an active skill with a similar name exists
- If it does and it has recent failures, try `forge.patch(existing_skill, failures)` first
- Run patched version through sandbox + adversarial validation
- If patch passes, start A/B test (from Task 3) between original and patched version
- If patch fails, fall back to full synthesis

> **Depends on**: Task 3 (A/B Testing) must be completed first.
> **Note**: This task modifies `forge.py` which was also changed in Tasks 1 and 2. Apply on top of prior changes.

- [ ] **Step 7: Run tests, verify pass**

Run: `python -m pytest tests/test_incremental_evolution.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add arise/prompts/patch.py arise/skills/forge.py arise/agent.py arise/types.py tests/test_incremental_evolution.py
git commit -m "feat: add incremental evolution with targeted patching"
```

---

### Task 5: Reward Learning

Auto-learn reward functions from user feedback instead of requiring manual `reward_fn`.

**Files:**
- Create: `arise/rewards/learned.py`
- Modify: `arise/rewards/__init__.py` (export LearnedReward)
- Modify: `arise/__init__.py` (export LearnedReward)
- Modify: `arise/config.py` (add feedback config)
- Test: `tests/test_reward_learning.py`

**Design:**
- `LearnedReward` collects (trajectory, human_score) pairs
- After N examples (default 10), trains an LLM-based reward model
- Uses few-shot prompting: includes recent human-scored examples in the prompt
- Falls back to `task_success` if not enough examples
- Optional: persist examples to disk for cross-session learning

- [ ] **Step 1: Write failing tests**

Create `tests/test_reward_learning.py`:
```python
from arise.types import Trajectory

def make_trajectory(outcome="success"):
    return Trajectory(task="test task", outcome=outcome, steps=[])

def test_learned_reward_falls_back_before_threshold():
    lr = LearnedReward(min_examples=10)
    # With no examples, should use fallback
    t = make_trajectory(outcome="success")
    reward = lr(t)
    assert reward == 1.0  # task_success fallback

def test_learned_reward_stores_feedback():
    lr = LearnedReward()
    t = make_trajectory()
    lr.add_feedback(t, 0.8)
    assert len(lr.examples) == 1

def test_learned_reward_uses_examples_after_threshold():
    lr = LearnedReward(min_examples=2)
    # Add enough examples
    for _ in range(3):
        lr.add_feedback(make_trajectory(outcome="good"), 1.0)
        lr.add_feedback(make_trajectory(outcome="Error: failed"), 0.0)
    # Now should use LLM-based scoring (mock LLM)
    ...

def test_learned_reward_persists():
    with tempfile.TemporaryDirectory() as d:
        lr = LearnedReward(persist_path=d)
        lr.add_feedback(make_trajectory(), 0.9)
        # Reload
        lr2 = LearnedReward(persist_path=d)
        assert len(lr2.examples) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reward_learning.py -v`
Expected: FAIL

- [ ] **Step 3: Implement LearnedReward**

Create `arise/rewards/learned.py`:
```python
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from arise.types import Trajectory
from arise.rewards.builtin import task_success
from arise.llm import llm_call

@dataclass
class FeedbackExample:
    task: str
    outcome: str
    step_count: int
    human_score: float

class LearnedReward:
    """Reward function that learns from human feedback via few-shot prompting."""

    def __init__(self, min_examples: int = 10, persist_path: str | None = None,
                 model: str = "gpt-4o-mini", max_examples: int = 50):
        self.min_examples = min_examples
        self.persist_path = persist_path
        self.model = model
        self.max_examples = max_examples
        self.examples: list[FeedbackExample] = []
        if persist_path:
            self._load()

    def __call__(self, trajectory: Trajectory) -> float:
        if len(self.examples) < self.min_examples:
            return task_success(trajectory)
        return self._llm_score(trajectory)

    def add_feedback(self, trajectory: Trajectory, score: float) -> None:
        self.examples.append(FeedbackExample(
            task=trajectory.task,
            outcome=trajectory.outcome[:500],
            step_count=len(trajectory.steps),
            human_score=score,
        ))
        if len(self.examples) > self.max_examples:
            self.examples = self.examples[-self.max_examples:]
        if self.persist_path:
            self._save()

    def _llm_score(self, trajectory: Trajectory) -> float:
        examples_text = "\n".join(
            f"Task: {e.task[:100]}\nOutcome: {e.outcome[:200]}\nSteps: {e.step_count}\nScore: {e.human_score}"
            for e in self.examples[-10:]
        )
        prompt = f"""Based on these human-scored examples:

{examples_text}

Score this new trajectory (0.0 = failure, 1.0 = perfect):
Task: {trajectory.task[:200]}
Outcome: {trajectory.outcome[:500]}
Steps: {len(trajectory.steps)}

Return ONLY a number between 0.0 and 1.0."""

        try:
            result = llm_call([{"role": "user", "content": prompt}], model=self.model, max_tokens=10)
            score = float(result.strip())
            return max(0.0, min(1.0, score))
        except Exception:
            return task_success(trajectory)

    def _save(self) -> None:
        ...

    def _load(self) -> None:
        ...
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_reward_learning.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add arise/rewards/learned.py tests/test_reward_learning.py arise/rewards/__init__.py arise/config.py
git commit -m "feat: add learned reward function from human feedback"
```

---

## Phase 2: AgentCore Demo

### Task 6: Build the DevOps Agent

A self-evolving agent that handles DevOps tasks: file operations, log analysis, deployment checks, API health monitoring. Starts with zero tools and evolves them as it encounters tasks.

**Files:**
- Create: `demo/agentcore/agent.py` (main agent entry point)
- Create: `demo/agentcore/tasks.py` (sample task set)
- Create: `demo/agentcore/reward.py` (task-specific reward function)
- Create: `demo/agentcore/requirements.txt`
- Create: `demo/agentcore/.bedrock_agentcore.yaml`
- Create: `demo/agentcore/README.md`

**Design:**
- Uses Strands Agent with Bedrock Claude model
- ARISE wraps the agent in distributed mode (S3 skills, SQS trajectories)
- Starts with zero skills — must evolve everything
- Task categories: file parsing, log analysis, JSON manipulation, API checks, text processing
- Reward function: `task_success` + output validation via regex patterns

- [ ] **Step 1: Create agent entry point**

Create `demo/agentcore/agent.py`:
```python
"""Self-evolving DevOps agent deployed on Amazon Bedrock AgentCore."""
import os
from strands import Agent
from strands.models.bedrock import BedrockModel
from arise import ARISE, ARISEConfig, create_distributed_arise
from arise.adapters.strands import strands_adapter
from arise.rewards.builtin import task_success

config = ARISEConfig(
    model="gpt-4o-mini",
    s3_bucket=os.environ.get("ARISE_SKILL_BUCKET", ""),
    sqs_queue_url=os.environ.get("ARISE_QUEUE_URL", ""),
    aws_region=os.environ.get("AWS_REGION", "us-west-2"),
    max_evolutions_per_hour=5,
    allowed_imports=["json", "csv", "re", "hashlib", "base64", "datetime",
                     "math", "collections", "itertools", "functools",
                     "pathlib", "os", "tempfile", "urllib"],
)

bedrock_model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    region_name=config.aws_region,
)

strands_agent = Agent(
    model=bedrock_model,
    system_prompt="You are a DevOps assistant. Use available tools to complete tasks. If no tool exists for a task, say so clearly.",
)

# create_distributed_arise sets up S3SkillStore + SQSTrajectoryReporter
# so the agent reads skills from S3 and reports trajectories to SQS
agent_fn = strands_adapter(strands_agent)
arise = create_distributed_arise(
    agent_fn=agent_fn,
    reward_fn=task_success,
    config=config,
)

def handler(event, context=None):
    """AgentCore / Lambda entry point."""
    task = event.get("task", event.get("body", ""))
    result = arise.run(task)
    return {"statusCode": 200, "body": result}

if __name__ == "__main__":
    import sys
    task = sys.argv[1] if len(sys.argv) > 1 else "Compute the SHA-256 hash of 'hello world'"
    print(arise.run(task))
```

- [ ] **Step 2: Create task set for training**

Create `demo/agentcore/tasks.py` with 20 diverse DevOps tasks.

- [ ] **Step 3: Create AgentCore config**

Create `demo/agentcore/.bedrock_agentcore.yaml`:
```yaml
agent:
  name: arise-devops-agent
  entrypoint: agent.py
  runtime: python3.11
  memory: 512
  timeout: 300
  environment:
    ARISE_SKILL_BUCKET: "${ARISE_SKILL_BUCKET}"
    ARISE_QUEUE_URL: "${ARISE_QUEUE_URL}"
    OPENAI_API_KEY: "${OPENAI_API_KEY}"
```

- [ ] **Step 4: Create requirements.txt**

```
arise-ai>=0.1.0
strands-agents>=0.1.0
strands-agents-tools>=0.1.0
boto3>=1.34
```

- [ ] **Step 5: Test locally**

```bash
cd demo/agentcore
pip install -r requirements.txt
ARISE_SKILL_BUCKET=arise-test-436776987862 \
ARISE_QUEUE_URL=https://us-west-2.queue.amazonaws.com/436776987862/arise-trajectories-test \
OPENAI_API_KEY=... \
python agent.py "Parse this CSV and return the average of column 2: name,score\nAlice,85\nBob,92\nCharlie,78"
```

- [ ] **Step 6: Write demo README**

Create `demo/agentcore/README.md` with setup instructions, architecture diagram, and expected output.

- [ ] **Step 7: Commit**

```bash
git add demo/agentcore/
git commit -m "feat: add self-evolving DevOps agent demo for AgentCore"
```

---

### Task 7: Deploy to AgentCore

**Files:**
- Modify: `demo/agentcore/.bedrock_agentcore.yaml` (finalize config)
- Create: `demo/agentcore/deploy.sh` (deployment script)

- [ ] **Step 1: Install AgentCore toolkit**

```bash
pip install bedrock-agentcore-starter-toolkit
```

- [ ] **Step 2: Deploy**

```bash
cd demo/agentcore
agentcore deploy --profile apartment-ai --region us-west-2
```

- [ ] **Step 3: Test deployed agent**

```bash
# Invoke via AgentCore API
agentcore invoke --agent arise-devops-agent --payload '{"task": "Compute SHA-256 of hello"}'
```

- [ ] **Step 4: Run training loop**

```bash
# Start the worker for evolution
AWS_PROFILE=apartment-ai python -c "
from arise.worker import ARISEWorker
from arise.config import ARISEConfig
config = ARISEConfig(
    s3_bucket='arise-test-436776987862',
    sqs_queue_url='https://us-west-2.queue.amazonaws.com/436776987862/arise-trajectories-test',
    aws_region='us-west-2',
)
worker = ARISEWorker(config)
worker.run_forever()
"
```

Then send tasks to the agent and watch it evolve tools.

- [ ] **Step 5: Commit final deployment artifacts**

```bash
git add demo/agentcore/
git commit -m "feat: add AgentCore deployment config and scripts"
```

---

## Phase 3: Housekeeping (parallel with above)

### Task 8: CI/CD + Cleanup

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `CONTRIBUTING.md`
- Delete: `medium-draft.md`
- Modify: `.gitignore` (add medium-draft.md pattern)

- [ ] **Step 1: Create GitHub Actions CI**

Create `.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ -v --ignore=tests/test_distributed_e2e.py --ignore=tests/test_distributed_llm.py
```

- [ ] **Step 2: Create CONTRIBUTING.md**

Brief guide: how to run tests, code style, PR process.

- [ ] **Step 3: Remove medium-draft.md**

```bash
git rm medium-draft.md
```

- [ ] **Step 4: Commit**

```bash
git add .github/ CONTRIBUTING.md
git commit -m "chore: add CI/CD, CONTRIBUTING.md, remove draft files"
```

---

## Execution Order

1. **Task 8** (CI/CD + Cleanup) — quick wins, do first
2. **Task 1** (Skill Registry) — foundational for sharing
3. **Task 2** (Multi-Model Synthesis) — cost optimization
4. **Task 3** (A/B Testing) — quality improvement
5. **Task 4** (Incremental Evolution) — efficiency
6. **Task 5** (Reward Learning) — UX improvement
7. **Task 6** (DevOps Agent) — demo build
8. **Task 7** (AgentCore Deploy) — deployment
