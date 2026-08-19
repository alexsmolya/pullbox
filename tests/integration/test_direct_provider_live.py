from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pullbox.providers.direct.client import DirectProviderClient
from pullbox.providers.direct.contract import (
    DIRECT_PROVIDER_PROTOCOL_V1,
    DirectResolveRequest,
    DirectSearchRequest,
)
from pullbox.services.direct_provider_registration import (
    DirectProviderRegistrationInput,
    enable_direct_provider,
    list_usable_direct_providers,
    register_direct_provider,
)

BASE_URL = os.environ.get("PULLBOX_PROVIDER_BASE_URL")
TOKEN = os.environ.get("PULLBOX_PROVIDER_TOKEN")

pytestmark = pytest.mark.skipif(
    not BASE_URL or not TOKEN,
    reason="live direct provider endpoint is not configured",
)


async def test_native_registration_search_and_resolve_against_live_provider(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    assert BASE_URL is not None
    assert TOKEN is not None
    registered = await register_direct_provider(
        db_session,
        DirectProviderRegistrationInput(
            endpoint=BASE_URL,
            bearer_token=TOKEN,
            allow_private_http=BASE_URL.startswith("http://"),
            confirm_custom_provider=True,
            priority=10,
        ),
    )
    enabled = await enable_direct_provider(db_session, registered.id)
    usable = await list_usable_direct_providers(db_session)

    assert enabled.enabled is True
    assert [provider.id for provider in usable] == [registered.id]

    async with DirectProviderClient(
        endpoint=BASE_URL,
        bearer_token=TOKEN,
        allow_private_http=BASE_URL.startswith("http://"),
    ) as client:
        search_request = DirectSearchRequest(
            protocol_version=DIRECT_PROVIDER_PROTOCOL_V1,
            request_id=uuid4(),
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            intent={
                "series_title": "Synthetic Adventures",
                "normalized_title": "synthetic adventures",
                "issue_number": "1",
                "year": 2026,
                "preferred_formats": ["cbz"],
            },
            limit=5,
        )
        search = await client.search(search_request)
        candidate = next(item for item in search.candidates if item.can_resolve)
        resolve = await client.resolve(
            DirectResolveRequest(
                protocol_version=DIRECT_PROVIDER_PROTOCOL_V1,
                request_id=uuid4(),
                deadline=datetime.now(UTC) + timedelta(seconds=30),
                provider_candidate_id=candidate.provider_candidate_id,
            )
        )

    assert search.candidates
    assert resolve.artifacts
