"""Shared paging/sorting used by every list endpoint, so they all behave the same."""
from typing import Any
from fastapi import Query
from pydantic import BaseModel


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=200),
        sort_by: str | None = Query(None),
        sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
        q: str | None = Query(None, description="Free text search"),
    ):
        self.page = page
        self.page_size = page_size
        self.sort_by = sort_by
        self.sort_dir = sort_dir
        self.q = q

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


def apply_sort(query, model, sort_by: str | None, sort_dir: str, allowed: dict):
    if sort_by and sort_by in allowed:
        col = allowed[sort_by]
        return query.order_by(col.desc() if sort_dir == "desc" else col.asc())
    return query
