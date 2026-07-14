import asyncio
import time
from collections import deque

import httpx

from app.security.models import VTStatus, VTVerdict

VT_BASE_URL = "https://www.virustotal.com/api/v3"

# Free tier: 4 peticiones/minuto y 500/día. Excederlo devuelve 429 y VT puede
# suspender la key, así que el límite se aplica aquí y no se descubre a golpes.
FREE_TIER_PER_MINUTE = 4
FREE_TIER_PER_DAY = 500


class RateLimiter:
    def __init__(self, per_minute: int = FREE_TIER_PER_MINUTE, per_day: int = FREE_TIER_PER_DAY):
        self.per_minute = per_minute
        self.per_day = per_day
        self._minute: deque[float] = deque()
        self._day: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._minute and now - self._minute[0] > 60:
                    self._minute.popleft()
                while self._day and now - self._day[0] > 86_400:
                    self._day.popleft()

                if len(self._day) >= self.per_day:
                    raise QuotaExhausted("cuota diaria de VirusTotal agotada (500/día)")

                if len(self._minute) < self.per_minute:
                    self._minute.append(now)
                    self._day.append(now)
                    return

                await asyncio.sleep(60 - (now - self._minute[0]) + 0.1)


class QuotaExhausted(RuntimeError):
    pass


class VirusTotalClient:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
    ):
        self.api_key = api_key
        self._client = client
        self._limiter = limiter or RateLimiter()

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def lookup_hash(self, sha256: str) -> VTVerdict:
        """Consulta por hash: no envía el archivo, así que no expone su contenido."""
        if not self.api_key:
            return VTVerdict(status=VTStatus.SKIPPED, detail="VIRUSTOTAL_API_KEY no configurada")

        try:
            await self._limiter.acquire()
        except QuotaExhausted as exc:
            return VTVerdict(status=VTStatus.ERROR, detail=str(exc))

        client = await self._http()
        try:
            resp = await client.get(
                f"{VT_BASE_URL}/files/{sha256}",
                headers={"x-apikey": self.api_key, "accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return VTVerdict(status=VTStatus.ERROR, detail=f"red: {exc}")

        if resp.status_code == 404:
            return VTVerdict(status=VTStatus.UNKNOWN, detail="hash nunca visto por VirusTotal")
        if resp.status_code == 401:
            return VTVerdict(status=VTStatus.ERROR, detail="API key de VirusTotal inválida")
        if resp.status_code == 429:
            return VTVerdict(status=VTStatus.ERROR, detail="rate limit de VirusTotal excedido")
        if resp.status_code != 200:
            return VTVerdict(status=VTStatus.ERROR, detail=f"HTTP {resp.status_code}")

        stats = resp.json()["data"]["attributes"].get("last_analysis_stats", {})
        malicious = int(stats.get("malicious", 0))
        suspicious = int(stats.get("suspicious", 0))
        harmless = int(stats.get("harmless", 0))
        undetected = int(stats.get("undetected", 0))

        if malicious > 0:
            status = VTStatus.MALICIOUS
        elif suspicious > 0:
            status = VTStatus.SUSPICIOUS
        else:
            status = VTStatus.HARMLESS

        return VTVerdict(
            status=status,
            malicious=malicious,
            suspicious=suspicious,
            harmless=harmless,
            total_engines=malicious + suspicious + harmless + undetected,
            permalink=f"https://www.virustotal.com/gui/file/{sha256}",
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
