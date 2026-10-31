# schemas.py
# Pydantic 請求模型（SPEC §5）。股票代號驗證：^[0-9A-Za-z.\-]{1,20}$（SPEC §10.3）。
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

SYMBOL_PATTERN = r"^[0-9A-Za-z.\-]{1,20}$"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class HoldingIn(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    shares: float = Field(gt=0)
    avg_cost: float | None = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


class HoldingUpdateIn(BaseModel):
    shares: float = Field(gt=0)
    avg_cost: float | None = Field(default=None, ge=0)
