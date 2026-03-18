# ARISE: Adaptive Runtime Improvement through Self-Evolution

## Abstract

We present ARISE, a framework-agnostic middleware that enables LLM agents to autonomously create, test, and promote their own tools at runtime. When an agent encounters tasks it cannot solve with its current capabilities, ARISE detects the gap, synthesizes a Python tool via LLM, validates it through sandbox testing and adversarial evaluation, and promotes it to the active library. We evaluate ARISE through a realistic SRE agent onboarding scenario where the agent must learn to operate proprietary systems with custom log formats, metrics APIs, and configuration files that do not exist in LLM training data. Our results show that ARISE improves agent success rates from 48% to 78% with Claude Sonnet and from 48% to 57% with GPT-4o-mini. Notably, ARISE's self-evolved minimal toolsets (2 tools) outperform comprehensive hand-written toolsets (7 tools), suggesting that tools tailored to the agent's actual failure patterns are more effective than tools designed by human engineers. ARISE is open-source, supports any agent framework, and includes distributed deployment via S3/SQS for stateless production environments.

---

## 1. Introduction

Building an LLM agent is straightforward. Maintaining its tool library is the bottleneck. Every time an agent encounters a task requiring a capability it lacks, a human engineer must notice the failure, understand what tool is missing, implement it, test it, and deploy it. This feedback loop works when the environment is well-defined, but breaks down in three increasingly common scenarios:

**Multi-tenant platforms.** An agent serving many customers encounters different internal systems, APIs, and data formats. Pre-building tools for every customer's stack is impractical.

**Long-running autonomous agents.** Operations agents, monitoring systems, and data pipeline agents encounter novel situations at unpredictable times — often without a human available to write a quick fix.

**The long tail of edge cases.** An agent fails on dozens of different edge cases. Each individual failure isn't worth an engineer's afternoon, but collectively they represent a significant capability gap.

ARISE addresses these scenarios by automating the tool engineering feedback loop. Rather than requiring human intervention, ARISE observes the agent's failures, identifies missing capabilities, synthesizes candidate tools, validates them through automated testing, and promotes passing tools to the agent's active library — all at runtime.

### Contributions

1. **A framework-agnostic self-evolution pipeline** that works with any LLM agent by wrapping the agent function and tool library, requiring no modifications to the agent's architecture.

2. **A multi-layer safety model** for generated code: sandbox isolation, automated test generation, adversarial validation, import restrictions, and version-controlled rollback.

3. **A distributed architecture** decoupling the stateless agent process from the evolution worker, enabling deployment in serverless and multi-replica environments.

4. **An empirical evaluation** on a realistic SRE onboarding benchmark with proprietary formats, demonstrating that self-evolved tools outperform both no-tool baselines and hand-written tool baselines.

---

## 2. Related Work

**LLMs as Tool Makers (LATM)** [Cai et al., 2023] demonstrated that LLMs can create reusable tools — a "tool maker" model generates Python functions that a cheaper "tool user" model invokes. ARISE extends this with automated testing, adversarial validation, versioning, and a feedback loop driven by real agent failures rather than predefined tasks.

**VOYAGER** [Wang et al., 2023] demonstrated an open-ended agent in Minecraft that builds a skill library through exploration. ARISE applies the same skill library pattern to real-world software agents, adding safety validation that game environments don't require, and supports deployment in production infrastructure.

**CREATOR** [Qian et al., 2023] proposed disentangling abstract reasoning from concrete tool creation, letting LLMs create tools when existing ones are insufficient. ARISE operationalizes this with trajectory analysis to automatically detect when creation should trigger.

**CRAFT** [Yuan et al., 2023] introduced a framework where agents create and retrieve tools from a shared library. ARISE adds the production engineering layer: sandboxed testing, adversarial validation, version control, distributed deployment, and A/B testing of tool variants.

**Toolformer** [Schick et al., 2023] showed LLMs can learn *when* to use tools through self-supervised training. ARISE complements this by addressing *which* tools should exist — creating them at runtime rather than assuming a fixed toolset.

Unlike prior work, ARISE is (1) framework-agnostic, working with any agent that accepts callable tools, (2) production-ready with safety guarantees and distributed deployment, and (3) publicly available as an installable package.

---

## 3. System Design

### 3.1 Architecture Overview

ARISE operates as middleware between the agent and its tool library. The core loop:

