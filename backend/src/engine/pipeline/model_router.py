from __future__ import annotations

from dataclasses import dataclass

from ... import config


@dataclass(frozen=True)
class PipelineModels:
    leader: str
    reviewer: str
    security: str
    test_writer: str
    implementer: str
    gate: str


def _mode_defaults(mode: str) -> tuple[list[str], str]:
    balanced_models = config.MCP_MODELS_BALANCED or list(config.COUNCIL_MODELS)
    balanced_chair = config.MCP_CHAIR_BALANCED or config.CHAIRMAN_MODEL

    if mode == "fast":
        models = config.MCP_MODELS_FAST or list(balanced_models)
        chair = config.MCP_CHAIR_FAST or balanced_chair
        return models, chair
    if mode == "deep":
        models = config.MCP_MODELS_DEEP or list(balanced_models)
        chair = config.MCP_CHAIR_DEEP or balanced_chair
        return models, chair
    return list(balanced_models), balanced_chair


def resolve_pipeline_models(mode: str) -> PipelineModels:
    models, chair = _mode_defaults(mode)
    default_worker = models[0] if models else chair
    default_writer = models[-1] if models else chair

    return PipelineModels(
        leader=config.LEADER_MODEL or chair,
        reviewer=config.REVIEWER_MODEL or default_worker,
        security=config.SECURITY_MODEL or default_worker,
        test_writer=config.TEST_WRITER_MODEL or default_writer,
        implementer=config.IMPLEMENTER_MODEL or chair,
        gate=config.GATE_MODEL or chair,
    )

