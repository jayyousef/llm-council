from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from ..db.models import Run, RunStep


class RunService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_run(
        self,
        conversation_id: uuid.UUID,
        tool_name: str,
        input_json: dict[str, Any],
        owner_key_id: uuid.UUID | None,
    ) -> uuid.UUID:
        run = Run(
            conversation_id=conversation_id,
            tool_name=tool_name,
            input_json=input_json,
            status="running",
            created_at=datetime.utcnow(),
            owner_key_id=owner_key_id,
        )
        self._session.add(run)
        await self._session.flush()
        return run.id

    async def end_run(self, run_id: uuid.UUID, status: str, latency_ms: int | None) -> None:
        run = await self._session.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.ended_at = datetime.utcnow()
        run.latency_ms = latency_ms
        self._session.add(run)
        await self._session.flush()

    async def add_run_step(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        step_type: str,
        agent_role: str,
        model: str,
        *,
        attempt: int = 0,
        is_retry: bool = False,
        output_json: dict[str, Any],
        latency_ms: int | None,
        error_text: Optional[str] = None,
    ) -> uuid.UUID:
        step = RunStep(
            run_id=run_id,
            stage_name=stage_name,
            step_type=step_type,
            agent_role=agent_role,
            model=model,
            attempt=attempt,
            is_retry=is_retry,
            output_json=output_json,
            latency_ms=latency_ms,
            error_text=error_text,
            created_at=datetime.utcnow(),
        )
        self._session.add(step)
        await self._session.flush()
        return step.id
