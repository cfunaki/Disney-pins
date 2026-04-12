import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_comp_lookup_budget_round_trip(db_session):
    from src.models import CompLookupBudget
    row = CompLookupBudget(date="2026-04-12", calls=3)
    db_session.add(row)
    await db_session.commit()
    loaded = (await db_session.execute(
        select(CompLookupBudget).where(CompLookupBudget.date == "2026-04-12")
    )).scalar_one()
    assert loaded.calls == 3


@pytest.mark.asyncio
async def test_comp_lookup_budget_primary_key_is_date(db_session):
    from src.models import CompLookupBudget
    db_session.add(CompLookupBudget(date="2026-04-11", calls=1))
    db_session.add(CompLookupBudget(date="2026-04-11", calls=2))
    with pytest.raises(Exception):
        await db_session.commit()
