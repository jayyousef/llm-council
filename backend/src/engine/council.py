"""3-stage LLM Council orchestration (hardened Stage 2 JSON)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from ..config import CHAIRMAN_MODEL, COUNCIL_MODELS
from .openrouter import query_model, query_models_parallel
from .schemas import Stage2JudgeOutput


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    # Strict JSON only. No regex fallback.
    try:
        obj = json.loads(ranking_text)
        validated = Stage2JudgeOutput.model_validate(obj)
        return list(validated.final_ranking)
    except Exception:
        return []


async def stage1_collect_responses(user_query: str) -> List[Dict[str, Any]]:
    messages = [{"role": "user", "content": user_query}]
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    stage1_results: list[dict[str, Any]] = []
    for model, result in responses.items():
        if result.ok and result.content is not None:
            stage1_results.append({"model": model, "response": result.content or ""})
    return stage1_results


async def stage2_collect_rankings(
    user_query: str, stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    labels = [chr(65 + i) for i in range(len(stage1_results))]
    label_to_model = {
        f"Response {label}": result["model"] for label, result in zip(labels, stage1_results)
    }

    responses_text = "\n\n".join(
        [f"Response {label}:\n{result['response']}" for label, result in zip(labels, stage1_results)]
    )

    schema_example = {
        "evaluations": [
            {"label": "Response A", "pros": ["..."], "cons": ["..."]},
            {"label": "Response B", "pros": ["..."], "cons": ["..."]},
        ],
        "final_ranking": ["Response A", "Response B"],
        "failure_modes_top1": ["..."],
        "verification_steps": ["..."],
    }

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Return ONLY valid JSON matching this exact schema (no markdown, no extra text):
{json.dumps(schema_example, ensure_ascii=False)}

Rules:
- "evaluations" must include one entry per response label present above.
- "final_ranking" must be a list of the response labels from best to worst.
- "failure_modes_top1" must list likely failure modes of the top-ranked response.
- "verification_steps" must list concrete steps a user can take to verify the top-ranked response.
"""

    responses = await query_models_parallel(COUNCIL_MODELS, [{"role": "user", "content": ranking_prompt}])

    stage2_results: list[dict[str, Any]] = []
    for model, result in responses.items():
        if not result.ok or result.content is None:
            continue

        raw_text = result.content
        parsed_ranking: list[str] = []
        parsed_json: dict[str, Any] | None = None
        validation_error: str | None = None

        def _try_parse(text: str) -> tuple[list[str], dict[str, Any] | None, str | None]:
            try:
                obj = json.loads(text)
                validated = Stage2JudgeOutput.model_validate(obj)
                return validated.final_ranking, validated.model_dump(), None
            except Exception as e:
                return [], None, str(e)

        parsed_ranking, parsed_json, validation_error = _try_parse(raw_text)
        if validation_error:
            correction_prompt = f"""Your previous output was invalid.
You MUST output ONLY valid JSON matching this schema:
{json.dumps(schema_example, ensure_ascii=False)}

Here was your previous output:
{raw_text}

Error:
{validation_error}
"""
            retry = await query_model(model, [{"role": "user", "content": correction_prompt}])
            if retry.ok and retry.content is not None:
                raw_text = retry.content
                parsed_ranking, parsed_json, validation_error = _try_parse(raw_text)

        stage2_results.append(
            {
                "model": model,
                "ranking": raw_text,
                "parsed_ranking": parsed_ranking,
                "parsed_json": parsed_json,
                "validation_error": validation_error,
            }
        )

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str, stage1_results: List[Dict[str, Any]], stage2_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    stage1_text = "\n\n".join(
        [f"Model: {r['model']}\nResponse: {r['response']}" for r in stage1_results]
    )
    stage2_text = "\n\n".join(
        [f"Model: {r['model']}\nRanking: {r['ranking']}" for r in stage2_results]
    )

    verification_steps: list[str] = []
    for r in stage2_results:
        parsed = r.get("parsed_json") if isinstance(r, dict) else None
        if isinstance(parsed, dict):
            steps = parsed.get("verification_steps")
            if isinstance(steps, list):
                verification_steps.extend([str(s) for s in steps if s])

    verification_text = ""
    if verification_steps:
        deduped: list[str] = []
        seen = set()
        for s in verification_steps:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        verification_text = "\n\nJudges suggested verification steps:\n" + "\n".join(
            [f"- {s}" for s in deduped[:12]]
        )

    prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}
{verification_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question.

When relevant, include a short "Verification checklist" section with concrete steps the user can take to validate the answer.
"""

    response = await query_model(CHAIRMAN_MODEL, [{"role": "user", "content": prompt}])
    if not response.ok or response.content is None:
        return {"model": CHAIRMAN_MODEL, "response": "Error: Unable to generate final synthesis."}

    return {"model": CHAIRMAN_MODEL, "response": response.content or ""}


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]], label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    from collections import defaultdict

    model_positions: dict[str, list[int]] = defaultdict(list)

    for ranking in stage2_results:
        if ranking.get("valid") is not True:
            continue
        parsed_ranking = ranking.get("parsed_ranking") or []
        if not isinstance(parsed_ranking, list):
            continue
        if len(parsed_ranking) == 0:
            continue
        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({"model": model, "average_rank": round(avg_rank, 2), "rankings_count": len(positions)})

    aggregate.sort(key=lambda x: x["average_rank"])
    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    response = await query_model(
        "google/gemini-2.5-flash",
        [{"role": "user", "content": title_prompt}],
        timeout_seconds=30.0,
    )
    if not response.ok or response.content is None:
        return "New Conversation"

    title = (response.content or "New Conversation").strip().strip("\"'")
    if len(title) > 50:
        title = title[:47] + "..."
    return title


async def run_full_council(user_query: str) -> Tuple[List, List, Dict, Dict]:
    stage1_results = await stage1_collect_responses(user_query)
    if not stage1_results:
        return [], [], {"model": "error", "response": "All models failed to respond. Please try again."}, {}

    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
    stage3_result = await stage3_synthesize_final(user_query, stage1_results, stage2_results)

    metadata = {"label_to_model": label_to_model, "aggregate_rankings": aggregate_rankings}
    return stage1_results, stage2_results, stage3_result, metadata
