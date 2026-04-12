# Agent Input / Output Contracts

Each agent receives a dict and returns a dict. Redis node state tracks status; the `output_ref` field points to the output key or a JSON blob stored separately.

---

## Block 1 — Intent

### `prompt_parser`
```python
input:  { "raw_goal": str }
output: ParsedGoal {
    "raw_goal":       str,
    "domains":        list[str],          # matched KNOWN_DOMAINS stems
    "entities": {
        "build_target":   str | None,
        "integrations":   list[str],
        "deploy_target":  str | None,
    },
    "unknown_fields": list[str],          # fields parser could not fill
}
```

### `ambiguity_scorer`
```python
input:  ParsedGoal (above)
output: ScoredUnknowns {
    "scores":      { field_name: float },  # 0.0–1.0 per field
    "must_ask":    list[str],              # scores >= 0.7
    "can_default": list[str],             # scores <  0.7
}
```
`build_target` scores 0.85 — always `must_ask` when absent.

### `defaults_agent`
```python
input:  { "parsed_goal": ParsedGoal, "scored": ScoredUnknowns }
output: IntentSpec (fully populated, ready for mesh)
        # can_default fields filled from DEFAULTS in intent_spec.py
        # must_ask fields must already be answered before this agent runs
```

---

## Block 2 — Mesh (all stubs)

### `researcher`
```python
input:  { "intent": IntentSpec, "skills": list[str] }  # skill names to load
output: { "research_notes": str, "sources": list[str] }
```

### `architect`
```python
input:  { "intent": IntentSpec, "research_notes": str }
output: ArchitectureSpec {
    "components":   list[str],
    "tech_stack":   dict[str, str],
    "entry_points": list[str],
    "deploy_notes": str,
}
```

### `coder`
```python
input:  { "intent": IntentSpec, "arch": ArchitectureSpec }
output: { "files": dict[str, str] }   # path → content
```

### `tester`
```python
input:  { "intent": IntentSpec, "files": dict[str, str] }
output: { "test_results": str, "passed": bool }
```

### `deployer`
```python
input:  { "intent": IntentSpec, "files": dict[str, str] }
output: { "deploy_url": str, "deploy_log": str }
```

### `monitor_setup`
```python
input:  { "intent": IntentSpec, "deploy_url": str }
output: { "monitor_config": dict }
```

---

## Block 3 — Router (all stubs)

### `signal_collector`
```python
input:  { "run_id": str, "deploy_url": str }
output: { "signals": list[dict] }   # raw log lines, metrics, etc.
```

### `scorer`
```python
input:  { "signals": list[dict] }
output: { "health_score": float, "anomalies": list[str] }
```

### `router`
```python
input:  { "health_score": float, "anomalies": list[str] }
output: { "decision": "pass" | "fix" | "rollback", "reason": str }
```

---

## Block 4 — Monitor / Fix Loop (all stubs)

### `log_watcher`
```python
input:  { "run_id": str, "app_name": str }
output: { "log_lines": list[str] }
```

### `anomaly_classifier`
```python
input:  { "log_lines": list[str] }
output: { "anomalies": list[dict], "severity": "low" | "medium" | "high" }
```

### `context_builder`
```python
input:  { "anomalies": list[dict], "intent": IntentSpec }
output: { "context": str }   # assembled prompt context for fix_agent
```

### `fix_agent`
```python
input:  { "context": str, "files": dict[str, str] }
output: { "patch": dict[str, str], "explanation": str }
```

### `validator`
```python
input:  { "patch": dict[str, str] }
output: { "valid": bool, "errors": list[str] }
```

### `skills_updater`
```python
input:  { "run_id": str, "context": str, "outcome": "pass" | "fail" }
output: { "updated_skills": list[str] }   # skill stems that were appended
# Uses SkillsStore.append — never SkillsStore.write_new on existing skills
```

---

## Shared types

```python
# agent/shared/intent_spec.py
IntentSpec = {
    "run_id":                    str,
    "goal":                      str,
    "integrations":              list[str],
    "deploy_target":             str,          # default: "fly.io"
    "llm": {
        "provider":              str,          # default: "anthropic"
        "model":                 str,          # default: "claude-sonnet-4-6"
        "temperature":           float,        # default: 0
        "base_url":              str | None,
    },
    "preferences": {
        "risk":                  str,          # default: "low"
        "notify":                str,          # default: "on_failure"
        "auto_merge_if_ci_green": bool,        # default: True
    },
}
```
