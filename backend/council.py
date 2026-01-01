"""Compatibility re-exports for the prototype layout.

Phase A moves orchestration to `backend.src.engine.council`.
"""

from backend.src.engine.council import (  # noqa: F401
    calculate_aggregate_rankings,
    generate_conversation_title,
    parse_ranking_from_text,
    run_full_council,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
)

