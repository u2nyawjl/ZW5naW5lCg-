import csv as _csv
import io

MAX_ROWS = 1000


def _decode(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace"), "utf-8/replace"


def extract(content: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    raw, encoding = _decode(content)
    if encoding != "utf-8":
        warnings.append(f"CSV decodificado como {encoding}")

    try:
        dialect = _csv.Sniffer().sniff(raw[:4096])
        delimiter = dialect.delimiter
    except _csv.Error:
        delimiter = ","
        warnings.append("Delimitador no detectado, se asume ','")

    rows: list[str] = []
    for i, row in enumerate(_csv.reader(io.StringIO(raw), delimiter=delimiter)):
        if i >= MAX_ROWS:
            warnings.append(f"CSV truncado en {MAX_ROWS} filas")
            break
        rows.append(" | ".join(row))

    return "\n".join(rows), warnings


def extract_text(content: bytes) -> tuple[str, list[str]]:
    raw, encoding = _decode(content)
    warnings = [] if encoding == "utf-8" else [f"Texto decodificado como {encoding}"]
    return raw, warnings


def metadata(content: bytes) -> dict:
    raw, encoding = _decode(content)
    return {"encoding": encoding, "lines": raw.count("\n") + 1}
