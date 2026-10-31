"""make bench-reports: every report and the dashboard over the last year, all
branches, as the owner (first page of 100, like the screen), timed."""

import time
from datetime import timedelta
from uuid import uuid4

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.db import Database

from .common import Ctx, make_filters
from .dashboard import dashboard
from .reports import REPORTS

EXTRA = {"sales/summary": {"by": "medicine"}, "expiry": {"within": 90}, "stock/slow-moving": {"days": 90}}


async def run(db: Database) -> list[tuple[str, float, int]]:
    owner = CurrentUser(id=uuid4(), role="owner", branch_ids=frozenset(), is_pharmacist=True, permissions=frozenset({"*"}))
    to = clock.today()
    out = []
    async with db.sessionmaker() as s:
        start = time.perf_counter()
        await dashboard(s, None, True, to)
        out.append(("dashboard", time.perf_counter() - start, 0))
        for key, rep in REPORTS.items():
            f = make_filters(to - timedelta(days=365), to, extra=dict(EXTRA.get(key, {})))
            start = time.perf_counter()
            result = await rep.build(Ctx(s, owner, f, None, 100, 0))
            out.append((key, time.perf_counter() - start, result.total))
            await s.rollback()
    return out
