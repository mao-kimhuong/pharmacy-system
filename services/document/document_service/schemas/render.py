from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LabelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_unit_id: UUID
    copies: int = Field(default=1, ge=1, le=500)


class LabelRender(BaseModel):
    """Shelf / barcode labels. Permission labels.print."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["label"]
    layout: Literal["shelf_50x30", "barcode_40x25", "a4_sheet"] = Field(
        description="Shelf label 50×30 mm, barcode label 40×25 mm (one per page, for label printers), "
        "or an A4 sheet of 3 × 8 labels"
    )
    items: list[LabelItem] = Field(min_length=1, max_length=200)


class PurchaseOrderRender(BaseModel):
    """A4 purchase order. Permission purchasing.order, own branches."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["purchase_order"]
    purchase_order_id: UUID


RenderRequest = Annotated[LabelRender | PurchaseOrderRender, Field(discriminator="type")]