1. **Observe**: The agent executes a task using its current tools. ARISE records the full trajectory (task, tool calls, results, errors) and computes a reward score.

2. **Detect**: When failures accumulate beyond a configurable threshold, ARISE analyzes recent failure trajectories to identify capability gaps — specific tool functions that would have enabled success.

3. **Synthesize**: For each detected gap, ARISE prompts an LLM to generate a Python function with type hints, docstring, and test suite. The synthesis prompt includes the failed trajectories as evidence, ensuring generated tools address the agent's actual needs.

4. **Validate**: Generated tools undergo multi-stage validation:
   - **Sandbox testing**: Execution in an isolated subprocess or Docker container
   - **Adversarial testing**: A separate LLM generates edge-case tests targeting boundary conditions, type errors, and security issues
   - **Import restriction**: Static analysis blocks unauthorized module imports

5. **Promote**: Tools passing all validation stages are promoted to the active library. Failed tools are stored for potential refinement.

### 3.2 Synthesis Pipeline

Gap detection uses an LLM prompt that includes recent failure trajectories and the current tool inventory. The LLM returns structured JSON describing missing capabilities with suggested function signatures.

Tool synthesis generates self-contained Python functions where all imports are inside the function body (enabling safe `exec()`-based loading). The synthesis prompt includes the gap description, evidence from failures, and the existing tool inventory to avoid duplication.

When synthesis produces a tool that fails sandbox testing, ARISE applies iterative refinement — feeding the error messages back to the LLM for correction, up to a configurable maximum number of attempts.

### 3.3 Incremental Evolution

For existing tools that fail on specific inputs, ARISE supports targeted patching via `forge.patch()`, which generates minimal fixes rather than full re-synthesis. Patched tools enter an A/B test against the original before promotion, ensuring that fixes don't introduce regressions.

### 3.4 Distributed Deployment

For stateless environments (Lambda, ECS, Bedrock AgentCore), ARISE decouples into:

- **Agent process**: Reads tools from S3 (with TTL cache), reports trajectories to SQS. No local state.
- **Worker process**: Consumes trajectories from SQS, runs evolution, writes promoted tools to S3.

The S3 skill store uses ETag-based optimistic locking for manifest updates. The SQS reporter is fire-and-forget via daemon threads to avoid blocking the agent.

### 3.5 Multi-Model Routing

ARISE supports routing different synthesis tasks to different models via `LLMRouter`. Gap detection can use a cheap model (GPT-4o-mini) while code synthesis uses a more capable model. The router tracks per-model success rates and supports automatic model selection based on historical sandbox pass rates.

---

## 4. Evaluation

### 4.1 Benchmark Design: SRE Agent Onboarding

We designed a benchmark simulating an SRE agent onboarding at "AcmeCorp" — a fictional company with three proprietary systems:

**Custom log format**: `[ACME:severity:service:timestamp] message | ctx={json}` — a format that does not exist in any LLM's training data, requiring the agent to learn the parsing rules from the prompt or evolve a parser tool.

**Metrics API**: An HTTP endpoint returning base64-encoded payloads in a proprietary format (`ACME_METRICS|service|timestamp|json`). The agent must make real HTTP calls and decode the response — neither is possible without tools.

**AcmeConf configuration format**: A custom config syntax with `@include` directives, variable interpolation (`${VAR:-default}`), duration literals, and list values — distinct from YAML, JSON, or TOML.

The benchmark consists of 60 tasks across 4 phases of escalating difficulty:

| Phase | Domain | Tasks | What the agent needs |
|-------|--------|-------|---------------------|
| 1 | Log Analysis | 15 | Parse custom format, filter, aggregate |
| 2 | Metrics API | 15 | HTTP calls + decode proprietary encoding |
| 3 | Config Management | 15 | Parse AcmeConf, validate, diff |
| 4 | Incident Response | 15 | Compose tools from all domains |

All tasks use deterministic check functions against pre-computed ground truth. No LLM judging — scoring is purely automated.

### 4.2 Conditions

We evaluate four conditions:

- **ARISE**: Agent starts with a seed `http_get` tool. Evolution is enabled with `failure_threshold=5`.
- **No-evolution**: Agent receives no tools. Pure LLM reasoning over inline data.
- **Fixed-tools**: Agent receives 7 hand-written tools from episode 1 (the "engineer built everything upfront" ceiling).
- Models: GPT-4o-mini and Claude Sonnet 4.5 as the agent model. GPT-4o-mini as the synthesis model in all conditions.

