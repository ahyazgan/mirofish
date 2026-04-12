"""
API Sağlık Monitörü - Borsa API bağlantılarını sürekli kontrol eder.
Latency, rate limit, bağlantı durumu izleme.
Tamamen yerel - ek maliyet yok.
"""

import httpx
import time
from datetime import datetime, timezone

from .base_agent import BaseAgent


class ApiHealthAgent(BaseAgent):
    """
    Görev: Borsa API sağlığını sürekli izle
    Girdi: Borsa API'lerine ping
    Çıktı: Sağlık durumu → Kill Switch, Alert, Orchestrator

    Kontroller:
    - Ping/latency ölçümü (her 10sn)
    - Rate limit kullanım oranı
    - Bağlantı durumu
    - Yanıt doğruluğu
    """

    # API endpoint'leri (hafif, hızlı)
    HEALTH_CHECKS = {
        'binance_spot': {
            'url': 'https://api.binance.com/api/v3/ping',
            'method': 'GET',
            'critical': True,
        },
        'binance_futures': {
            'url': 'https://fapi.binance.com/fapi/v1/ping',
            'method': 'GET',
            'critical': True,
        },
    }

    # Eşikler
    LATENCY_WARN_MS = 500     # 500ms üstü uyarı
    LATENCY_CRITICAL_MS = 2000 # 2s üstü kritik
    MAX_CONSECUTIVE_FAIL = 3   # 3 üst üste başarısız = alarm

    def __init__(self, interval: float = 10.0):
        super().__init__('API Saglik Monitoru', interval=interval)
        self._health_status: dict[str, dict] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._latency_history: dict[str, list[float]] = {}

    @property
    def health_stats(self) -> dict:
        return {
            'endpoints': self._health_status.copy(),
            'overall': self._get_overall_health(),
        }

    async def run_cycle(self):
        await self.receive_all()

        for name, config in self.HEALTH_CHECKS.items():
            result = await self._check_endpoint(name, config)

            self._health_status[name] = result

            # Hata takibi
            if not result['healthy']:
                self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1

                if self._consecutive_failures[name] >= self.MAX_CONSECUTIVE_FAIL:
                    if config['critical']:
                        # Kill Switch'e bildir
                        await self.send('kill_switch', {
                            'type': 'api_critical_error',
                            'endpoint': name,
                            'consecutive_failures': self._consecutive_failures[name],
                            'last_error': result.get('error', ''),
                        })

                    await self.send('alert', {
                        'type': 'api_health_critical',
                        'endpoint': name,
                        'failures': self._consecutive_failures[name],
                        'error': result.get('error', ''),
                    })

                    self.logger.warning(
                        f"API KRITIK | {name} {self._consecutive_failures[name]}x başarısız"
                    )
            else:
                if self._consecutive_failures.get(name, 0) > 0:
                    # Düzeldi
                    await self.send('kill_switch', {
                        'type': 'api_ok',
                        'endpoint': name,
                    })
                self._consecutive_failures[name] = 0

            # Yüksek latency uyarısı
            if result['healthy'] and result.get('latency_ms', 0) > self.LATENCY_WARN_MS:
                self.logger.info(
                    f"API YAVAS | {name} latency={result['latency_ms']:.0f}ms "
                    f"(limit={self.LATENCY_WARN_MS}ms)"
                )

        # Periyodik durum raporu (her 30 döngüde)
        if self.stats['cycles'] % 30 == 0:
            overall = self._get_overall_health()
            self.logger.info(
                f"API DURUM | {overall} | "
                + " | ".join(
                    f"{name}: {data.get('latency_ms', 0):.0f}ms"
                    for name, data in self._health_status.items()
                    if data.get('healthy')
                )
            )

    async def _check_endpoint(self, name: str, config: dict) -> dict:
        """Tek endpoint sağlık kontrolü"""
        try:
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=5) as client:
                if config['method'] == 'GET':
                    resp = await client.get(config['url'])
                else:
                    resp = await client.post(config['url'])

            latency_ms = (time.monotonic() - start) * 1000

            # Latency geçmişi
            if name not in self._latency_history:
                self._latency_history[name] = []
            self._latency_history[name].append(latency_ms)
            if len(self._latency_history[name]) > 100:
                self._latency_history[name] = self._latency_history[name][-100:]

            avg_latency = sum(self._latency_history[name][-10:]) / min(len(self._latency_history[name]), 10)

            # Rate limit headers (Binance)
            rate_limit_used = 0
            rate_limit_total = 1200
            if 'x-mbx-used-weight-1m' in resp.headers:
                rate_limit_used = int(resp.headers['x-mbx-used-weight-1m'])

            healthy = resp.status_code == 200
            status = 'OK' if healthy else f'HTTP {resp.status_code}'

            if latency_ms > self.LATENCY_CRITICAL_MS:
                status = 'SLOW_CRITICAL'
            elif latency_ms > self.LATENCY_WARN_MS:
                status = 'SLOW'

            return {
                'healthy': healthy,
                'status': status,
                'latency_ms': round(latency_ms, 1),
                'avg_latency_ms': round(avg_latency, 1),
                'rate_limit_used': rate_limit_used,
                'rate_limit_total': rate_limit_total,
                'rate_limit_pct': round(rate_limit_used / rate_limit_total * 100, 1) if rate_limit_total else 0,
                'time': datetime.now(timezone.utc).isoformat(),
            }

        except httpx.TimeoutException:
            return {
                'healthy': False,
                'status': 'TIMEOUT',
                'error': 'Connection timeout (5s)',
                'latency_ms': 5000,
                'time': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                'healthy': False,
                'status': 'ERROR',
                'error': str(e)[:200],
                'latency_ms': 0,
                'time': datetime.now(timezone.utc).isoformat(),
            }

    def _get_overall_health(self) -> str:
        """Genel sağlık durumu"""
        if not self._health_status:
            return 'UNKNOWN'

        all_healthy = all(s.get('healthy', False) for s in self._health_status.values())
        any_critical = any(
            not s.get('healthy', False)
            for name, s in self._health_status.items()
            if self.HEALTH_CHECKS.get(name, {}).get('critical', False)
        )

        if all_healthy:
            return 'HEALTHY'
        elif any_critical:
            return 'CRITICAL'
        else:
            return 'DEGRADED'
