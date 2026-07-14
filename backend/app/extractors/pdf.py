import io

from pypdf import PdfReader


def extract(content: bytes, max_pages: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    reader = PdfReader(io.BytesIO(content))

    if reader.is_encrypted:
        # Contraseña vacía: muchos PDFs solo llevan protección de permisos.
        if reader.decrypt("") == 0:
            raise ValueError("PDF cifrado con contraseña: no se puede extraer texto")
        warnings.append("PDF con cifrado de permisos, abierto sin contraseña")

    pages = reader.pages
    if len(pages) > max_pages:
        warnings.append(f"PDF truncado: {len(pages)} páginas, se leen {max_pages}")
        pages = pages[:max_pages]

    chunks = [(page.extract_text() or "") for page in pages]
    text = "\n\n".join(c.strip() for c in chunks if c.strip())

    if not text:
        warnings.append("PDF sin capa de texto (probablemente escaneado): requiere OCR")

    return text, warnings


def metadata(content: bytes) -> dict:
    reader = PdfReader(io.BytesIO(content))
    info = reader.metadata or {}
    return {
        "pages": len(reader.pages),
        "author": info.get("/Author"),
        "title": info.get("/Title"),
        "created": str(info.get("/CreationDate")) if info.get("/CreationDate") else None,
        "modified": str(info.get("/ModDate")) if info.get("/ModDate") else None,
        "producer": info.get("/Producer"),
        "creator_software": info.get("/Creator"),
    }
