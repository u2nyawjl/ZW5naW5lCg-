import httpx
import pytest
import respx

from app.security.models import VTStatus
from app.security.virustotal import (
    VT_BASE_URL,
    QuotaExhausted,
    RateLimiter,
    VirusTotalClient,
)

pytestmark = pytest.mark.asyncio

SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@respx.mock
async def test_rate_limit_response_is_an_error_not_a_clean_verdict():
    """Un 429 no puede leerse como 'limpio': eso dejaría pasar malware con la cuota agotada."""
    respx.get(f"{VT_BASE_URL}/files/{SHA}").mock(return_value=httpx.Response(429))

    verdict = await VirusTotalClient(api_key="k").lookup_hash(SHA)

    assert verdict.status is VTStatus.ERROR
    assert verdict.status is not VTStatus.HARMLESS


@respx.mock
async def test_invalid_key_is_reported_explicitly():
    respx.get(f"{VT_BASE_URL}/files/{SHA}").mock(return_value=httpx.Response(401))

    verdict = await VirusTotalClient(api_key="mala").lookup_hash(SHA)

    assert verdict.status is VTStatus.ERROR
    assert "inválida" in verdict.detail


@respx.mock
async def test_network_failure_does_not_raise():
    respx.get(f"{VT_BASE_URL}/files/{SHA}").mock(side_effect=httpx.ConnectError("sin red"))

    verdict = await VirusTotalClient(api_key="k").lookup_hash(SHA)

    assert verdict.status is VTStatus.ERROR


async def test_daily_quota_is_enforced_locally():
    limiter = RateLimiter(per_minute=10, per_day=2)

    await limiter.acquire()
    await limiter.acquire()

    with pytest.raises(QuotaExhausted):
        await limiter.acquire()
