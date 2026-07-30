from datetime import datetime
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class Msg(BaseModel):
    success: bool = True
    message: str = ""


class PageOut(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
