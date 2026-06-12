from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAccountRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class AccountResponse(BaseModel):
    id: UUID
    account_number: str
    balance: Decimal
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}
