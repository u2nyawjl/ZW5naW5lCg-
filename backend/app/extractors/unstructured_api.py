"""Extracción de texto vía la API de Unstructured.

Amplía la lectura a formatos que los extractores locales no cubren (docx, odt,
imágenes con OCR, html, epub, msg…). Se llama por HTTP, así no arrastra las
dependencias pesadas de `unstructured[all-docs]` al runner de Actions.

Solo se invoca sobre archivos ya APROBADOS por el pipeline (VirusTotal + tipo real):
el binario sale a un tercero, igual que ya salía su hash a VirusTotal.
"""

import httpx


async def extract(
    content: bytes, filename: str, mime: str, api_url: str, api_key: str, timeout: float = 90.0
) -> tuple[str | None, list[str]]:
    """Devuelve (texto, avisos). texto=None si no se pudo extraer."""
    if not api_key or not api_url:
        return None, []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                api_url,
                headers={"unstructured-api-key": api_key, "accept": "application/json"},
                files={"files": (filename, content, mime or "application/octet-stream")},
                data={"strategy": "auto"},
            )
    except Exception as exc:
        return None, [f"Unstructured no respondió: {type(exc).__name__}: {exc}"]

    if resp.status_code != 200:
        return None, [f"Unstructured HTTP {resp.status_code}: {resp.text[:160]}"]

    try:
        elements = resp.json()
    except ValueError:
        return None, ["Unstructured devolvió una respuesta no-JSON"]

    parts = [str(e.get("text", "")).strip() for e in elements if isinstance(e, dict)]
    text = "\n".join(p for p in parts if p)
    if not text:
        return None, ["Unstructured no extrajo texto"]
    return text, []
