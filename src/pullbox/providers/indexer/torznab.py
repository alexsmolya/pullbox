"""Torznab indexer implementation.

Extends the Newznab indexer for torrent-based indexers. Adds seeders,
leechers, and other torrent-specific attributes to search results.

Torznab is a Newznab-compatible API extension used by Jackett, Prowlarr,
and torrent indexers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.providers.base import ReleaseResult

if TYPE_CHECKING:
    from xml.etree import ElementTree
from pullbox.providers.indexer.newznab import (
    NewznabIndexer,
    _parse_item_common,
    _safe_int,
)


class TorznabIndexer(NewznabIndexer):
    """Torznab implementation of the Indexer protocol.

    Inherits all Newznab logic and overrides torrent-specific behaviour:
    ``supports_torrent = True``, ``supports_nzb = False``, and search
    results include seeders/leechers.  Constructor args are identical
    to ``NewznabIndexer``.
    """

    @property
    def indexer_type(self) -> str:
        return "torznab"

    @property
    def supports_nzb(self) -> bool:
        return False

    @property
    def supports_torrent(self) -> bool:
        return True

    def _parse_item(self, item: ElementTree.Element) -> ReleaseResult:
        """Parse a single RSS <item> with torrent-specific attributes."""
        title, download_url, size_bytes, attrs, published_at, age_days, info_url = (
            _parse_item_common(item)
        )

        return ReleaseResult(
            title=title,
            indexer_name=self._name,
            download_url=download_url,
            size_bytes=size_bytes,
            age_days=age_days,
            seeders=_safe_int(attrs.get("seeders")),
            leechers=_safe_int(attrs.get("peers")),
            grabs=_safe_int(attrs.get("grabs")),
            is_torrent=True,
            category=attrs.get("category"),
            published_at=published_at,
            info_url=info_url,
        )
