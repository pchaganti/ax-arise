# Security

ARISE generates and executes Python code at runtime. This document describes the threat model and built-in mitigations.

## Threat Model

| Threat | Description | Mitigation |
|--------|-------------|------------|
| Malicious generated code | LLM synthesizes code that reads env vars, makes network calls, or accesses the filesystem | Sandbox isolation (subprocess/Docker), `allowed_imports` whitelist |
| Import restriction bypass | Generated code uses `__import__()`, `importlib`, or `exec("import ...")` to circumvent import checks | AST-based static analysis + dynamic import pattern detection |
| Prompt injection via trajectories | Attacker crafts task inputs that manipulate the synthesis prompt | Trajectory data is truncated and sanitized before inclusion in prompts |
| Poisoned skill promotion | A skill passes tests but contains hidden malicious behavior | Adversarial validation, multi-stage testing pipeline, manual review before production |
| S3 manifest tampering | Attacker modifies the shared skill manifest | Use IAM policies to restrict write access to worker process only |
| SQS message injection | Attacker sends crafted messages to the trajectory queue | Use IAM policies + VPC endpoints; messages are validated before processing |

## Sandbox

Generated code runs in an isolated environment:

- **subprocess** (default): Separate Python process with timeout. No network or filesystem isolation.
- **Docker** (recommended for production): Isolated container with no network access, read-only filesystem, and resource limits.

Configure the sandbox backend:

```python
config = ARISEConfig(
    sandbox_backend="docker",  # or "subprocess"
    sandbox_timeout=30,
)
```

## Import Restrictions

Use `allowed_imports` to whitelist which modules generated skills can use:

```python
config = ARISEConfig(
    allowed_imports=["hashlib", "json", "csv", "re", "math", "base64", "datetime"],
)
```

When set, ARISE checks generated code for:
- Static `import` / `from ... import` statements
- Dynamic `__import__("module")` calls
- `importlib.import_module("module")` calls
- `exec()` / `eval()` containing import statements

Skills with disallowed imports are rejected and refined.

**If `allowed_imports` is `None` (default), no restriction is applied.** Set this explicitly in production.

## Recommendations

1. **Always set `allowed_imports`** in production. Start with standard library modules only.
2. **Use Docker sandbox** for untrusted workloads.
3. **Review promoted skills** before deploying to production. Use `arise skills` and `arise inspect` CLI commands.
4. **Restrict S3/SQS IAM permissions**: agent process should have read-only S3 access; only the worker should write.
5. **Monitor evolution costs**: set `max_evolutions_per_hour` to limit LLM spend.
6. **Set `max_library_size`** to prevent unbounded skill accumulation.

## Reporting Vulnerabilities

If you find a security issue, please open a GitHub issue or email the maintainer directly. Do not include exploit code in public issues.
