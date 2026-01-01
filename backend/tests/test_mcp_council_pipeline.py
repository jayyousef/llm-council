import uuid

import pytest
from sqlmodel import select

from backend.src.db.models import Conversation, Message, Run, RunStep
from backend.src.engine.openrouter import OpenRouterResult
from backend.src.engine.pipeline import model_router
from backend.src.mcp.tools import handle_council_pipeline


def _ok_result(model: str, *, content: str, call_id: uuid.UUID, attempt: int, total_tokens: int = 2) -> OpenRouterResult:
    return OpenRouterResult(
        ok=True,
        model=model,
        call_id=call_id,
        attempt=attempt,
        content=content,
        reasoning_details=None,
        usage={"prompt_tokens": total_tokens // 2, "completion_tokens": total_tokens // 2, "total_tokens": total_tokens},
        raw_response={"usage": {"prompt_tokens": total_tokens // 2, "completion_tokens": total_tokens // 2, "total_tokens": total_tokens}},
        latency_ms=1,
        status_code=200,
        error_text=None,
    )


@pytest.mark.asyncio
async def test_mcp_pipeline_pass(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    monkeypatch.setattr(
        model_router,
        "resolve_pipeline_models",
        lambda mode: model_router.PipelineModels(
            leader="leader",
            reviewer="reviewer",
            security="security",
            test_writer="test_writer",
            implementer="implementer",
            gate="gate",
        ),
    )

    async def fake_query_model(model, messages, **kwargs):
        call_id = kwargs["call_id"]
        attempt = kwargs.get("attempt", 0)
        if model == "leader":
            return _ok_result(
                model,
                content=(
                    '{"task_summary":"t","in_scope":["..."],"out_of_scope":["..."],"acceptance_criteria":["ac"],'
                    '"agents_to_invoke":["reviewer","security","implementer","gate"],'
                    '"tests_policy":{"required":false,"reasons":[]},'
                    '"constraints":["no_new_endpoints"],"max_iterations":2,"budget":null}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "reviewer":
            return _ok_result(
                model,
                content='{"verdict":"PASS","issues":[],"missed_requirements":[],"risks":[],"tests_recommended":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        if model == "security":
            return _ok_result(
                model,
                content='{"verdict":"PASS","threats":[],"required_security_controls":[],"tests_required":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        if model == "implementer":
            return _ok_result(
                model,
                content=(
                    '{"final_codex_prompt":"do it","patch_scope":["backend/src/mcp/tools.py"],'
                    '"do_not_change":["no"],"run_commands":["python3 -m pytest -q"],"rollback_plan":["git checkout -- ."]}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "gate":
            return _ok_result(
                model,
                content=(
                    '{"verdict":"PASS","must_fix":[],"acceptance_criteria_met":[{"criterion":"ac","met":true}],'
                    '"tests_required":false}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        raise AssertionError(f"unexpected model: {model}")

    monkeypatch.setattr("backend.src.engine.pipeline.runner.query_model", fake_query_model)

    out = await handle_council_pipeline(session, {"task_description": "do the thing", "mode": "balanced"})
    assert out["run_id"]
    assert out["conversation_id"]
    assert out["gate_verdict"] == "PASS"
    assert out["final_codex_prompt"] == "do it"
    assert out["errors"] == []
    assert out["degraded"] is False

    convo = (await session.exec(select(Conversation))).first()
    assert convo is not None
    msgs = (await session.exec(select(Message).where(Message.conversation_id == convo.id))).all()
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_mcp_pipeline_invalid_json_retry_then_valid(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    monkeypatch.setattr(
        model_router,
        "resolve_pipeline_models",
        lambda mode: model_router.PipelineModels(
            leader="leader",
            reviewer="reviewer",
            security="security",
            test_writer="test_writer",
            implementer="implementer",
            gate="gate",
        ),
    )

    async def fake_query_model(model, messages, **kwargs):
        call_id = kwargs["call_id"]
        attempt = kwargs.get("attempt", 0)
        if model == "leader":
            return _ok_result(
                model,
                content=(
                    '{"task_summary":"t","in_scope":["..."],"out_of_scope":["..."],"acceptance_criteria":["ac"],'
                    '"agents_to_invoke":["reviewer","security","implementer","gate"],'
                    '"tests_policy":{"required":false,"reasons":[]},'
                    '"constraints":["no_new_endpoints"],"max_iterations":2,"budget":null}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "reviewer":
            if attempt == 0:
                return _ok_result(model, content="not json", call_id=call_id, attempt=attempt)
            return _ok_result(
                model,
                content='{"verdict":"PASS","issues":[],"missed_requirements":[],"risks":[],"tests_recommended":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        if model == "security":
            return _ok_result(
                model,
                content='{"verdict":"PASS","threats":[],"required_security_controls":[],"tests_required":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        if model == "implementer":
            return _ok_result(
                model,
                content=(
                    '{"final_codex_prompt":"do it","patch_scope":["backend/src/mcp/tools.py"],'
                    '"do_not_change":["no"],"run_commands":["python3 -m pytest -q"],"rollback_plan":["git checkout -- ."]}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "gate":
            return _ok_result(
                model,
                content=(
                    '{"verdict":"PASS","must_fix":[],"acceptance_criteria_met":[{"criterion":"ac","met":true}],'
                    '"tests_required":false}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        raise AssertionError(f"unexpected model: {model}")

    monkeypatch.setattr("backend.src.engine.pipeline.runner.query_model", fake_query_model)

    out = await handle_council_pipeline(session, {"task_description": "do the thing", "mode": "balanced"})
    assert out["errors"] == []
    assert out["gate_verdict"] == "PASS"

    run_id = uuid.UUID(out["run_id"])
    reviewer_steps = (
        await session.exec(select(RunStep).where(RunStep.run_id == run_id).where(RunStep.agent_role == "reviewer"))
    ).all()
    assert len(reviewer_steps) == 2


@pytest.mark.asyncio
async def test_mcp_pipeline_budget_exceeded_aborts(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    monkeypatch.setattr(
        model_router,
        "resolve_pipeline_models",
        lambda mode: model_router.PipelineModels(
            leader="leader",
            reviewer="reviewer",
            security="security",
            test_writer="test_writer",
            implementer="implementer",
            gate="gate",
        ),
    )

    async def fake_query_model(model, messages, **kwargs):
        call_id = kwargs["call_id"]
        attempt = kwargs.get("attempt", 0)
        # Force budget exceed immediately.
        return _ok_result(model, content='{"task_summary":"t","in_scope":[],"out_of_scope":[],"acceptance_criteria":[],"agents_to_invoke":["implementer","gate"],"tests_policy":{"required":false,"reasons":[]},"constraints":[],"max_iterations":2,"budget":null}', call_id=call_id, attempt=attempt, total_tokens=100)

    monkeypatch.setattr("backend.src.engine.pipeline.runner.query_model", fake_query_model)

    out = await handle_council_pipeline(
        session,
        {"task_description": "do the thing", "mode": "balanced", "budget": {"max_total_tokens": 50}},
    )
    assert out["gate_verdict"] == "FAIL"
    assert out["degraded"] is True
    assert "budget_exceeded" in out["errors"]


@pytest.mark.asyncio
async def test_mcp_pipeline_max_iterations_clamped_and_loop_bounded(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    monkeypatch.setattr(
        model_router,
        "resolve_pipeline_models",
        lambda mode: model_router.PipelineModels(
            leader="leader",
            reviewer="reviewer",
            security="security",
            test_writer="test_writer",
            implementer="implementer",
            gate="gate",
        ),
    )

    calls = {"n": 0}

    async def fake_query_model(model, messages, **kwargs):
        calls["n"] += 1
        call_id = kwargs["call_id"]
        attempt = kwargs.get("attempt", 0)
        if model == "leader":
            prompt = str((messages or [{}])[0].get("content") or "")
            if "revising a Codex implementation prompt" in prompt:
                return _ok_result(
                    model,
                    content=(
                        '{"final_codex_prompt":"do it","patch_scope":["backend/src/mcp/tools.py"],'
                        '"do_not_change":["no"],"run_commands":["python3 -m pytest -q"],"rollback_plan":["git checkout -- ."]}'
                    ),
                    call_id=call_id,
                    attempt=attempt,
                )
            return _ok_result(
                model,
                content=(
                    '{"task_summary":"t","in_scope":["..."],"out_of_scope":["..."],"acceptance_criteria":["ac"],'
                    '"agents_to_invoke":["implementer","gate"],'
                    '"tests_policy":{"required":false,"reasons":[]},'
                    '"constraints":[],"max_iterations":4,"budget":null}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "implementer":
            return _ok_result(
                model,
                content=(
                    '{"final_codex_prompt":"do it","patch_scope":["backend/src/mcp/tools.py"],'
                    '"do_not_change":["no"],"run_commands":["python3 -m pytest -q"],"rollback_plan":["git checkout -- ."]}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "gate":
            return _ok_result(
                model,
                content=(
                    '{"verdict":"FAIL","must_fix":[{"severity":"low","file":"x","issue":"y","suggested_fix":"z"}],'
                    '"acceptance_criteria_met":[{"criterion":"ac","met":false}],"tests_required":false}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        raise AssertionError(f"unexpected model: {model}")

    monkeypatch.setattr("backend.src.engine.pipeline.runner.query_model", fake_query_model)

    out = await handle_council_pipeline(session, {"task_description": "do", "mode": "balanced", "max_iterations": 10})
    assert out["gate_verdict"] == "FAIL"

    run_id = uuid.UUID(out["run_id"])
    run = await session.get(Run, run_id)
    assert run is not None
    assert run.input_json["max_iterations"] == 4

    gate_steps = (await session.exec(select(RunStep).where(RunStep.run_id == run_id).where(RunStep.agent_role == "gate"))).all()
    assert len(gate_steps) == 4


@pytest.mark.asyncio
async def test_mcp_pipeline_scope_violation_fails_without_gate_call(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    monkeypatch.setattr(
        model_router,
        "resolve_pipeline_models",
        lambda mode: model_router.PipelineModels(
            leader="leader",
            reviewer="reviewer",
            security="security",
            test_writer="test_writer",
            implementer="implementer",
            gate="gate",
        ),
    )

    called_gate = {"n": 0}

    async def fake_query_model(model, messages, **kwargs):
        call_id = kwargs["call_id"]
        attempt = kwargs.get("attempt", 0)
        if model == "leader":
            return _ok_result(
                model,
                content=(
                    '{"task_summary":"t","in_scope":["backend/src/mcp/tools.py"],"out_of_scope":["..."],'
                    '"acceptance_criteria":["ac"],"agents_to_invoke":["implementer","gate"],'
                    '"tests_policy":{"required":false,"reasons":[]},"constraints":[],"max_iterations":2,"budget":null}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "implementer":
            return _ok_result(
                model,
                content=(
                    '{"final_codex_prompt":"do it","patch_scope":["backend/src/mcp/tools.py","backend/src/app/main.py"],'
                    '"do_not_change":["no"],"run_commands":["python3 -m pytest -q"],"rollback_plan":["git checkout -- ."]}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "gate":
            called_gate["n"] += 1
            return _ok_result(
                model,
                content=(
                    '{"verdict":"PASS","must_fix":[],"acceptance_criteria_met":[{"criterion":"ac","met":true}],'
                    '"tests_required":false}'
                ),
                call_id=call_id,
                attempt=attempt,
            )
        if model == "reviewer":
            return _ok_result(
                model,
                content='{"verdict":"PASS","issues":[],"missed_requirements":[],"risks":[],"tests_recommended":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        if model == "security":
            return _ok_result(
                model,
                content='{"verdict":"PASS","threats":[],"required_security_controls":[],"tests_required":[]}',
                call_id=call_id,
                attempt=attempt,
            )
        raise AssertionError(f"unexpected model: {model}")

    monkeypatch.setattr("backend.src.engine.pipeline.runner.query_model", fake_query_model)

    out = await handle_council_pipeline(session, {"task_description": "do", "mode": "balanced"})
    assert out["gate_verdict"] == "FAIL"
    assert "scope_violation" in out["errors"]
    assert called_gate["n"] == 0