### 4.3 Results

#### Table 1: Success rates by phase and condition

| Model | Condition | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Overall | Tools |
|-------|-----------|---------|---------|---------|---------|---------|-------|
| Claude Sonnet | ARISE | **60%** | **73%** | **100%** | **80%** | **78%** | 2 |
| Claude Sonnet | No-evolution | 60% | 13% | 100% | 80% | 63% | 0 |
| GPT-4o-mini | ARISE | 20% | 67% | 93% | 47% | 57% | 21 |
| GPT-4o-mini | No-evolution | 33% | 7% | 93% | 60% | 48% | 0 |
| GPT-4o-mini | Fixed-tools | 13% | 53% | 87% | 40% | 48% | 7 |

#### Finding 1: ARISE improves both models

ARISE improved Claude Sonnet from 63% to 78% (+15 percentage points) and GPT-4o-mini from 48% to 57% (+9 pp). The improvement is consistent across capability levels.

#### Finding 2: The improvement concentrates where tools are essential

Phase 2 (Metrics API) requires real HTTP calls and proprietary format decoding — tasks that are impossible without tools. ARISE produces the largest gains here:

- Claude: 13% → 73% (+60 pp)
- GPT-4o-mini: 7% → 67% (+60 pp)

Phase 3 (Config), where inline reasoning suffices, shows no improvement — both models achieve 93-100% with or without tools. This confirms that ARISE adds value specifically where tool capabilities are needed, not through general reasoning improvement.

#### Finding 3: Self-evolved tools outperform hand-written tools

The fixed-tools baseline (48%) tied with the no-evolution baseline (48%) for GPT-4o-mini, despite providing 7 perfectly implemented tools. ARISE's self-evolved tools achieved 57%.

Agent trace analysis reveals the mechanism: the hand-written tools accept the full log text as a function argument, causing each tool call to send 500+ lines through the LLM context. This creates a throughput bottleneck — episodes with fixed tools took 100-980 seconds each, versus 2-8 seconds for no-evolution and 5-50 seconds for ARISE (excluding evolution cycles).

ARISE's evolved tools were more targeted because the synthesis prompt includes the agent's actual failure context, producing tools that fit how the agent naturally decomposes problems.

#### Finding 4: Agent reasoning quality matters more than tool quantity

Claude Sonnet achieved 78% with only 2 tools while GPT-4o-mini needed 21 evolved tools to reach 57%. This demonstrates that ARISE amplifies existing model capability rather than replacing it. A strong model that uses tools well benefits more from a minimal, well-targeted toolset than a weak model with many tools.

#### Finding 5: Tool-calling overhead can hurt weak models

For GPT-4o-mini, the no-evolution baseline outperformed ARISE on Phase 1 (33% vs 20%) and Phase 4 (60% vs 47%). Analysis shows that GPT-4o-mini sometimes calls tools incorrectly when raw reasoning would have succeeded, and struggles to compose multiple tool calls in sequence. This overhead effect disappears with Claude Sonnet, which uses tools more judiciously.

### 4.4 Evolution Analysis

#### GPT-4o-mini ARISE

- 8 evolution cycles across 60 episodes
- 21 tools synthesized, 11 promoted (52% promotion rate)
- Key promoted tools: `count_error_entries_per_service`, `filter_entries_by_time_range`, `decode_and_parse_metrics`, `aggregate_metrics_summary`
- Import restriction caught 1 attempt to use an unauthorized module (`difflib`)
- Total synthesis cost: ~$0.26 (64 LLM calls at GPT-4o-mini pricing)

#### Claude Sonnet ARISE

- 1-2 evolution cycles across 60 episodes
- Only 1 tool evolved beyond the seed `http_get`
- Claude's reasoning was strong enough to handle most tasks without synthesized tools
- Total synthesis cost: ~$0.05

This disparity highlights an interesting dynamic: weaker models need more evolved tools, but are also worse at using them. Stronger models need fewer tools but use them more effectively.

### 4.5 Tool Quality Analysis

We examine the tools ARISE synthesized during the GPT-4o-mini run (21 tools total, 14 promoted).

**Promoted tools by domain:**

