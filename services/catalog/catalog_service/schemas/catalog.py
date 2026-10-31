from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Price = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, examples=["2.50"])]
Barcode = Annotated[str, Field(pattern=r"^[0-9A-Za-z._\-/+]{3,48}$", examples=["8850123456789"])]
Schedule = Literal["I", "II", "III", "IV"]
Storage = Literal["room", "cold"]
Term = Annotated[str, Field(min_length=1, max_length=80)]


# ---------------------------------------------------------------- categories, brands


class LookupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_km: str
    name_en: str
    is_active: bool
    created_at: datetime


class LookupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str = Field(min_length=1, max_length=120)
    name_km: str = Field(default="", max_length=120)


class LookupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_km: str | None = Field(default=None, max_length=120)


class LookupRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_km: str
    name_en: str


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


# ---------------------------------------------------------------- pack units


class PackUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    medicine_id: UUID
    name: str
    qty_in_base: int
    barcode: str | None
    sell_price: Decimal
    is_base: bool
    is_active: bool


class PackUnitCreate(BaseModel):
    """A bigger unit (strip, box). The base unit is created with the medicine."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40, examples=["box"])
    qty_in_base: int = Field(ge=2, le=1_000_000, examples=[100])
    barcode: Barcode | None = None
    sell_price: Price


class PackUnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=40)
    qty_in_base: int | None = Field(default=None, ge=2, le=1_000_000)
    barcode: Barcode | None = None  # send null to remove the barcode
    sell_price: Price | None = None


# ---------------------------------------------------------------- medicines


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_id: UUID
    qty_base: int


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    brand_name: str
    generic_name: str
    strength: str
    dosage_form: str
    name_km: str
    category: LookupRef | None
    brand: LookupRef | None
    manufacturer: str
    base_unit: str
    is_rx_only: bool
    controlled_schedule: Schedule | None
    storage: Storage
    reorder_level: int
    active_ingredients: list[str]
    drug_classes: list[str]
    is_active: bool
    version: int
    kind: str = "medicine"
    components: list["ComponentOut"] = []
    pack_units: list[PackUnitOut]
    created_at: datetime
    updated_at: datetime


class MedicinePage(BaseModel):
    items: list[MedicineOut]
    total: int
    page: int
    size: int


class SearchHit(MedicineOut):
    # Set when the search text was a pack unit's barcode: the unit that was scanned.
    matched_pack_unit_id: UUID | None = None


class SearchPage(BaseModel):
    items: list[SearchHit]
    total: int
    page: int
    size: int


class MedicineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=40, examples=["PARA500"])
    brand_name: str = Field(min_length=1, max_length=160, examples=["Panadol"])
    generic_name: str = Field(min_length=1, max_length=160, examples=["Paracetamol"])
    strength: str = Field(default="", max_length=60, examples=["500mg"])
    dosage_form: str = Field(default="", max_length=60, examples=["tablet"])
    name_km: str = Field(default="", max_length=160)
    category_id: UUID | None = None
    brand_id: UUID | None = None
    manufacturer: str = Field(default="", max_length=160)
    base_unit: str = Field(min_length=1, max_length=40, examples=["tablet"])
    base_price: Price
    base_barcode: Barcode | None = None
    # Left out: false, or true when controlled_schedule is set.
    is_rx_only: bool | None = None
    controlled_schedule: Schedule | None = None
    storage: Storage = "room"
    reorder_level: int = Field(default=0, ge=0, le=10_000_000)
    active_ingredients: list[Term] | None = Field(
        default=None, max_length=10, description="Left out: from generic_name (split on +)"
    )
    drug_classes: list[Term] = Field(default_factory=list, max_length=10, examples=[["penicillins"]])
    pack_units: list[PackUnitCreate] = Field(default_factory=list, max_length=10)


class MedicineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, min_length=1, max_length=40)
    brand_name: str | None = Field(default=None, min_length=1, max_length=160)
    generic_name: str | None = Field(default=None, min_length=1, max_length=160)
    strength: str | None = Field(default=None, max_length=60)
    dosage_form: str | None = Field(default=None, max_length=60)
    name_km: str | None = Field(default=None, max_length=160)
    category_id: UUID | None = None
    brand_id: UUID | None = None
    manufacturer: str | None = Field(default=None, max_length=160)
    base_unit: str | None = Field(default=None, min_length=1, max_length=40)
    is_rx_only: bool | None = None
    controlled_schedule: Schedule | None = None
    storage: Storage | None = None
    reorder_level: int | None = Field(default=None, ge=0, le=10_000_000)
    active_ingredients: list[Term] | None = Field(default=None, max_length=10)
    drug_classes: list[Term] | None = Field(default=None, max_length=10)


# ---------------------------------------------------------------- hampers (S7)


class ComponentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    qty_base: int = Field(ge=1, le=100_000, description="In the component's base unit")


class HamperCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=40, examples=["KIT-FLU"])
    name: str = Field(min_length=1, max_length=160, examples=["Flu care kit"])
    name_km: str = Field(default="", max_length=160)
    category_id: UUID | None = None
    brand_id: UUID | None = None
    price: Price
    barcode: Barcode | None = None
    components: list[ComponentIn] = Field(min_length=1, max_length=30)


class HamperComponentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: list[ComponentIn] = Field(min_length=1, max_length=30)


# ---------------------------------------------------------------- promotions (S7)

PromoType = Literal["percent_off", "amount_off", "buy_x_get_y", "bundle_price", "qty_tiers", "group_price"]


class Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_qty: int = Field(ge=1, description="Base units of one medicine")
    percent: Decimal = Field(gt=0, le=100)


class BundleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_id: UUID
    qty_base: int = Field(ge=1)


class PromotionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    name_km: str = Field(default="", max_length=160)
    value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4,
                                  description="% (percent_off), USD per unit sold (amount_off), bundle or group price")  # fmt: skip
    buy_qty: int | None = Field(default=None, ge=1, description="buy_x_get_y, base units")
    get_qty: int | None = Field(default=None, ge=1)
    tiers: list[Tier] = Field(default_factory=list, max_length=10)
    bundle_items: list[BundleItem] = Field(default_factory=list, max_length=10)
    medicine_ids: list[UUID] = Field(default_factory=list, max_length=500)
    category_ids: list[UUID] = Field(default_factory=list, max_length=100)
    brand_ids: list[UUID] = Field(default_factory=list, max_length=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    days_of_week: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=list, description="0 = Monday"
    )
    branch_ids: list[UUID] = Field(default_factory=list, description="Empty = every branch")
    customer_group_ids: list[UUID] = Field(default_factory=list, description="Empty = every customer")
    max_uses_total: int | None = Field(default=None, ge=1)
    max_uses_per_customer: int | None = Field(default=None, ge=1)
    stackable: bool = False
    include_rx: bool = Field(default=False, description="Also Rx-only and controlled medicines")


class PromotionCreate(PromotionFields):
    code: str = Field(min_length=1, max_length=30, examples=["B2G1-PARA"])
    type: PromoType


class PromotionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    name_km: str | None = Field(default=None, max_length=160)
    value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    buy_qty: int | None = Field(default=None, ge=1)
    get_qty: int | None = Field(default=None, ge=1)
    tiers: list[Tier] | None = None
    bundle_items: list[BundleItem] | None = None
    medicine_ids: list[UUID] | None = None
    category_ids: list[UUID] | None = None
    brand_ids: list[UUID] | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    days_of_week: list[Annotated[int, Field(ge=0, le=6)]] | None = None
    branch_ids: list[UUID] | None = None
    customer_group_ids: list[UUID] | None = None
    max_uses_total: int | None = Field(default=None, ge=1)
    max_uses_per_customer: int | None = Field(default=None, ge=1)
    stackable: bool | None = None
    include_rx: bool | None = None


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    name_km: str
    type: str
    value: Decimal | None
    buy_qty: int | None
    get_qty: int | None
    tiers: list[dict]
    bundle_items: list[dict]
    medicine_ids: list[str]
    category_ids: list[str]
    brand_ids: list[str]
    starts_at: datetime | None
    ends_at: datetime | None
    days_of_week: list[int]
    branch_ids: list[str]
    customer_group_ids: list[str]
    max_uses_total: int | None
    max_uses_per_customer: int | None
    stackable: bool
    include_rx: bool
    is_active: bool
    version: int
