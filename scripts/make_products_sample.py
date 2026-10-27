#!/usr/bin/env python3
"""Writes the Import Product samples (needs openpyxl, e.g. the repo .venv):

    docs/samples/products-sample.xlsx         20 products, imports cleanly
    docs/samples/products-sample-broken.xlsx  same file with one bad row

    .venv/bin/python scripts/make_products_sample.py

Medicines commonly sold in Cambodian pharmacies, with tablet / strip / box
pack units, several Rx-only and one controlled (Diazepam, schedule IV).
Prices are typical retail USD prices, for testing only. Barcodes are made-up
EAN-13 codes with the Cambodian GS1 prefix 884 and a valid check digit.
The categories and brands do not exist in a new system: commit the import with
"create missing categories and brands" (create_missing=true).
Khmer names are transliterations; have a Khmer-speaking pharmacist review them.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parents[1] / "docs" / "samples"
COLUMNS = [
    "sku", "brand_name", "generic_name", "strength", "dosage_form", "name_km", "category", "brand",
    "manufacturer", "base_unit", "rx_only", "controlled_schedule", "storage", "reorder_level",
    "pack_unit", "qty_in_base", "barcode", "sell_price_usd",
]  # fmt: skip

# sku, brand, generic, strength, form, Khmer, category, brand, maker, base, rx, schedule, storage,
# reorder level, [(pack unit, qty in base, price)]
PRODUCTS = [
    ("PARA500", "Panadol", "Paracetamol", "500mg", "tablet", "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល", "Pain & fever",
     "Panadol", "GSK", "tablet", "no", "", "room", 240,
     [("tablet", 1, "0.05"), ("strip", 12, "0.55"), ("box", 120, "5.00")]),
    ("EFFER500", "Efferalgan", "Paracetamol", "500mg", "effervescent tablet", "អេហ្វេរ៉ាល់ហ្គង់",
     "Pain & fever", "Efferalgan", "UPSA", "tablet", "no", "", "room", 64,
     [("tablet", 1, "0.15"), ("strip", 4, "0.55"), ("box", 16, "2.10")]),
    ("IBU400", "Brufen", "Ibuprofen", "400mg", "tablet", "ប្រ៊ុយហ្វេន អ៊ីប៊ុយប្រូហ្វេន", "Pain & fever",
     "Brufen", "Abbott", "tablet", "no", "", "room", 200,
     [("tablet", 1, "0.08"), ("strip", 10, "0.75"), ("box", 100, "7.00")]),
    ("AMOX500", "Ospamox", "Amoxicillin", "500mg", "capsule", "អាម៉ុកស៊ីស៊ីលីន", "Antibiotics",
     "Ospamox", "Sandoz", "capsule", "yes", "", "room", 300,
     [("capsule", 1, "0.12"), ("strip", 10, "1.10"), ("box", 100, "10.50")]),
    ("AUGM625", "Augmentin", "Amoxicillin + Clavulanic acid", "500mg/125mg", "tablet", "អូហ្គម៉ង់តាំង",
     "Antibiotics", "Augmentin", "GSK", "tablet", "yes", "", "room", 56,
     [("tablet", 1, "0.70"), ("strip", 7, "4.80"), ("box", 14, "9.50")]),
    ("AZI250", "Zithromax", "Azithromycin", "250mg", "capsule", "ស៊ីត្រូម៉ាក់ អាហ្ស៊ីត្រូម៉ៃស៊ីន",
     "Antibiotics", "Zithromax", "Pfizer", "capsule", "yes", "", "room", 30,
     [("capsule", 1, "1.00"), ("box", 6, "5.80")]),
    ("CIPRO500", "Ciprobay", "Ciprofloxacin", "500mg", "tablet", "ស៊ីប្រូហ្វ្លុកសាស៊ីន", "Antibiotics",
     "Ciprobay", "Bayer", "tablet", "yes", "", "room", 40,
     [("tablet", 1, "0.40"), ("strip", 10, "3.80"), ("box", 20, "7.50")]),
    ("ORS", "ORS", "Oral rehydration salts", "20.5g", "powder sachet", "អូរ៉េស៊ីត ទឹកអំបិលស្ករ",
     "Rehydration", "ORS", "Pharmatec", "sachet", "no", "", "room", 100,
     [("sachet", 1, "0.15"), ("box", 20, "2.80")]),
    ("OMEP20", "Losec", "Omeprazole", "20mg", "capsule", "អូមេប្រាហ្សូល", "Digestive",
     "Losec", "AstraZeneca", "capsule", "no", "", "room", 140,
     [("capsule", 1, "0.10"), ("strip", 14, "1.30"), ("box", 28, "2.50")]),
    ("METF500", "Glucophage", "Metformin", "500mg", "tablet", "មេតហ្វ័រមីន", "Diabetes",
     "Glucophage", "Merck", "tablet", "yes", "", "room", 300,
     [("tablet", 1, "0.06"), ("strip", 10, "0.55"), ("box", 100, "5.20")]),
    ("AMLO5", "Norvasc", "Amlodipine", "5mg", "tablet", "អាំឡូឌីពីន", "Heart & blood pressure",
     "Norvasc", "Pfizer", "tablet", "yes", "", "room", 90,
     [("tablet", 1, "0.25"), ("strip", 10, "2.40"), ("box", 30, "7.00")]),
    ("CETI10", "Zyrtec", "Cetirizine", "10mg", "tablet", "សេទីរីហ្ស៊ីន", "Allergy",
     "Zyrtec", "UCB", "tablet", "no", "", "room", 100,
     [("tablet", 1, "0.20"), ("strip", 10, "1.80"), ("box", 20, "3.50")]),
    ("LORA10", "Clarityne", "Loratadine", "10mg", "tablet", "ឡូរ៉ាតាឌីន", "Allergy",
     "Clarityne", "Bayer", "tablet", "no", "", "room", 60,
     [("tablet", 1, "0.25"), ("strip", 10, "2.30"), ("box", 30, "6.50")]),
    ("VITC1000", "Redoxon", "Ascorbic acid (vitamin C)", "1000mg", "effervescent tablet",
     "វីតាមីន សេ", "Vitamins & supplements", "Redoxon", "Bayer", "tablet", "no", "", "room", 50,
     [("tablet", 1, "0.30"), ("tube", 10, "2.80")]),
    ("SALB100", "Ventolin", "Salbutamol", "100mcg/dose", "inhaler", "វ៉ិនតូលីន សាល់ប៊ុយតាម៉ុល",
     "Respiratory", "Ventolin", "GSK", "inhaler", "yes", "", "room", 10,
     [("inhaler", 1, "4.50")]),
    ("AMOXSYR250", "Ospamox", "Amoxicillin", "250mg/5ml", "powder for suspension",
     "អាម៉ុកស៊ីស៊ីលីន ទឹកសម្រាប់កុមារ", "Antibiotics", "Ospamox", "Sandoz", "bottle", "yes", "", "room", 20,
     [("bottle", 1, "1.80"), ("box", 10, "17.00")]),
    ("DOMP10", "Motilium", "Domperidone", "10mg", "tablet", "ម៉ូទីលីយ៉ូម ដុមភែរីដូន", "Digestive",
     "Motilium", "Janssen", "tablet", "no", "", "room", 90,
     [("tablet", 1, "0.15"), ("strip", 10, "1.40"), ("box", 30, "4.00")]),
    ("LOPE2", "Imodium", "Loperamide", "2mg", "capsule", "អ៊ីម៉ូដ្យូម ឡូពែរ៉ាមីត", "Digestive",
     "Imodium", "Janssen", "capsule", "no", "", "room", 36,
     [("capsule", 1, "0.20"), ("strip", 6, "1.10"), ("box", 12, "2.10")]),
    ("CLOT1", "Canesten", "Clotrimazole", "1% 20g", "cream", "ក្លូទ្រីម៉ាហ្សូល ក្រែម", "Skin",
     "Canesten", "Bayer", "tube", "no", "", "room", 10,
     [("tube", 1, "3.50")]),
    ("DIAZ5", "Valium", "Diazepam", "5mg", "tablet", "ឌីអាហ្សេប៉ាម", "Psycholeptics",
     "Valium", "Roche", "tablet", "yes", "IV", "room", 50,
     [("tablet", 1, "0.10"), ("strip", 10, "0.90"), ("box", 100, "8.50")]),
]  # fmt: skip


def ean13(company: int, item: int) -> str:
    body = f"884{company:05d}{item:04d}"
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


def rows() -> list[list]:
    out = []
    item = 0
    for n, (sku, brand_name, generic, strength, form, km, category, brand, maker, base, rx, schedule,
            storage, reorder, packs) in enumerate(PRODUCTS):  # fmt: skip
        product = [sku, brand_name, generic, strength, form, km, category, brand, maker, base, rx, schedule,
                   storage, reorder]  # fmt: skip
        for i, (pack, qty, price) in enumerate(packs):
            item += 1
            # First half: product columns on every row; second half: only on the first row.
            cells = product if i == 0 or n < len(PRODUCTS) // 2 else [sku] + [""] * (len(product) - 1)
            out.append([*cells, pack, qty, ean13(10001, item), price])
    return out


def write(path: Path, data: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in data:
        ws.append(row)
    for i, name in enumerate(COLUMNS):
        width = max(len(name), *(len(str(r[i])) for r in data))
        ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = min(width + 2, 40)
    ws.freeze_panes = "A2"
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    good = rows()
    write(OUT / "products-sample.xlsx", good)
    # One typical mistake: Amoxicillin's strip row gets Paracetamol's strip barcode.
    broken = [list(r) for r in good]
    amox_strip = next(r for r in broken if r[0] == "AMOX500" and r[14] == "strip")
    para_strip = next(r for r in broken if r[0] == "PARA500" and r[14] == "strip")
    amox_strip[16] = para_strip[16]
    write(OUT / "products-sample-broken.xlsx", broken)
    print(f"wrote {len(PRODUCTS)} products ({len(good)} rows) to {OUT}")


if __name__ == "__main__":
    main()
