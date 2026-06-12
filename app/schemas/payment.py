from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CreatePaymentRequest(BaseModel):
    from_account: str = Field(min_length=1)
    to_account: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class PaymentResponse(BaseModel):
    id: UUID
    from_account: str
    to_account: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
