from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LabelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_unit_id: UUID
    copies: int = Field(default=1, ge=1, le=500)


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["label"] = Field(description="Only labels for now; receipts, invoices, POs come later")
    layout: Literal["shelf_50x30", "barcode_40x25", "a4_sheet"] = Field(
        description="Shelf label 50×30 mm, barcode label 40×25 mm (one per page, for label printers), "
        "or an A4 sheet of 3 × 8 labels"
    )
    items: list[LabelItem] = Field(min_length=1, max_length=200)
