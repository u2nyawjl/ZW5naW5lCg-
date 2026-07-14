import hashlib


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def md5_bytes(content: bytes) -> str:
    """Solo para correlacionar con fuentes de terceros; nunca como control de integridad."""
    return hashlib.md5(content, usedforsecurity=False).hexdigest()
