"""Permission catalog, default role grants and the menu.

This file is the source of truth for permission keys. At start-up the auth
service copies the catalog into the `permissions` table (new keys are added,
labels updated), and gives the built-in roles their defaults the first time.
After that, the owner edits roles on the Role screen.

Defaults follow docs/spec.md → Errors, security & permissions → Permissions matrix.
Dispensing Rx-only and controlled drugs also needs the user's `is_pharmacist`
flag; the sales service checks both.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    key: str
    group: str
    label: str


P = PermissionDef
CATALOG: tuple[PermissionDef, ...] = (
    P("dashboard.view", "Dashboard", "See the dashboard"),
    # Sales
    P("pos.sell", "Sales", "Sell (POS)"),
    P("pos.dispense_rx", "Sales", "Dispense prescription-only medicines"),
    P("sales.view", "Sales", "See invoices (List Sale)"),
    P("sales.cancel", "Sales", "Cancel invoices"),
    P("sales.cancel_any", "Sales", "Cancel invoices from earlier days"),
    P("sales.exchange_rate", "Sales", "Set the KHR exchange rate"),
    P("sales.return", "Sales", "Sale returns"),
    P("sales.suspend", "Sales", "Suspend and resume sales"),
    P("sales.orders", "Sales", "Quotes and sale orders"),
    P("sales.templates", "Sales", "Sale templates"),
    P("sales.discount", "Sales", "Approve manual discounts above the cap (with PIN)"),
    P("sales.below_cost", "Sales", "Sell below cost"),
    P("catalog.promotions", "Sales", "Item promotions"),
    # Prescriptions and controlled drugs
    P("patients.view", "Prescriptions", "See patients"),
    P("patients.manage", "Prescriptions", "Add and edit patients"),
    P("prescriptions.view", "Prescriptions", "See prescriptions and doctors"),
    P("prescriptions.manage", "Prescriptions", "Add and edit prescriptions and doctors"),
    P(
        "prescriptions.override_warning",
        "Prescriptions",
        "Override allergy warnings (pharmacist, with reason)",
    ),
    P("controlled.view", "Controlled drugs", "See the controlled-drug register"),
    P("controlled.dispense", "Controlled drugs", "Dispense controlled medicines (pharmacist, with PIN)"),
    P("controlled.witness", "Controlled drugs", "Witness controlled-drug entries"),
    P("controlled.adjust", "Controlled drugs", "Adjust or destroy controlled stock"),
    P("controlled.resolve", "Controlled drugs", "Resolve register discrepancies"),
    # Inventory
    P("products.view", "Inventory", "See products"),
    P("products.manage", "Inventory", "Edit medicines and prices"),
    P("products.import", "Inventory", "Import products from Excel"),
    P("labels.print", "Inventory", "Print labels"),
    P("catalog.hampers", "Inventory", "Hampers (kits)"),
    P("inventory.view", "Inventory", "See stock"),
    P("inventory.stock_in", "Inventory", "Quick stock-in"),
    P("inventory.adjust", "Inventory", "Adjustments and quarantine release"),
    P("inventory.shrinkage", "Inventory", "Record shrinkage (damaged, lost, expired...)"),
    P("inventory.shrinkage_approve", "Inventory", "Approve shrinkage above the branch limit"),
    P("inventory.locations", "Inventory", "Set shelf locations"),
    P("inventory.initialize", "Inventory", "Opening stock (Initialize)"),
    P("stockcount.count", "Inventory", "Count stock (Stock Take)"),
    P("stockcount.approve", "Inventory", "Approve stock counts"),
    # Transfers
    P("transfers.request", "Transfer", "Request stock from another branch"),
    P("transfers.approve", "Transfer", "Approve requests to send stock (source branch)"),
    P("transfers.dispatch", "Transfer", "Pick and send transfers (source branch)"),
    P("transfers.receive", "Transfer", "Receive transfers (destination branch)"),
    P("transfers.resolve", "Transfer", "Resolve transfer differences"),
    # Purchasing
    P("purchasing.request", "Purchase", "Purchase requests"),
    P("purchasing.request_approve", "Purchase", "Approve or reject purchase requests"),
    P("inventory.reorder_settings", "Purchase", "Re-order levels and the re-order list"),
    P("purchasing.order", "Purchase", "Create purchase orders"),
    P("purchasing.receive", "Purchase", "Receive goods"),
    P("purchasing.over_receive", "Purchase", "Receive more than ordered"),
    P("purchasing.pay", "Purchase", "Pay suppliers"),
    # Contacts
    P("contacts.customers", "Contacts", "Customers"),
    P("customers.credit_limit", "Contacts", "Set customer credit limits"),
    P("contacts.customer_groups", "Contacts", "Customer groups"),
    P("contacts.suppliers", "Contacts", "Suppliers and supplier groups"),
    # Commission
    P("commission.view_own", "Commission", "See your own commission"),
    P("commission.manage", "Commission", "Commission rules and payouts"),
    # Reports
    P("reports.sales", "Reports", "Sales reports"),
    P("reports.stock", "Reports", "Stock and expiry reports"),
    P("reports.purchases", "Reports", "Purchase and transfer reports"),
    P("finance.cost_profit", "Reports", "See cost and profit"),
    # Settings
    P("settings.users", "Settings", "Manage staff"),
    P("settings.roles", "Settings", "Manage roles and permissions"),
    P("settings.audit_log", "Settings", "See the User Log"),
    P("settings.branches", "Settings", "Create and edit branches"),
    P("settings.branch_settings", "Settings", "Edit settings of own branches"),
    P("settings.features", "Settings", "Turn features on or off"),
)
KEYS = frozenset(p.key for p in CATALOG)
# Old key → new key: grants move to the new key at start-up (catalog_sync).
RENAMED: dict[str, str] = {
    "pos.dispense_controlled": "controlled.dispense", "transfers.send": "transfers.dispatch",
    "sales.order": "sales.orders", "sales.template": "sales.templates", "promotions.manage": "catalog.promotions",
    "hampers.manage": "catalog.hampers", "commission.view": "commission.view_own",
}  # fmt: skip
# Existing keys added to a built-in role's defaults in a later sprint: given once
# to stacks that already exist (tag, role, key); a later removal by the owner stays.
DEFAULT_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("S5:pharmacist:controlled.adjust", "pharmacist", "controlled.adjust"),
    ("S6:pharmacist:purchasing.request", "pharmacist", "purchasing.request"),
    *(
        (f"S7:{role}:{key}", role, key)
        for role in ("pharmacist", "cashier")
        for key in ("sales.orders", "sales.templates", "commission.view_own")
    ),
)

OWNER = "owner"
SYSTEM_ROLES: dict[str, str] = {
    "owner": "Owner",
    "branch_manager": "Branch manager",
    "pharmacist": "Pharmacist",
    "cashier": "Cashier",
}

_PHARMACIST = {
    "dashboard.view", "pos.sell", "pos.dispense_rx", "controlled.dispense", "sales.view",
    "sales.cancel", "sales.return", "sales.suspend", "prescriptions.manage", "controlled.view",
    "patients.view", "patients.manage", "prescriptions.view", "prescriptions.override_warning",
    "controlled.witness", "controlled.adjust", "products.view", "labels.print", "inventory.view", "inventory.stock_in",
    "stockcount.count", "stockcount.approve", "transfers.request", "transfers.dispatch", "purchasing.request",
    "transfers.receive", "purchasing.receive", "contacts.customers", "reports.stock", "inventory.shrinkage",
    "sales.orders", "sales.templates", "commission.view_own",
}  # fmt: skip
_CASHIER = {
    "dashboard.view", "pos.sell", "sales.view", "sales.suspend", "products.view", "inventory.view",
    "inventory.stock_in", "stockcount.count", "transfers.receive", "purchasing.receive",
    "contacts.customers", "sales.orders", "sales.templates", "commission.view_own",
}  # fmt: skip
# Branch manager: everything except what only the owner does. Cost & profit only if granted.
_MANAGER = KEYS - {
    "settings.roles", "settings.branches", "settings.features", "finance.cost_profit",
    "inventory.initialize", "sales.below_cost",
}  # fmt: skip

DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "branch_manager": frozenset(_MANAGER),
    "pharmacist": frozenset(_PHARMACIST),
    "cashier": frozenset(_CASHIER),
}

# Permissions only the owner may hand out: a role with any of them can only be
# given to someone by the owner (a manager cannot create another manager).
ADMIN_PERMISSIONS = frozenset({"settings.users", "settings.roles", "settings.branches", "settings.features"})


@dataclass(frozen=True)
class MenuItem:
    group: str
    key: str
    label: str
    any_of: tuple[str, ...]


M = MenuItem
MENU: tuple[MenuItem, ...] = (
    M("dashboard", "dashboard", "Dashboard", ("dashboard.view",)),
    M("sales", "pos", "POS", ("pos.sell",)),
    M("sales", "sale_order", "Sale Order", ("sales.orders",)),
    M("sales", "sale_suspend", "Sale Suspend", ("sales.suspend",)),
    M("sales", "sale_template", "Sale Template", ("sales.templates",)),
    M("sales", "list_sale", "List Sale", ("sales.view",)),
    M("sales", "sale_return", "Sale Return", ("sales.return",)),
    M("sales", "items_promotion", "Items Promotion", ("catalog.promotions",)),
    M("prescriptions", "patients", "Patients", ("patients.view",)),
    M("prescriptions", "doctors", "Doctors", ("prescriptions.view",)),
    M("prescriptions", "prescriptions", "Prescriptions", ("prescriptions.view",)),
    M("controlled", "register", "Register", ("controlled.view",)),
    M("controlled", "discrepancies", "Discrepancies", ("controlled.view",)),
    M("inventory", "product", "Product", ("products.view",)),
    M("inventory", "hamper", "Hamper", ("catalog.hampers",)),
    M("inventory", "stock", "Stock", ("inventory.view",)),
    M("inventory", "stock_take", "Stock Take", ("stockcount.count",)),
    M("inventory", "shrinkage", "Shrinkage", ("inventory.shrinkage", "inventory.shrinkage_approve")),
    M("inventory", "import_product", "Import Product", ("products.import",)),
    M("inventory", "print_label", "Print Label", ("labels.print",)),
    M("transfer", "stock_transfer_request", "Stock Transfer Request", ("transfers.request",)),
    M("transfer", "stock_transfer", "Stock Transfer", ("transfers.dispatch", "transfers.receive")),
    M(
        "purchase",
        "purchase_request",
        "Purchase Request",
        ("purchasing.request", "purchasing.request_approve"),
    ),
    M("purchase", "reorder", "Re-order", ("inventory.reorder_settings",)),
    M("purchase", "purchase_order", "Purchase Order", ("purchasing.order",)),
    M("purchase", "receiving_goods", "Receiving Goods", ("purchasing.receive",)),
    M("purchase", "purchase_payment", "Purchase Payment", ("purchasing.pay",)),
    M("contacts", "customer", "Customer", ("contacts.customers",)),
    M("contacts", "customer_group", "Customer Group", ("contacts.customer_groups",)),
    M("contacts", "supplier", "Supplier", ("contacts.suppliers",)),
    M("contacts", "supplier_group", "Supplier Group", ("contacts.suppliers",)),
    M("commission", "commission_rules", "Commission Rules", ("commission.manage",)),
    M("commission", "list_commission", "List Commission", ("commission.view_own", "commission.manage")),
    M("reports", "sales_reports", "Sales reports", ("reports.sales",)),
    M("reports", "sale_margin_by_item", "Sale Margin By Item", ("finance.cost_profit",)),
    M("reports", "stock_reports", "Stock reports", ("reports.stock",)),
    M("reports", "purchase_reports", "Purchase & transfer reports", ("reports.purchases",)),
    M("settings", "user", "User", ("settings.users",)),
    M("settings", "role", "Role", ("settings.roles",)),
    M("settings", "user_log", "User Log", ("settings.audit_log",)),
    M("settings", "branches", "Branches", ("settings.branches", "settings.branch_settings")),
    M("settings", "features", "Features", ("settings.features",)),
    M("settings", "initialize", "Initialize", ("inventory.initialize",)),
)


def menu_for(permissions: frozenset[str] | set[str]) -> list[dict[str, str]]:
    allowed = "*" in permissions
    return [
        {"group": m.group, "key": m.key, "label": m.label}
        for m in MENU
        if allowed or any(p in permissions for p in m.any_of)
    ]
