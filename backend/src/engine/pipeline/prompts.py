from __future__ import annotations

import json
from typing import Any

from . import schemas


def _json_only_rules() -> str:
    return (
        "Return ONLY valid JSON. No markdown. No code fences. No extra keys. "
        "If information is missing, call it out in the appropriate schema fields."
    )


def _repo_context_text(repo_context: dict[str, Any] | None) -> str:
    if not repo_context:
        return ""
    files = repo_context.get("files")
    if not isinstance(files, list) or not files:
        return ""

    chunks: list[str] = []
    for f in files[:25]:
        if not isinstance(f, dict):
            continue
        path = str(f.get("path") or "")
        if not path:
            continue
        content = f.get("content")
        summary = f.get("summary")
        body = ""
        if isinstance(content, str) and content.strip():
            body = content.strip()[:4000]
        elif isinstance(summary, str) and summary.strip():
            body = summary.strip()[:1200]
        chunks.append(f"FILE: {path}\n{body}".rstrip())
    if not chunks:
        return ""
    return "Repo context:\n\n" + "\n\n".join(chunks)


def leader_scope_prompt(
    *,
    task_description: str,
    repo_context: dict[str, Any] | None,
    max_iterations: int,
    budget: schemas.PipelineBudget | None,
) -> tuple[str, dict[str, Any]]:
    example = {
        "task_summary": "One sentence summary",
        "in_scope": ["..."],
        "out_of_scope": ["..."],
        "acceptance_criteria": ["..."],
        "agents_to_invoke": ["reviewer", "security", "implementer", "gate"],
        "tests_policy": {"required": True, "reasons": ["..."]},
        "constraints": [
            "Do not add new HTTP endpoints",
            "Do not break existing API behavior",
            "Keep changes minimal and scoped",
        ],
        "max_iterations": max_iterations,
        "budget": budget.model_dump() if budget else None,
    }
    prompt = f"""You are the Leader (PM/Chairman) for a software change pipeline.

Task:
{task_description}

{_repo_context_text(repo_context)}

Rules:
- Define clear scope and acceptance criteria.
- Prevent feature creep. Put anything not required into out_of_scope.
- Ensure max_iterations is exactly {max_iterations}.
- If a budget is provided, include it exactly in the 'budget' field (or null if none).
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def reviewer_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    repo_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    example = {
        "verdict": "PASS",
        "issues": [
            {
                "severity": "med",
                "file": "path/to/file.py",
                "issue": "What is wrong",
                "why": "Why it matters",
                "suggested_fix": "How to fix",
            }
        ],
        "missed_requirements": [],
        "risks": [],
        "tests_recommended": ["python3 -m pytest -q"],
    }
    prompt = f"""You are the Reviewer (Principal Engineer).

Task:
{task_description}

ScopeContract (must comply):
{json.dumps(scope.model_dump(), ensure_ascii=False)}

{_repo_context_text(repo_context)}

Rules:
- Only discuss in_scope and acceptance_criteria. Explicitly ignore out_of_scope.
- Call out risks and missing requirements in the provided fields.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def security_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    repo_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    example = {
        "verdict": "PASS",
        "threats": [
            {
                "severity": "low",
                "area": "logging",
                "description": "Potential secret logging",
                "mitigation": "Ensure secrets are redacted",
            }
        ],
        "required_security_controls": [],
        "tests_required": [],
    }
    prompt = f"""You are Security (DevSecOps).

Task:
{task_description}

ScopeContract (must comply):
{json.dumps(scope.model_dump(), ensure_ascii=False)}

{_repo_context_text(repo_context)}

Rules:
- Only discuss in_scope and acceptance_criteria. Explicitly ignore out_of_scope.
- Focus on auth, DB, logging, network, deps/supply-chain risks relevant to the scope.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def test_writer_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    reviewer: schemas.ReviewOutput | None,
    security: schemas.SecurityOutput | None,
    repo_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    example = {
        "tests_to_add": [
            {
                "type": "unit",
                "target": "backend/src/...",
                "files": ["backend/tests/test_example.py"],
                "cases": ["..."],
            }
        ],
        "commands": ["python3 -m pytest -q"],
        "notes": [],
    }
    reviewer_json = reviewer.model_dump() if reviewer else None
    security_json = security.model_dump() if security else None
    prompt = f"""You are the Test Writer (SDET).

Task:
{task_description}

ScopeContract (must comply):
{json.dumps(scope.model_dump(), ensure_ascii=False)}

