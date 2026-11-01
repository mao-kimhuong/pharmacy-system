from datetime import date
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


class InvoiceRender(BaseModel):
    """80 mm receipt or A4 invoice. Permission pos.sell or sales.view, own branches."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["receipt_80mm", "invoice_a4"]
    invoice_id: UUID
    lang: Literal["km", "en"] | None = Field(default=None, description="Default: the branch setting receipt_lang")


class DispensingLabelRender(BaseModel):
    """Labels for the Rx lines of an invoice. Permission pos.dispense_rx or prescriptions.view."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["dispensing_label"]
    invoice_id: UUID
    line_no: int | None = Field(default=None, ge=1, description="Left out: every Rx line")
    lang: Literal["km", "en"] = "km"
    size: Literal["70x40", "50x30", "100x50", "a4_sheet"] | None = Field(
        default=None, description="Left out: the branch setting dispensing_label_size (70x40 by default)"
    )


class RxSummaryRender(BaseModel):
    """The patient's allergies and prescriptions (A4). Permission prescriptions.view; logged."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["rx_summary"]
    patient_id: UUID


class RegisterRender(BaseModel):
    """The controlled-drug register (A4, Khmer/English). Permission controlled.view, own branches."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["controlled_register"]
    branch_id: UUID
    medicine_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class TransferNoteRender(BaseModel):
    """Transfer note with a QR code of the number. Any transfers.* permission, source or destination."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["transfer_note"]
    transfer_id: UUID


class PurchaseOrderGroupRender(BaseModel):
    """The POs of a group (several branches, one supplier) on one printout. Permission purchasing.order."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["purchase_order_group"]
    group_id: UUID


class SaleOrderRender(BaseModel):
    """Quote or sale order (A4, Khmer/English). Permission sales.orders or sales.view, own branches."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sale_order"]
    sale_order_id: UUID


class SupplierReturnRender(BaseModel):
    """Return note for the supplier. Permission purchasing.return, own branches."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["supplier_return"]
    supplier_return_id: UUID
    lang: Literal["km", "en"] = "km"


class CustomerStatementRender(BaseModel):
    """A customer's statement. Permission contacts.customers."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["customer_statement"]
    customer_id: UUID
    date_from: date | None = None
    date_to: date | None = None
    lang: Literal["km", "en"] = "km"


RenderRequest = Annotated[
    LabelRender
    | PurchaseOrderRender
    | InvoiceRender
    | DispensingLabelRender
    | RxSummaryRender
    | RegisterRender
    | TransferNoteRender
    | PurchaseOrderGroupRender
    | SaleOrderRender
    | SupplierReturnRender
    | CustomerStatementRender,
    Field(discriminator="type"),
]


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    kind: str = Field(default="text", max_length=10)


class TableRender(BaseModel):
    """A report as a PDF (internal: the reports service)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=160)
    filters: dict[str, str] = Field(default_factory=dict)
    columns: list[TableColumn] = Field(min_length=1, max_length=40)
    rows: list[list[str]] = Field(max_length=5000)
    summary: dict[str, str] = Field(default_factory=dict)
