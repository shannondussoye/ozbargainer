from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DealResult:
    """Canonical deal data returned by all scrapers.

    This is the shared contract between FastScraper, BrowserScraper,
    StorageManager, and LiveMonitor. Both scrapers must produce this type;
    downstream consumers can rely on its shape at the type level.
    """

    id: str = ""
    url: str = ""
    title: str = ""
    description: str = ""
    price: str = ""
    coupon_code: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    upvotes: int = 0
    downvotes: int = 0
    comment_count: int = 0
    is_expired: bool = False
    posted_date: str = ""
    external_domain: str = ""
    linked_comment: Optional[str] = None
    linked_comment_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    time_str: str = ""
    user: str = ""
    action: str = ""
    type: str = ""
    original_url: str = ""
    error: Optional[str] = None

    @property
    def has_error(self) -> bool:
        return self.error is not None