Reviewer output:
{json.dumps(reviewer_json, ensure_ascii=False)}

Security output:
{json.dumps(security_json, ensure_ascii=False)}

{_repo_context_text(repo_context)}

Rules:
- Only propose tests that validate acceptance_criteria and in_scope.
- Keep commands executable in this repo.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def implementer_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    reviewer: schemas.ReviewOutput | None,
    security: schemas.SecurityOutput | None,
    test_plan: schemas.TestPlanOutput | None,
    repo_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    example = {
        "final_codex_prompt": "A complete Codex prompt describing the patch to implement, with constraints.",
        "patch_scope": ["backend/src/app/main.py"],
        "do_not_change": ["No new endpoints", "Do not refactor unrelated code"],
        "run_commands": ["python3 -m pytest -q"],
        "rollback_plan": ["git checkout -- <files>"],
    }
    prompt = f"""You are the Implementer (Codex prompt writer). Produce a high-quality Codex prompt.

Task:
{task_description}

ScopeContract (MUST comply; no feature creep):
{json.dumps(scope.model_dump(), ensure_ascii=False)}

Reviewer output:
{json.dumps(reviewer.model_dump() if reviewer else None, ensure_ascii=False)}

Security output:
{json.dumps(security.model_dump() if security else None, ensure_ascii=False)}

Test plan:
{json.dumps(test_plan.model_dump() if test_plan else None, ensure_ascii=False)}

{_repo_context_text(repo_context)}

Rules:
- Only cover in_scope and acceptance_criteria. Explicitly ignore out_of_scope.
- Your patch_scope must reflect the files that should change.
- Your final_codex_prompt must be specific, bounded, and include constraints.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def implementer_revision_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    previous_prompt: schemas.CodexPromptOutput,
    must_fix: list[schemas.MustFixItem],
) -> tuple[str, dict[str, Any]]:
    example = {
        "final_codex_prompt": "Revised Codex prompt addressing only must_fix items.",
        "patch_scope": previous_prompt.patch_scope,
        "do_not_change": previous_prompt.do_not_change,
        "run_commands": previous_prompt.run_commands,
        "rollback_plan": previous_prompt.rollback_plan,
    }
    prompt = f"""You are revising a Codex implementation prompt after a failed gate.

Task:
{task_description}

ScopeContract (MUST comply; no feature creep):
{json.dumps(scope.model_dump(), ensure_ascii=False)}

Previous CodexPromptOutput:
{json.dumps(previous_prompt.model_dump(), ensure_ascii=False)}

Gate must_fix list (address ONLY these):
{json.dumps([m.model_dump() for m in must_fix], ensure_ascii=False)}

Rules:
- Modify ONLY what is necessary to address must_fix.
- Do NOT expand scope, do NOT add new files unless must_fix requires it.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example


def gate_prompt(
    *,
    task_description: str,
    scope: schemas.ScopeContract,
    reviewer: schemas.ReviewOutput | None,
    security: schemas.SecurityOutput | None,
    test_plan: schemas.TestPlanOutput | None,
    implementer: schemas.CodexPromptOutput,
) -> tuple[str, dict[str, Any]]:
    example = {
        "verdict": "PASS",
        "must_fix": [
            {
                "severity": "high",
                "file": "backend/src/...",
                "issue": "What must be fixed",
                "suggested_fix": "Concrete fix",
            }
        ],
        "acceptance_criteria_met": [{"criterion": "....", "met": True}],
        "tests_required": True,
    }
    prompt = f"""You are the Gate. Decide PASS/FAIL.

Task:
{task_description}

ScopeContract:
{json.dumps(scope.model_dump(), ensure_ascii=False)}

Reviewer output:
{json.dumps(reviewer.model_dump() if reviewer else None, ensure_ascii=False)}

Security output:
{json.dumps(security.model_dump() if security else None, ensure_ascii=False)}

Test plan:
{json.dumps(test_plan.model_dump() if test_plan else None, ensure_ascii=False)}

CodexPromptOutput:
{json.dumps(implementer.model_dump(), ensure_ascii=False)}

Rules:
- Enforce no feature creep: only accept if CodexPromptOutput is bounded to in_scope and acceptance_criteria.
- If scope.in_scope includes file-path-like entries, FAIL if implementer.patch_scope contains any file not included in scope.in_scope.
- Be strict. If uncertain, FAIL with must_fix items.
- {_json_only_rules()}

Output JSON matching this example exactly:
{json.dumps(example, ensure_ascii=False)}
"""
    return prompt, example

