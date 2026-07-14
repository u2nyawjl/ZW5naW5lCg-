import httpx
import pytest
import respx

from app.security.models import Decision, VTStatus
from app.security.pipeline import ingest_file
from app.security.virustotal import VT_BASE_URL, VirusTotalClient
from tests.fixtures import builders

pytestmark = pytest.mark.asyncio


def _vt_response(malicious: int = 0, suspicious: int = 0, harmless: int = 70) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": malicious,
                        "suspicious": suspicious,
                        "harmless": harmless,
                        "undetected": 0,
                    }
                }
            }
        },
    )


@pytest.fixture
def dirs(tmp_path):
    q = tmp_path / "quarantine"
    logs = tmp_path / "logs"
    q.mkdir()
    logs.mkdir()
    return q, logs


async def _run(content, filename, dirs, **kwargs):
    quarantine, logs = dirs
    client = VirusTotalClient(api_key="test-key")
    try:
        return await ingest_file(
            content,
            filename,
            vt_client=client,
            quarantine_dir=quarantine,
            logs_dir=logs,
            **kwargs,
        )
    finally:
        await client.aclose()


@respx.mock
async def test_malicious_file_is_blocked_before_any_parser_runs(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(
        return_value=_vt_response(malicious=58, harmless=12)
    )

    report = await _run(builders.eicar(), "factura_urgente.pdf", dirs)

    assert report.decision is Decision.BLOCK
    assert report.virustotal.status is VTStatus.MALICIOUS
    assert report.text is None, "un archivo malicioso nunca debe llegar al extractor"
    assert report.metadata == {}
    assert "58" in report.reason


@respx.mock
async def test_malicious_file_is_still_quarantined_for_forensics(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response(malicious=40))

    report = await _run(builders.eicar(), "payload.pdf", dirs)

    from pathlib import Path

    stored = Path(report.quarantine_path)
    assert stored.exists()
    assert oct(stored.stat().st_mode)[-3:] == "600", "el crudo no debe ser legible por otros"
    assert stored.read_bytes() == builders.eicar()


@respx.mock
async def test_clean_pdf_is_parsed_with_metadata(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response())

    report = await _run(builders.minimal_pdf(), "informe.pdf", dirs)

    assert report.decision is Decision.ALLOW
    assert report.mime == "application/pdf"
    assert "capstone" in report.text
    assert report.metadata["pages"] == 1
    assert report.sha256 and len(report.sha256) == 64


@respx.mock
async def test_unknown_hash_is_parsed_but_flagged(dirs):
    """El caso normal: un documento privado que VirusTotal nunca ha visto."""
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=httpx.Response(404))

    report = await _run(builders.minimal_pdf(), "acta_reunion.pdf", dirs)

    assert report.decision is Decision.ALLOW
    assert report.virustotal.status is VTStatus.UNKNOWN
    assert report.text
    assert any("no verificado" in w.lower() for w in report.warnings)


@respx.mock
async def test_unknown_hash_is_held_under_strict_policy(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=httpx.Response(404))

    report = await _run(builders.minimal_pdf(), "acta.pdf", dirs, unknown_policy="hold")

    assert report.decision is Decision.HOLD
    assert report.text is None


@respx.mock
async def test_executable_disguised_as_pdf_is_blocked(dirs):
    """Ni siquiera un veredicto limpio de VirusTotal libera un ejecutable."""
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response())

    report = await _run(builders.windows_executable(), "presupuesto_2026.pdf", dirs)

    assert report.decision is Decision.BLOCK
    assert report.extension_mismatch
    assert report.text is None


@respx.mock
async def test_content_type_mismatch_is_held(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response())

    report = await _run(builders.minimal_pdf(), "datos.csv", dirs)

    assert report.decision is Decision.HOLD
    assert report.extension_mismatch


@respx.mock
async def test_zip_bomb_is_stopped_without_crashing_the_ingest(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response())

    report = await _run(
        builders.zip_bomb(uncompressed_mb=8), "telemetria.xlsx", dirs, max_uncompressed_mb=1
    )

    assert report.decision is Decision.ALLOW
    assert report.text is None
    assert any("descompresión" in w for w in report.warnings)


@respx.mock
async def test_xlsx_and_pptx_extraction(dirs):
    respx.get(url__regex=rf"{VT_BASE_URL}/files/.*").mock(return_value=_vt_response())

    xlsx = await _run(builders.minimal_xlsx(), "telemetria.xlsx", dirs)
    assert "AA:BB:CC:DD:EE:FF" in xlsx.text
    assert xlsx.metadata["author"] == "Nico"

    pptx = await _run(builders.minimal_pptx(), "avance.pptx", dirs)
    assert "Avance capstone" in pptx.text
    assert pptx.metadata["author"] == "Nico"


@respx.mock
async def test_oversized_file_is_rejected_before_hashing(dirs):
    with pytest.raises(ValueError, match="excede el límite"):
        await _run(b"\x00" * (2 * 1_048_576), "grande.pdf", dirs, max_file_size_mb=1)


@respx.mock
async def test_no_api_key_degrades_to_unverified_instead_of_failing(dirs):
    quarantine, logs = dirs
    client = VirusTotalClient(api_key="")

    report = await ingest_file(
        builders.minimal_pdf(),
        "sin_key.pdf",
        vt_client=client,
        quarantine_dir=quarantine,
        logs_dir=logs,
    )

    assert report.virustotal.status is VTStatus.SKIPPED
    assert report.decision is Decision.ALLOW
    assert report.text