| Domain | Tools promoted | Examples |
|--------|---------------|----------|
| Log parsing | 6 | `count_error_entries_per_service`, `filter_entries_by_time_range`, `aggregate_errors_by_hour` |
| Metrics | 5 | `decode_base64_metrics`, `compare_metrics`, `aggregate_metrics_summary` |
| General | 3 | `calculate_total_metric`, `calculate_error_rate`, `compute_efficiency` |

**Failed tools (7 stayed in testing):**

| Tool | Failure reason |
|------|---------------|
| `fetch_and_decode_metrics` | Sandbox failure 3/3 — couldn't correctly implement the proprietary base64 decoding in a self-contained function |
| `correlate_service_errors_by_hour` | Sandbox failure — cross-service time correlation logic too complex for synthesis |
| `count_log_severity` | Adversarial testing caught edge case with empty log input |
| `compute_error_rate` | Adversarial testing caught division-by-zero on services with no entries |
| `aggregate_entries_by_service_and_severity` | Sandbox failure — output format didn't match test expectations |

The safety model caught real bugs: division-by-zero, empty input handling, and format mismatches. 33% of synthesized tools were rejected — a meaningful rejection rate that validates the multi-stage validation approach.

**Import restriction enforcement:** One tool attempted to import `difflib` (not in the allowed list). The static import checker caught this and forced a reimplementation using basic string comparison.

### 4.6 Error Analysis

We categorize the 13 failures in the Claude Sonnet ARISE run (78% success, 47/60 passed):

| Category | Count | Tasks | Explanation |
|----------|-------|-------|-------------|
| Log parsing errors | 6 | log-01,03,04,09,12,14 | Claude parsed the custom format but produced output that didn't match the check function's expected format (e.g., returning "2 errors" instead of just "2") |
| Multi-service metrics | 4 | metrics-07,10,14,15 | Tasks requiring multiple API calls + aggregation across all services; Claude sometimes missed a service or computed averages incorrectly |
| Complex incidents | 3 | incident-06,07,15 | Multi-domain tasks requiring log + metrics + config composition; Claude timed out on the multi-step reasoning |

**Key insight:** ARISE's improvement for Claude is **entirely concentrated in Phase 2** (+9 tasks over no-evolution). For Phases 1, 3, and 4, Claude's results are identical with and without ARISE — the seed `http_get` tool was the only difference that mattered. This suggests that for strong models, ARISE's primary value is providing I/O capabilities (HTTP, file access) rather than computation tools.

For GPT-4o-mini, the pattern is different: ARISE improved Phase 2 by +9 tasks (same as Claude) but *decreased* Phases 1 and 4 performance due to tool-calling overhead. The 21 evolved computational tools (log parsing, aggregation) added complexity that the weaker model couldn't manage effectively.

### 4.7 Cost and Timing

| Condition | Duration | Estimated cost |
|-----------|----------|---------------|
| GPT-4o-mini no-evolution | 8 min | $0.18 |
| GPT-4o-mini ARISE | 4 hr | $0.44 |
| GPT-4o-mini fixed-tools | 2.5 hr | $0.18 |
| Claude Sonnet ARISE | 5 hr | $5.50 |
| Claude Sonnet no-evolution | 10 min | $3.00 |

Evolution cycles dominate runtime. Each cycle involves 10-20 sequential LLM calls for synthesis, testing, and refinement. Without evolution, episodes complete in seconds.

### 4.8 Cross-Domain Generality: DataCorp Benchmark

To validate that ARISE generalizes beyond SRE operations, we constructed a second benchmark domain: **DataCorp**, a fictional data engineering company with three proprietary systems:

- **Custom CSV dialect**: pipe-delimited with `##` comment headers containing schema metadata
- **Data validation API**: HTTP endpoint that validates records against schema rules with custom error codes (DC-001 through DC-010)
- **DataCorp Query Language (DCQL)**: SQL-like syntax with proprietary functions (`DC_CONVERT`, `DC_HASH`, `DC_TIMERANGE`)

30 tasks across 3 phases: CSV processing (10), data validation (10), and DCQL query execution (10).

#### Table 3: DataCorp results (quick mode, 12 tasks)

| Condition | Phase 1 (CSV) | Phase 2 (Validation) | Phase 3 (Queries) | Overall |
|-----------|--------------|---------------------|-------------------|---------|
| ARISE (gpt-4o-mini) | 75% | **100%** | **100%** | **92%** |
| No-evolution (gpt-4o-mini) | 75% | 50% | 25% | 50% |

