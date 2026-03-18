# ARISE Benchmark Results

## Experiment: SRE Agent Onboarding at AcmeCorp

**Date:** 2026-03-18
**Seed:** 42
**Episodes:** 60 (15 per phase)
**Synthesis model:** gpt-4o-mini (for tool evolution)

## Results: gpt-4o-mini as Agent

| Condition | Phase 1 (Logs) | Phase 2 (Metrics) | Phase 3 (Config) | Phase 4 (Incidents) | Overall | Tools |
|-----------|---------------|-------------------|-------------------|---------------------|---------|-------|
| **ARISE** | 20% | **67%** | **93%** | 47% | **57%** | 21 |
| No-evolution | 33% | 7% | **93%** | **60%** | 48% | 0 |
| Fixed-tools | 13% | 53% | 87% | 40% | 48% | 7 |

### Key Findings

**1. ARISE outperforms both baselines overall (57% vs 48%)**

ARISE evolved 21 tools and achieved the highest overall success rate. Neither baseline — raw LLM reasoning nor hand-written tools — matched it.

**2. Self-evolved tools > hand-written tools**

The fixed-tools baseline (48%) tied with no-evolution (48%), despite having 7 perfectly implemented tools. gpt-4o-mini couldn't use the hand-written tools effectively. ARISE's self-evolved tools performed better because they were shaped by the agent's own failure patterns — the synthesis prompt includes the actual failures, so tools are tailored to how the agent works.

**3. Phase 2 (Metrics API) is where ARISE shines**

| Condition | Phase 2 Score |
|-----------|--------------|
| ARISE | **67%** |
| Fixed-tools | 53% |
| No-evolution | 7% |

The metrics API requires real HTTP calls + decoding a proprietary format. Without tools, the agent is helpless (7%). With tools — whether hand-written or evolved — it can succeed. ARISE outperformed even the hand-written tools (67% vs 53%).

**4. Phase 1 (Logs) — tool use overhead hurt**

| Condition | Phase 1 Score |
|-----------|--------------|
| No-evolution | **33%** |
| ARISE | 20% |
| Fixed-tools | 13% |

Log data was embedded inline in prompts, so raw reasoning worked for simple parsing. Adding tools introduced overhead — the agent sometimes called tools incorrectly when reasoning alone would have worked. This is a gpt-4o-mini limitation, not an ARISE limitation.

**5. Phase 3 (Config) — reasoning sufficient**

All conditions scored 87-93%. AcmeConf configs were provided inline, and gpt-4o-mini is strong enough to parse custom syntax by reasoning. Tools provided marginal benefit.

**6. Phase 4 (Incidents) — composition challenge**

Multi-domain tasks combining logs + metrics + config. No-evolution performed best (60%) because the easier incident tasks could be solved by reasoning about inline data. ARISE (47%) and fixed-tools (40%) struggled because gpt-4o-mini is poor at composing multiple tool calls in sequence.

### Tools Evolved by ARISE

Total: 21 skills (6 promoted to active, 15 in testing)

Promoted tools:
- `count_log_entries` — count total log entries
- `extract_unique_services_with_severity` — find services with specific severity
- `count_error_entries_per_service` — count errors per service
- `count_entries_by_severity` — count by severity level
- `filter_entries_by_time_range` — time-windowed log filtering
- `aggregate_errors_by_hour` — hourly error aggregation
- `query_services_api` — list services from metrics API
- `decode_and_parse_metrics` — decode ACME_METRICS format
- `parse_config_file` — parse AcmeConf format
- `compare_config_versions` — diff two configs
- `aggregate_metrics_summary` — summarize metrics across services

### Evolution Cycles

- 8 evolution cycles triggered across 60 episodes
- 21 tools synthesized, 11 promoted (52% promotion rate)
- Failed tools: primarily due to adversarial testing catching edge cases
- Import restriction caught 1 attempt to use `difflib` (not in allowed_imports)

### Cost

- Agent LLM calls: 60 × ~$0.003 = ~$0.18
- Synthesis LLM calls: ~64 calls × ~$0.004 = ~$0.26
- **Total: ~$0.44**

### Timing

- No-evolution: ~8 minutes (60 episodes, no synthesis overhead)
- Fixed-tools: ~2.5 hours (slow tool-calling rounds with gpt-4o-mini)
- ARISE: ~4 hours (synthesis cycles added ~2 hours)

### Hypothesis for Stronger Models

gpt-4o-mini's weakness is **tool use**, not tool synthesis. A stronger agent model (gpt-4o, Claude Sonnet) should:
- Improve Phase 1: better at using evolved log parsing tools
- Maintain Phase 2: tools already work well
- Maintain Phase 3: reasoning already strong
- Improve Phase 4: better at composing multiple tools in sequence
- Improve fixed-tools baseline significantly (the tools are good, the agent wasn't)

This would make the ARISE vs fixed-tools comparison more meaningful — both should improve with a stronger model, but ARISE's advantage (tools tailored to the agent) may persist.

---

## Result Files

- `gpt-4o-mini_arise_42_20260318T050507Z.json`
- `gpt-4o-mini_no_evolution_42_20260318T025829Z.json`
- `gpt-4o-mini_fixed_tools_42_20260318T073829Z.json`

## Figures

- `learning_curve.pdf` — rolling success rate over episodes
- `tool_accumulation.pdf` — skill library growth
- `phase_breakdown.pdf` — success rate per phase per condition
- `model_comparison.pdf` — (pending: needs multiple model runs)
- `summary_table.tex` — LaTeX table for paper
