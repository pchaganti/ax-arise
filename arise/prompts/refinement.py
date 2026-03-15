REFINEMENT_PROMPT = """\
You need to fix/improve a Python tool that has issues.

FUNCTION NAME: {name}
DESCRIPTION: {description}

CURRENT IMPLEMENTATION:
```python
{implementation}
```

CURRENT TEST SUITE:
```python
{test_suite}
```

FEEDBACK / ERRORS:
{feedback}

Fix the implementation (and tests if needed) based on the feedback. Keep the same function name and signature if possible.

CRITICAL RULES:
- All imports must be INSIDE the function body, not at module level. The function is loaded via exec() and must be fully self-contained. Tests can have imports at their top level.
- NEVER hardcode expected values you can't compute (like hashes, encoded data). Instead, compute expected values in the test or test structural properties (e.g., "result is 64 hex chars").

Return ONLY a JSON object:
{{
    "implementation": "fixed Python function source code",
    "test_suite": "updated test code if needed, or the original test code"
}}
"""
