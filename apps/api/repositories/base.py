"""
Base repository pattern.
In production: all methods hit the database.
Currently: delegate to in-memory mock data for development.
The interface is identical either way — swap the implementation, not the callers.
"""
from typing import Optional, TypeVar, Generic
from datetime import datetime, timezone

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Abstract base — concrete repos override these methods."""

    def find_by_id(self, id: str) -> Optional[T]:
        raise NotImplementedError

    def find_all(self, firm_id: Optional[str] = None, **filters) -> list[T]:
        raise NotImplementedError

    def create(self, data: dict) -> T:
        raise NotImplementedError

    def update(self, id: str, data: dict) -> Optional[T]:
        raise NotImplementedError

    def soft_delete(self, id: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
