"""Excel files for Import Product and the product export.

Layout (sheet "Products", one row per pack unit, grouped by SKU):

    sku | brand_name | ... | reorder_level | pack_unit | qty_in_base | barcode | sell_price_usd

Product columns may be repeated on every row of a SKU or left blank after the
first one. The row whose pack_unit equals base_unit (qty_in_base 1) is the base unit.
File safety (content check, macros, zip bombs, values only) is in pharmacy_shared.xlsx.
"""

from dataclasses import dataclass

from pharmacy_shared.xlsx import MAX_FILE_BYTES, read_sheet, write_workbook

__all__ = ["COLUMNS", "KEYS", "MAX_FILE_BYTES", "PRODUCT_KEYS", "read_rows", "template", "write_workbook"]


@dataclass(frozen=True)
class Column:
    key: str
    product: bool  # product column (same on every row of a SKU) or pack unit column
    required: bool  # header must be present
    help: str


COLUMNS: tuple[Column, ...] = (
    Column("sku", True, True, "Your product code, e.g. PARA500. Capital letters, digits, . _ - /"),
    Column("brand_name", True, True, "Name on the pack, e.g. Panadol"),
    Column("generic_name", True, True, "Active ingredient, e.g. Paracetamol"),
    Column("strength", True, False, "e.g. 500mg, 250mg/5ml"),
    Column("dosage_form", True, False, "e.g. tablet, capsule, syrup, sachet"),
    Column("name_km", True, False, "Name in Khmer"),
    Column("category", True, False, "Category English name; must exist unless you allow new ones on commit"),
    Column("brand", True, False, "Brand English name; must exist unless you allow new ones on commit"),
    Column("manufacturer", True, False, "Maker, e.g. GSK"),
    Column("base_unit", True, True, "Smallest unit sold, e.g. tablet. Stock is counted in it"),
    Column("rx_only", True, False, "yes / no. Blank = no (yes for controlled medicines)"),
    Column("controlled_schedule", True, False, "Blank, I, II, III or IV. Controlled = always Rx-only"),
    Column("storage", True, False, "room or cold. Blank = room"),
    Column("reorder_level", True, False, "Re-order when stock (in base units) falls to this. Blank = 0"),
    Column("active_ingredients", True, False, "Separated by ; Blank = from generic_name (split on +)"),
    Column("drug_classes", True, False, "Separated by ; e.g. penicillins; beta-lactams (for allergy checks)"),
    Column("pack_unit", False, True, "tablet / strip / box ... One row per pack unit"),
    Column("qty_in_base", False, True, "How many base units it holds. 1 only on the base_unit row"),
    Column("barcode", False, False, "Unique across all products; blank = none"),
    Column("sell_price_usd", False, True, "Selling price in USD, e.g. 2.50"),
)
KEYS = tuple(c.key for c in COLUMNS)
PRODUCT_KEYS = tuple(c.key for c in COLUMNS if c.product)
REQUIRED_HEADERS = tuple(c.key for c in COLUMNS if c.required)


def read_rows(data: bytes) -> list[tuple[int, dict[str, str]]]:
    """(Excel row number, {column: text}) for every non-empty product row."""
    return read_sheet(
        data,
        keys=KEYS,
        required=REQUIRED_HEADERS,
        sheet="Products",
        aliases={"sell_price": "sell_price_usd", "price": "sell_price_usd", "rx": "rx_only"},
    )


TEMPLATE_EXAMPLE = [
    ["PARA500", "Panadol", "Paracetamol", "500mg", "tablet", "ប៉ារ៉ាសេតាម៉ុល", "Pain & fever", "Panadol",
     "GSK", "tablet", "no", "", "room", 200, "Paracetamol", "analgesics", "tablet", 1, "", "0.10"],
    ["PARA500", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "strip", 10, "", "0.90"],
    ["PARA500", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "box", 120, "", "10.00"],
]  # fmt: skip


def template() -> bytes:
    help_rows = [[c.key, "yes" if c.required else "", c.help] for c in COLUMNS]
    help_rows += [
        ["", "", ""],
        ["Rows", "", "One row per pack unit. Repeat the SKU on each row of the same product."],
        [
            "",
            "",
            "Product columns may be left blank after the SKU's first row; a different value is an error.",
        ],
        ["Updates", "", "A SKU that already exists is updated; blank cells keep the saved value."],
        ["", "", "Pack units are matched by name. Pack units not in the file are left as they are."],
        ["Values", "", "Only values are read. Formulas give their last saved value; macros are refused."],
    ]
    return write_workbook([
        ("Products", list(KEYS), TEMPLATE_EXAMPLE),
        ("Instructions", ["column", "required", "what to enter"], help_rows),
    ])  # fmt: skip
