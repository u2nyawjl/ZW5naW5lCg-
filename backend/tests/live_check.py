"""Prueba de humo contra la API real de VirusTotal. Consume 2 de las 500 consultas diarias.

    docker compose run --rm --no-deps -v ./backend:/app api python -m tests.live_check
"""

import asyncio
from pathlib import Path

from app.config import get_settings
from app.security.pipeline import ingest_file
from app.security.virustotal import VirusTotalClient
from tests.fixtures import builders


async def main() -> None:
    s = get_settings()
    client = VirusTotalClient(api_key=s.virustotal_api_key)

    casos = [
        ("EICAR (malware de prueba, conocido por VT)", builders.eicar(), "factura_urgente.pdf"),
        ("PDF privado recién creado (hash inédito)", builders.minimal_pdf(), "acta_reunion.pdf"),
    ]

    for titulo, content, filename in casos:
        report = await ingest_file(
            content,
            filename,
            vt_client=client,
            quarantine_dir=Path(s.quarantine_dir),
            logs_dir=Path(s.logs_dir),
            source="live_check",
            unknown_policy=s.vt_unknown_policy,
        )
        print(f"\n=== {titulo} ===")
        print(f"  archivo      : {report.filename}")
        print(f"  sha256       : {report.sha256[:32]}...")
        print(f"  tipo real    : {report.mime}  (mismatch: {report.extension_mismatch})")
        print(f"  virustotal   : {report.virustotal.status} "
              f"({report.virustotal.malicious}/{report.virustotal.total_engines} motores)")
        print(f"  DECISIÓN     : {report.decision.upper()}")
        print(f"  motivo       : {report.reason}")
        print(f"  texto        : {report.text_chars} caracteres extraídos")
        for w in report.warnings:
            print(f"  aviso        : {w}")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
