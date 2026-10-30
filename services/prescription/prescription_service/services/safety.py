"""Safety checks at dispense time, with messages in English and Khmer.

- Allergy: the medicine's active ingredients or drug classes (from the catalog
  copy) match one of the patient's active allergies (ignoring case).
- Duplicate therapy: another open prescription of the same patient still has
  quantity left of a medicine with a shared active ingredient.
(The Khmer wording should be checked by a Khmer-speaking pharmacist.)
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OPEN, Patient, Prescription, Product, RxItem


def _fold(values: list[str] | None) -> dict[str, str]:
    return {v.casefold(): v for v in values or [] if v}


def allergy_warnings(patient: Patient, product: Product | None) -> list[dict[str, Any]]:
    if product is None:
        return []
    ingredients, classes = _fold(product.active_ingredients), _fold(product.drug_classes)
    out = []
    for a in patient.active_allergies:
        pool = ingredients if a.kind == "ingredient" else classes
        if a.value.casefold() in pool:
            what = pool[a.value.casefold()]
            out.append({
                "kind": "allergy", "value": what,
                "en": f"Allergy: the patient is allergic to {what} ({product.display_name})",
                "km": f"ប្រយ័ត្នអាឡែហ្ស៊ី៖ អ្នកជំងឺមានអាឡែហ្ស៊ីនឹង {what} ({product.display_name})",
            })  # fmt: skip
    return out


async def duplicate_warnings(
    session: AsyncSession, patient_id: UUID, rx_id: UUID, product: Product | None
) -> list[dict[str, Any]]:
    if product is None or not product.active_ingredients:
        return []
    mine = _fold(product.active_ingredients)
    rows = (await session.execute(
        select(RxItem, Prescription.number, Product)
        .join(Prescription, Prescription.id == RxItem.prescription_id)
        .join(Product, Product.id == RxItem.medicine_id)
        .where(Prescription.patient_id == patient_id, Prescription.id != rx_id, Prescription.status.in_(OPEN))
    )).all()  # fmt: skip
    out, seen = [], set()
    for item, number, other in rows:
        if item.remaining_base <= 0:
            continue
        for key in _fold(other.active_ingredients).keys() & mine.keys():
            if (number, key) in seen:
                continue
            seen.add((number, key))
            out.append({
                "kind": "duplicate_therapy", "value": mine[key], "prescription": number,
                "en": f"Duplicate therapy: {mine[key]} is also on prescription {number}",
                "km": f"ការព្យាបាលស្ទួន៖ {mine[key]} មាននៅក្នុងវេជ្ជបញ្ជា {number} ផងដែរ",
            })  # fmt: skip
    return out
