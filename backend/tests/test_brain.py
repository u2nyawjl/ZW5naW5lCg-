import httpx
import pytest
import respx

from app.agent.brain import Brain

pytestmark = pytest.mark.asyncio

MODELS_URL = "https://models.github.ai/inference/chat/completions"


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@respx.mock
async def test_classify_parses_relevant_json():
    respx.post(MODELS_URL).mock(return_value=_reply(
        '{"relevant": true, "category": "reunion", "reason": "tiene fecha", "summary": "Reunión el lunes"}'
    ))
    brain = Brain(token="t")

    out = await brain.classify_email("prof@u.cl", "Reunión", "El lunes a las 10", "misión")

    assert out["relevant"] is True
    assert out["category"] == "reunion"


@respx.mock
async def test_classify_malformed_json_defaults_to_relevant():
    """Ante una respuesta ilegible, guardar de más es más seguro que perder algo."""
    respx.post(MODELS_URL).mock(return_value=_reply("lo siento, no puedo"))
    brain = Brain(token="t")

    out = await brain.classify_email("x@y.z", "asunto", "cuerpo", "misión")

    assert out["relevant"] is True


@respx.mock
async def test_classify_sends_json_mode_and_bounds_tokens():
    route = respx.post(MODELS_URL).mock(return_value=_reply(
        '{"relevant": false, "category": "ruido", "reason": "promo", "summary": ""}'
    ))
    brain = Brain(token="t")

    await brain.classify_email("promo@shop.com", "50% OFF", "compra ya", "misión")

    import json
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] <= 300


@respx.mock
async def test_rate_limit_retries_then_raises():
    respx.post(MODELS_URL).mock(return_value=httpx.Response(429))
    brain = Brain(token="t")

    with pytest.raises(httpx.HTTPStatusError):
        await brain.classify_email("a@b.c", "x", "y", "m")

    # tenacity reintenta: más de una llamada confirma el backoff.
    assert respx.calls.call_count == 3
