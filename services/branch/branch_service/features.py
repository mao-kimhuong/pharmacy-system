"""Feature switches (Settings → Features). Optional menu items are hidden while
their feature is off; the front end reads GET /features.

New keys are added to the database at start-up with their default."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDef:
    key: str
    label: str
    default: bool
    hides: tuple[str, ...]  # menu item keys (auth service MENU) hidden while off


F = FeatureDef
FEATURES: tuple[FeatureDef, ...] = (
    F("commission", "Commission", False, ("commission_rules", "list_commission")),
    F("hampers", "Hampers (bundles)", False, ("hamper",)),
    F("sale_orders", "Sale orders", False, ("sale_order",)),
    F("sale_templates", "Sale templates", False, ("sale_template",)),
    F("customer_groups", "Customer groups", False, ("customer_group",)),
    F("supplier_groups", "Supplier groups", False, ("supplier_group",)),
    F("purchase_requests", "Purchase requests", False, ("purchase_request",)),
    F("multi_branch", "Several branches (transfers)", False, ("stock_transfer_request", "stock_transfer")),
    F("ai", "AI help (DeepSeek)", False, ()),
)
KEYS = {f.key: f for f in FEATURES}
