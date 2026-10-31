"""seed-demo: refused unless APP_ENV=development (never in production); writes
DEMO branches only and leaves real data alone; running it again replaces it."""

import pytest
from sqlalchemy import func, select

from reports_service.db import db
from reports_service.models import Invoice, KnownBranch
from reports_service.services import demo

from .conftest import PP1, event, invoice, line, product


async def test_refused_outside_development(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(SystemExit):
        await demo.run(db, days=1, per_day=1)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(demo.get_settings(), "environment", "production")
    with pytest.raises(SystemExit):
        await demo.run(db, days=1, per_day=1)


async def test_demo_branches_only_and_repeatable(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    await event("invoice.created", invoice("PP1-INV-1", [line(await product(), 10, "1.00", "0.40")]))
    await demo.run(db, days=2, per_day=3)
    first = await demo.run(db, days=2, per_day=3)
    async with db.sessionmaker() as s:
        codes = set((await s.execute(select(KnownBranch.code))).scalars())
        per_branch = dict((await s.execute(select(Invoice.branch_id, func.count()).group_by(Invoice.branch_id))).all())
    assert {c for c in codes if not c.startswith("DEMO")} == {"PP1", "PP2"}  # real branches untouched
    assert per_branch[PP1] == 1 and sum(per_branch.values()) - 1 == first["invoices"]  # the rerun replaced, not added
