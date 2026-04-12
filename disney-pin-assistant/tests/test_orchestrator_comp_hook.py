from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_orchestrator_calls_lookup_comps_after_priced(session_factory):
    from src.models import Pin, PinStatus
    from src.pipeline import orchestrator

    async with session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED,
                  reference_parsed_fields={"characters": ["Stitch"], "franchise": "Lilo & Stitch"})
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    with patch(
        "src.pipeline.orchestrator.lookup_comps_for_pin",
        new=AsyncMock(return_value=None),
    ) as m:
        await orchestrator.run_comp_lookup_hook(session_factory, pin_id)
    m.assert_awaited_once_with(session_factory, pin_id)


@pytest.mark.asyncio
async def test_orchestrator_hook_swallows_lookup_errors(session_factory):
    from src.models import Pin, PinStatus
    from src.pipeline import orchestrator

    async with session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED)
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    with patch(
        "src.pipeline.orchestrator.lookup_comps_for_pin",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        # Should not raise
        await orchestrator.run_comp_lookup_hook(session_factory, pin_id)
