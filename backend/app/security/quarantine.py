import os
from pathlib import Path


def store(content: bytes, sha256: str, quarantine_dir: Path) -> Path:
    """Guarda el archivo crudo con permisos 0600 y sin bit de ejecución.

    El nombre en disco es el hash, no el nombre original: un adjunto llamado
    "../../.ssh/authorized_keys" o "informe.pdf\\x00.sh" no puede escapar del directorio.
    """
    shard = quarantine_dir / sha256[:2]
    shard.mkdir(parents=True, exist_ok=True)
    path = shard / f"{sha256}.bin"

    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
    else:
        os.chmod(path, 0o600)

    return path
