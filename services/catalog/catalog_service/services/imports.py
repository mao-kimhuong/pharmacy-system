"""Import Product: upload an Excel file → validate every row → commit.

Rules:
- Upload saves nothing to medicines; it stores the rows with their errors.
- One row per pack unit, grouped by SKU. Product columns may repeat on every
  row of a SKU; blank = same as the SKU's first value, a different value is a
  row error ("conflicts with row N").
- An existing SKU is updated (blank cells keep the saved value); a new SKU is
  created. Pack units are matched by name; ones missing from the file stay.
- Categories and brands are matched by English name. Missing ones are listed
  (new_categories / new_brands); rows using them are UNKNOWN_CATEGORY /
  UNKNOWN_BRAND errors unless the commit says create_missing=true.
- Commit validates again against the current data and writes everything in
  ONE transaction. It is refused while rows have errors, unless
  skip_invalid=true (then every SKU with an error is skipped as a whole).
- Every product created or changed: medicine.* event + User Log entry; created
  categories / brands and the import itself are logged too.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Brand, Category, ImportRow, Medicine, OutboxEvent, PackUnit, ProductImport
from . import lookups, medicines
from .common import SERVICE, SKU_PATTERN, clean, commit, not_found
from .spreadsheet import PRODUCT_KEYS, read_rows

BARCODE = re.compile(r"^[0-9A-Za-z._\-/+]{3,48}$")
MAX_LEN = {"brand_name": 160, "generic_name": 160, "strength": 60, "dosage_form": 60, "name_km": 160,
           "category": 120, "brand": 120, "manufacturer": 160, "base_unit": 40, "pack_unit": 40}  # fmt: skip
YES = {"yes", "y", "true", "1", "x", "បាទ", "ចាស", "មាន"}
NO = {"no", "n", "false", "0", "ទេ", "គ្មាន"}
SCHEDULE_ALIASES = {
    "I": "I",
    "II": "II",
    "III": "III",
    "IV": "IV",
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
}
CLEAR = {"none", "-"}
UNKNOWN_CODES = {ErrorCode.UNKNOWN_CATEGORY.value, ErrorCode.UNKNOWN_BRAND.value}
_TEXT_FIELDS = ("brand_name", "generic_name", "strength", "dosage_form", "name_km", "manufacturer")


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()  # "keep the saved value"


@dataclass
class RowResult:
    row_no: int
    data: dict[str, str]
    sku: str = ""
    action: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)

    def error(self, column: str, message: str, code: ErrorCode = ErrorCode.VALIDATION_ERROR) -> None:
        self.errors.append({"field": column, "code": code.value, "message": message})

    def blocking(self, create_missing: bool) -> bool:
        return any(not (create_missing and e["code"] in UNKNOWN_CODES) for e in self.errors)


@dataclass
class PackPlan:
    name: str
    qty_in_base: int
    barcode: Any  # str | None | UNSET
    sell_price: Decimal | None  # None = keep
    is_base: bool
    existing: PackUnit | None
    row: RowResult


@dataclass
class ProductPlan:
    sku: str
    existing: Medicine | None
    rows: list[RowResult]
    fields: dict[str, Any] = field(default_factory=dict)  # only the columns given
    category: str | None = None  # English name, None = keep / none
    brand: str | None = None
    rx: bool | None = None
    schedule: Any = UNSET
    packs: list[PackPlan] = field(default_factory=list)

    def blocking(self, create_missing: bool) -> bool:
        return any(r.blocking(create_missing) for r in self.rows)


@dataclass
class Validation:
    rows: list[RowResult]
    plans: list[ProductPlan]
    new_categories: list[str]
    new_brands: list[str]

    @property
    def error_rows(self) -> int:
        return sum(1 for r in self.rows if r.errors)


# ---------------------------------------------------------------- cell parsing


def _bool(text: str) -> bool | None:
    t = text.strip().lower()
    if not t:
        return None
    if t in YES:
        return True
    if t in NO:
        return False
    raise ValueError("write yes or no")


def _int(text: str, minimum: int, maximum: int = 10_000_000) -> int:
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("must be a whole number") from exc
    if number != number.to_integral_value() or not minimum <= number <= maximum:
        raise ValueError(f"must be a whole number from {minimum} to {maximum}")
    return int(number)


def _price(text: str) -> Decimal:
    try:
        value = Decimal(text.replace("$", "").strip())  # "2,30" is refused, not read as 230
    except InvalidOperation as exc:
        raise ValueError("must be a price in USD, e.g. 2.50") from exc
    if not value.is_finite() or value < 0 or value >= Decimal("1e12"):
        raise ValueError("must be a price from 0 in USD, e.g. 2.50")
    if value != value.quantize(medicines.CENT):
        raise ValueError("at most 2 decimals (cents)")
    return value.quantize(medicines.CENT)


def _storage(text: str) -> str:
    if text.strip().lower() not in ("room", "cold"):
        raise ValueError("write room or cold")
    return text.strip().lower()


def _schedule(text: str) -> Any:
    t = text.strip()
    if not t:
        return UNSET
    if t.lower() in CLEAR:
        return None
    if t.upper() in SCHEDULE_ALIASES:
        return SCHEDULE_ALIASES[t.upper()]
    raise ValueError("must be blank, I, II, III or IV")


# ---------------------------------------------------------------- validation


async def validate(session: AsyncSession, raw_rows: list[tuple[int, dict[str, str]]]) -> Validation:
    rows = [RowResult(row_no, dict(data)) for row_no, data in raw_rows]
    groups: dict[str, list[RowResult]] = {}
    for r in rows:
        sku = clean(r.data.get("sku")).upper()
        if not sku:
            r.error("sku", "sku is required")
        elif not SKU_PATTERN.match(sku):
            r.error("sku", "sku: 1-40 capital letters, digits or . _ - /")
        else:
            r.sku = sku
            groups.setdefault(sku, []).append(r)
        for column, limit in MAX_LEN.items():
            if len(r.data.get(column, "")) > limit:
                r.error(column, f"{column}: at most {limit} characters")

    existing = {
        m.sku: m
        for m in (await session.execute(select(Medicine).where(Medicine.sku.in_(list(groups))))).scalars()
    }
    plans = [_plan_product(sku, group_rows, existing.get(sku)) for sku, group_rows in groups.items()]
    new_categories = await _check_lookups(session, plans, Category)
    new_brands = await _check_lookups(session, plans, Brand)
    await _check_barcodes(session, plans)
    return Validation(rows, plans, new_categories, new_brands)


def _plan_product(sku: str, rows: list[RowResult], existing: Medicine | None) -> ProductPlan:
    plan = ProductPlan(sku=sku, existing=existing, rows=rows)
    first = rows[0]
    action = "update" if existing else "create"
    for r in rows:
        r.action = action

    # Product columns: first non-blank value wins; a different value later is an error.
    merged: dict[str, tuple[str, RowResult]] = {}
    for r in rows:
        for key in PRODUCT_KEYS:
            value = r.data.get(key, "")
            if key == "sku" or not value:
                continue
            if key not in merged:
                merged[key] = (value, r)
            elif value.casefold() != merged[key][0].casefold():
                r.error(key, f"{key}: conflicts with row {merged[key][1].row_no} ({merged[key][0]!r})")

    def parse(key: str, parser, *args) -> Any:
        if key not in merged:
            return UNSET
        value, source = merged[key]
        try:
            return parser(value, *args)
        except ValueError as exc:
            source.error(key, f"{key}: {exc}")
            return UNSET

    for key in _TEXT_FIELDS:
        if key in merged:
            plan.fields[key] = merged[key][0]
    if "base_unit" in merged:
        plan.fields["base_unit"] = merged["base_unit"][0]
    storage = parse("storage", _storage)
    if storage is not UNSET:
        plan.fields["storage"] = storage
    reorder = parse("reorder_level", _int, 0)
    if reorder is not UNSET:
        plan.fields["reorder_level"] = reorder
    rx = parse("rx_only", _bool)
    plan.rx = None if rx is UNSET else rx
    plan.schedule = parse("controlled_schedule", _schedule)
    plan.category = merged["category"][0] if "category" in merged else None
    plan.brand = merged["brand"][0] if "brand" in merged else None

    if existing is None:
        for key in ("brand_name", "generic_name", "base_unit"):
            if key not in merged:
                first.error(key, f"{key} is required for a new product")

    schedule = (
        (existing.controlled_schedule if existing else None) if plan.schedule is UNSET else plan.schedule
    )
    if schedule and plan.rx is False:
        source = merged["rx_only"][1]
        source.error("rx_only", "a controlled medicine is always prescription-only (rx_only must be yes)")

    base_unit = plan.fields.get("base_unit") or (existing.base_unit if existing else "")
    if existing and "base_unit" in plan.fields:
        clash = next((p for p in existing.pack_units if not p.is_base
                      and p.name.casefold() == base_unit.casefold()), None)  # fmt: skip
        if clash:
            merged["base_unit"][1].error(
                "base_unit", f"base_unit: {sku} already has a pack unit {clash.name!r}"
            )
    _plan_packs(plan, rows, base_unit)
    if existing is None and base_unit and not any(p.is_base for p in plan.packs):
        first.error(
            "pack_unit", f"no row for the base unit {base_unit!r} (pack_unit {base_unit}, qty_in_base 1)"
        )
    return plan


def _plan_packs(plan: ProductPlan, rows: list[RowResult], base_unit: str) -> None:
    seen: dict[str, RowResult] = {}
    existing = plan.existing
    for r in rows:
        name = r.data.get("pack_unit", "")
        if not name:
            r.error("pack_unit", "pack_unit is required (e.g. tablet, strip, box)")
            continue
        if name.casefold() in seen:
            r.error("pack_unit", f"pack_unit {name!r} repeats row {seen[name.casefold()].row_no}")
            continue
        seen[name.casefold()] = r
        is_base = bool(base_unit) and name.casefold() == base_unit.casefold()
        try:
            qty = _int(r.data.get("qty_in_base", ""), 1, 1_000_000)
        except ValueError as exc:
            r.error("qty_in_base", f"qty_in_base: {exc}")
            continue
        if is_base and qty != 1:
            r.error("qty_in_base", f"the base unit {base_unit!r} must have qty_in_base 1")
        if not is_base and qty == 1:
            r.error("qty_in_base", f"qty_in_base 1 is only for the base unit ({base_unit or 'base_unit'})")

        match = None
        if existing is not None:
            match = (
                existing.base_pack
                if is_base
                else next(
                    (
                        p
                        for p in existing.pack_units
                        if not p.is_base and p.name.casefold() == name.casefold()
                    ),
                    None,
                )
            )
        sell_price = None
        price_text = r.data.get("sell_price_usd", "")
        if price_text:
            try:
                sell_price = _price(price_text)
            except ValueError as exc:
                r.error("sell_price_usd", f"sell_price_usd: {exc}")
        elif match is None:
            r.error("sell_price_usd", "sell_price_usd is required for a new pack unit")
        barcode = r.data.get("barcode", "")
        if barcode and not BARCODE.match(barcode):
            r.error("barcode", "barcode: 3-48 letters, digits or . _ - / +")
        plan.packs.append(
            PackPlan(name=name, qty_in_base=qty, barcode=barcode or (UNSET if match else None),
                     sell_price=sell_price, is_base=is_base, existing=match, row=r)
        )  # fmt: skip


async def _check_lookups(session: AsyncSession, plans: list[ProductPlan], model: type) -> list[str]:
    column = "category" if model is Category else "brand"
    code = ErrorCode.UNKNOWN_CATEGORY if model is Category else ErrorCode.UNKNOWN_BRAND
    wanted = {getattr(p, column).casefold(): getattr(p, column) for p in plans if getattr(p, column)}
    if not wanted:
        return []
    found = {
        row.name_en.casefold(): row
        for row in (
            await session.execute(
                select(model).where(func.lower(model.name_en).in_([k.lower() for k in wanted]))
            )
        ).scalars()
    }
    missing: dict[str, str] = {}
    for plan in plans:
        name = getattr(plan, column)
        if not name:
            continue
        source = next((r for r in plan.rows if r.data.get(column)), plan.rows[0])
        row = found.get(name.casefold())
        if row is None:
            missing.setdefault(name.casefold(), name)
            source.error(column, f"{column} {name!r} does not exist yet (allow new ones on commit)", code)
        elif not row.is_active:
            source.error(column, f"{column} {row.name_en!r} is deactivated")
    return sorted(missing.values(), key=str.casefold)


async def _check_barcodes(session: AsyncSession, plans: list[ProductPlan]) -> None:
    first_use: dict[str, RowResult] = {}
    wanted: list[PackPlan] = []
    for plan in plans:
        for pack in plan.packs:
            if not isinstance(pack.barcode, str):
                continue
            if pack.barcode in first_use:
                pack.row.error(
                    "barcode", f"barcode {pack.barcode} repeats row {first_use[pack.barcode].row_no}",
                    ErrorCode.DUPLICATE_BARCODE,
                )  # fmt: skip
                continue
            first_use[pack.barcode] = pack.row
            wanted.append(pack)
    if not wanted:
        return
    owners = {
        row.barcode: row
        for row in await session.execute(
            select(PackUnit.id, PackUnit.barcode, PackUnit.name, Medicine.sku)
            .join(Medicine, Medicine.id == PackUnit.medicine_id)
            .where(PackUnit.barcode.in_([p.barcode for p in wanted]))
        )
    }
    for pack in wanted:
        owner = owners.get(pack.barcode)
        if owner is not None and (pack.existing is None or pack.existing.id != owner.id):
            pack.row.error(
                "barcode", f"barcode {pack.barcode} is already used by {owner.sku} ({owner.name})",
                ErrorCode.DUPLICATE_BARCODE,
            )  # fmt: skip


# ---------------------------------------------------------------- upload, read


def _status(validation: Validation) -> str:
    return "has_errors" if validation.error_rows else "validated"


async def create_import(
    session: AsyncSession, actor: CurrentUser, file_name: str, data: bytes
) -> ProductImport:
    raw_rows = read_rows(data)
    validation = await validate(session, raw_rows)
    imp = ProductImport(
        file_name=clean(file_name)[:255] or "import.xlsx",
        file_sha256=hashlib.sha256(data).hexdigest(),
        status=_status(validation),
        total_rows=len(validation.rows),
        error_rows=validation.error_rows,
        new_categories=validation.new_categories,
        new_brands=validation.new_brands,
        created_count=0,
        updated_count=0,
        skipped_skus=[],
        created_by=actor.id,
    )
    session.add(imp)
    await session.flush()
    session.add_all(
        ImportRow(import_id=imp.id, row_no=r.row_no, sku=r.sku, action=r.action, data=r.data, errors=r.errors)
        for r in validation.rows
    )
    _audit(session, actor, "import.uploaded", imp, {
        "file_name": imp.file_name, "rows": imp.total_rows, "error_rows": imp.error_rows,
    })  # fmt: skip
    await commit(session)
    return imp


async def get_import(session: AsyncSession, import_id: UUID, *, lock: bool = False) -> ProductImport:
    query = select(ProductImport).where(ProductImport.id == import_id)
    if lock:
        query = query.with_for_update()
    imp = (await session.execute(query)).scalar_one_or_none()
    if imp is None:
        raise not_found("Import")
    return imp


async def list_imports(session: AsyncSession, page: int, size: int) -> tuple[list[ProductImport], int]:
    total = (await session.execute(select(func.count(ProductImport.id)))).scalar_one()
    rows = await session.execute(
        select(ProductImport).order_by(ProductImport.created_at.desc(), ProductImport.id)
        .offset((page - 1) * size).limit(size)
    )  # fmt: skip
    return list(rows.scalars()), int(total)


async def list_rows(
    session: AsyncSession, import_id: UUID, errors_only: bool, page: int, size: int
) -> tuple[list[ImportRow], int]:
    rows = list(
        (await session.execute(
            select(ImportRow).where(ImportRow.import_id == import_id).order_by(ImportRow.row_no)
        )).scalars()
    )  # fmt: skip
    if errors_only:
        rows = [r for r in rows if r.errors]
    return rows[(page - 1) * size : page * size], len(rows)


def _audit(session: AsyncSession, actor: CurrentUser, action: str, imp: ProductImport, after: dict) -> None:
    record_audit(
        session, OutboxEvent, service=SERVICE, action=action, entity_type="import",
        entity_id=imp.id, actor=actor, after=after,
    )  # fmt: skip


# ---------------------------------------------------------------- commit


async def commit_import(
    session: AsyncSession, actor: CurrentUser, import_id: UUID, *, create_missing: bool, skip_invalid: bool
) -> ProductImport:
    imp = await get_import(session, import_id, lock=True)
    if imp.status == "committed":
        raise AppError(ErrorCode.IMPORT_STATE, "This import was already committed", status_code=409)
    stored = list(
        (await session.execute(
            select(ImportRow).where(ImportRow.import_id == imp.id).order_by(ImportRow.row_no)
        )).scalars()
    )  # fmt: skip
    # Data may have changed since the upload (another import, a new barcode): check again.
    validation = await validate(session, [(r.row_no, r.data) for r in stored])
    by_row = {r.row_no: r for r in validation.rows}
    for row in stored:
        row.errors = by_row[row.row_no].errors
        row.action = by_row[row.row_no].action
    imp.error_rows = validation.error_rows
    imp.new_categories = validation.new_categories
    imp.new_brands = validation.new_brands
    imp.status = _status(validation)

    blocked = [r for r in validation.rows if r.blocking(create_missing)]
    good = [p for p in validation.plans if not p.blocking(create_missing)]
    if (blocked and not skip_invalid) or not good:
        await commit(session)  # keep the fresh errors for GET /imports/{id}
        message = (
            f"{len(blocked)} row(s) have errors. Fix the file, or commit with skip_invalid=true"
            if good else "Nothing to import: every product has errors"
        )  # fmt: skip
        if not blocked and validation.new_categories + validation.new_brands:
            message += " or create_missing=true"
        raise AppError(
            ErrorCode.IMPORT_HAS_ERRORS, message, status_code=422,
            details={"error_rows": len(blocked), "new_categories": validation.new_categories,
                     "new_brands": validation.new_brands},
        )  # fmt: skip

    categories = await _resolve_lookups(session, actor, imp, good, Category, create_missing)
    brands = await _resolve_lookups(session, actor, imp, good, Brand, create_missing)
    created = updated = 0
    for plan in good:
        changed = await _apply(session, actor, imp, plan, categories, brands)
        if plan.existing is None:
            created += 1
        elif changed:
            updated += 1

    good_skus = {p.sku for p in good}
    skipped = sorted({r.sku or f"row {r.row_no}" for r in validation.rows if r.sku not in good_skus})
    imp.status = "committed"
    imp.created_count = created
    imp.updated_count = updated
    imp.skipped_skus = skipped
    imp.committed_by = actor.id
    imp.committed_at = datetime.now(UTC)
    _audit(session, actor, "import.committed", imp, {
        "file_name": imp.file_name, "created": created, "updated": updated, "skipped_skus": skipped,
        "created_categories": [c.name_en for c in categories.values() if c.id in categories.created],
        "created_brands": [b.name_en for b in brands.values() if b.id in brands.created],
    })  # fmt: skip
    await commit(session)
    return imp


class _Resolved(dict):
    """casefolded name → row, plus the ids created by this commit."""

    created: set[UUID]


async def _resolve_lookups(
    session: AsyncSession,
    actor: CurrentUser,
    imp: ProductImport,
    plans: list[ProductPlan],
    model: type,
    create_missing: bool,
) -> _Resolved:
    column = "category" if model is Category else "brand"
    names = {getattr(p, column).casefold(): getattr(p, column) for p in plans if getattr(p, column)}
    resolved = _Resolved()
    resolved.created = set()
    if not names:
        return resolved
    for row in (
        await session.execute(select(model).where(func.lower(model.name_en).in_([n.lower() for n in names])))
    ).scalars():
        resolved[row.name_en.casefold()] = row
    for key, name in names.items():
        if key in resolved:
            continue
        if not create_missing:  # cannot happen: such plans are blocked
            raise AppError(ErrorCode.UNKNOWN_CATEGORY, f"Unknown {column} {name}", status_code=422)
        row = lookups.new_row(model, actor, name)
        session.add(row)
        await session.flush()
        lookups.record_created(session, actor, row, source="import", import_id=str(imp.id))
        resolved[key] = row
        resolved.created.add(row.id)
    return resolved


async def _apply(
    session: AsyncSession,
    actor: CurrentUser,
    imp: ProductImport,
    plan: ProductPlan,
    categories: _Resolved,
    brands: _Resolved,
) -> bool:
    m = plan.existing
    is_new = m is None
    if m is None:
        m = Medicine(sku=plan.sku, base_unit=plan.fields["base_unit"], is_rx_only=False, version=0,
                     storage="room", reorder_level=0, created_by=actor.id)  # fmt: skip
        for key in _TEXT_FIELDS:
            setattr(m, key, "")
        m.pack_units = []
        session.add(m)
    before = {} if is_new else m.safe_fields()

    for key, value in plan.fields.items():
        if key == "base_unit" and not is_new and value != m.base_unit:
            m.base_pack.name = value
        setattr(m, key, value)
    if plan.category:
        m.category = categories[plan.category.casefold()]
    if plan.brand:
        m.brand = brands[plan.brand.casefold()]
    if plan.schedule is not UNSET:
        m.controlled_schedule = plan.schedule
    medicines.apply_rx_rule(m, plan.rx)

    for pack in plan.packs:
        target = pack.existing
        if target is None:
            target = PackUnit(name=pack.name, qty_in_base=pack.qty_in_base, is_base=pack.is_base,
                              barcode=None, sell_price=pack.sell_price)  # fmt: skip
            m.pack_units.append(target)
        elif not target.is_base:
            target.qty_in_base = pack.qty_in_base
        if pack.barcode is not UNSET:
            target.barcode = pack.barcode
        if pack.sell_price is not None:
            target.sell_price = pack.sell_price
        target.is_active = True
    await session.flush()
    action = "medicine.created" if is_new else "medicine.updated"
    return medicines.record_change(
        session, actor, m, action, before, event=action, extra={"import_id": str(imp.id)}
    )
