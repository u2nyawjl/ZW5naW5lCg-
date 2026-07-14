import io
import zipfile

MIME_PDF = "application/pdf"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV = "text/csv"
MIME_TEXT = "text/plain"

SUPPORTED = {MIME_PDF, MIME_PPTX, MIME_XLSX, MIME_CSV, MIME_TEXT}

# libmagic ve un .pptx/.xlsx como un zip: la extensión desempata cuando el contenedor coincide.
OOXML_BY_EXTENSION = {".pptx": MIME_PPTX, ".xlsx": MIME_XLSX}

# Nunca se parsean ni se ejecutan, diga lo que diga VirusTotal.
EXECUTABLE_MIMES = {
    "application/x-dosexec",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-mach-binary",
    "application/x-msdownload",
    "application/vnd.microsoft.portable-executable",
    "application/x-msi",
    "application/x-elf",
    "text/x-shellscript",
    "application/x-bat",
    "application/java-archive",
}

EXECUTABLE_EXTENSIONS = {
    ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar",
    ".msi", ".sh", ".elf", ".apk", ".dmg", ".lnk", ".hta", ".reg",
}


def is_executable(mime: str, extension: str) -> bool:
    return mime in EXECUTABLE_MIMES or extension.lower() in EXECUTABLE_EXTENSIONS


def resolve_mime(detected: str, extension: str) -> str:
    """Un OOXML es un zip para libmagic; se refina con la extensión solo en ese caso."""
    if detected in ("application/zip", "application/octet-stream"):
        return OOXML_BY_EXTENSION.get(extension.lower(), detected)
    return detected


def guard_zip_bomb(content: bytes, max_uncompressed_bytes: int) -> None:
    """Un .xlsx de 2 MB puede descomprimirse a 20 GB y tumbar el contenedor."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        total = sum(info.file_size for info in zf.infolist())
    if total > max_uncompressed_bytes:
        raise ValueError(
            f"bomba de descompresión: {total / 1e6:.0f} MB descomprimidos "
            f"(límite {max_uncompressed_bytes / 1e6:.0f} MB)"
        )