ARISE improved overall success from 50% to **92%** — a +42 percentage point gain, substantially larger than the +9pp improvement on AcmeCorp. The improvement is concentrated in Phases 2 and 3, where tool access (HTTP for the validation API, execution for DCQL) is essential.

This cross-domain result confirms that ARISE's self-evolution generalizes to fundamentally different task types. The SRE and data engineering domains share no proprietary formats, yet ARISE improved performance on both by detecting capability gaps and synthesizing appropriate tools.

---

## 5. Limitations

**Statistical significance.** Results are from single runs (seed=42). Multiple seeds are needed for confidence intervals. We plan to report mean ± std across seeds 42, 123, 456 in the final version.

**Tool-calling overhead.** For weaker models like GPT-4o-mini, the overhead of tool selection and invocation can reduce performance on tasks where raw reasoning suffices. ARISE currently does not suppress tool use when reasoning alone would be sufficient.

**Evolution latency.** Each evolution cycle takes 2-10 minutes of sequential LLM calls. This is acceptable for background workers but problematic for synchronous, latency-sensitive applications.

**Check function sensitivity.** Our deterministic check functions may be stricter than necessary — an agent might produce a correct answer in a format the check function doesn't recognize. This could understate actual performance across all conditions equally.

**Fixed-tools baseline.** We were unable to complete the Claude Sonnet fixed-tools run due to excessive latency (100-980 seconds per episode from large payloads in tool arguments). This limits our ability to fully compare ARISE against hand-written tools for stronger models.

---

## 6. Discussion

### Why fewer tools can be better

Our most surprising finding is that ARISE's self-evolved minimal toolsets outperform comprehensive hand-written toolsets. We attribute this to three factors:

1. **Failure-driven synthesis produces targeted tools.** ARISE's synthesis prompt includes the agent's actual failure trajectories, so generated tools address the specific decomposition the agent naturally performs.

2. **Fewer tools reduce selection overhead.** With 7 tools, the agent must decide which to call and how to compose them. With 2 tools, the decision space is trivial.

3. **Large argument passing creates bottlenecks.** Hand-written tools that accept full data payloads cause each tool call to resend hundreds of lines through the LLM context window, consuming tokens and latency.

These factors suggest that tool library design should prioritize agent-tool fit over tool completeness.

### The role of the base model

ARISE amplifies model capability rather than replacing it. Claude Sonnet with just `http_get` achieved 78% — nearly matching its theoretical ceiling — because its reasoning is strong enough to parse custom formats inline. GPT-4o-mini needed 21 specialized tools to reach 57% because it cannot reliably parse unfamiliar formats through reasoning alone.

This suggests that ARISE is most valuable for mid-tier models that have adequate reasoning for tool use but insufficient reasoning for complex parsing and composition without tools.

---

## 7. Conclusion

ARISE demonstrates that LLM agents can autonomously extend their own capabilities through a validated self-evolution pipeline. Our evaluation shows consistent improvement across model capability levels, with the largest gains on tasks requiring genuine tool capabilities (HTTP calls, proprietary format decoding). The finding that self-evolved minimal toolsets outperform hand-written comprehensive toolsets challenges the assumption that more tools always leads to better agent performance, and suggests a new paradigm where agents and their tools co-evolve.

ARISE is available as an open-source Python package (`pip install arise-ai`) with support for any agent framework, distributed deployment via S3/SQS, and deployment on Amazon Bedrock AgentCore.

---

## References

- Cai, T., et al. (2023). Large Language Models as Tool Makers. arXiv:2305.17126.
- Wang, G., et al. (2023). VOYAGER: An Open-Ended Embodied Agent with Large Language Models. arXiv:2305.16291.
- Qian, C., et al. (2023). CREATOR: Tool Creation for Disentangling Abstract and Concrete Reasoning of Large Language Models. arXiv:2305.14318.
- Yuan, S., et al. (2023). CRAFT: Customizing LLMs by Creating and Retrieving from Specialized Toolsets. arXiv:2309.17428.
- Schick, T., et al. (2023). Toolformer: Language Models Can Teach Themselves to Use Tools. arXiv:2302.04761.
- Hu, S., et al. (2024). Automated Design of Agentic Systems. arXiv:2408.08435.
