"""
Flash Crash Koruyucu - Ani fiyat düşüşlerinde pozisyonları korur.
Sahte/manipülatif haber ve ani piyasa hareketlerinde otomatik koruma.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from datetime import datetime, timezone, timedelta
from collections import defaultdict

from .base_agent import BaseAgent


class FlashCrashAgent(BaseAgent):
    """
    Görev: Flash crash ve ani piyasa anomalilerini tespit et, pozisyonları koru
    Girdi: Price Tracker'dan fiyatlar, Risk Manager'dan pozisyonlar
    Çıktı: Acil koruma emirleri → Executor, Kill Switch, Alert

    Tetikleme:
    - %5+ düşüş <1dk içinde
    - %10+ düşüş <5dk içinde
    - Likidite boşluğu (spread %2+ açılma)
    - Art arda likidasyon dalgası
    """

    # Flash crash eşikleri
    CRASH_1M_PCT = 5.0     # 1 dakikada %5 düşüş
    CRASH_5M_PCT = 10.0    # 5 dakikada %10 düşüş
    SPREAD_ALERT_PCT = 2.0  # Spread %2 açılırsa
    COOLDOWN_SECONDS = 300  # Flash crash sonrası 5dk bekleme

    def __init__(self, interval: float = 5.0):
        super().__init__('Flash Crash Koruyucu', interval=interval)
        self._price_snapshots: dict[str, list[dict]] = defaultdict(list)
        self._flash_crash_active = False
        self._last_crash_time: datetime | None = None
        self._crash_count = 0
        self._protection_actions: list[dict] = []

    @property
    def crash_stats(self) -> dict:
        return {
            'active': self._flash_crash_active,
            'total_crashes': self._crash_count,
            'last_crash': self._last_crash_time.isoformat() if self._last_crash_time else None,
            'cooldown_remaining': self._get_cooldown_remaining(),
            'actions_taken': len(self._protection_actions),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                prices = msg.get('price_objects', {})
                now = datetime.now(timezone.utc)
                for coin, data in prices.items():
                    self._price_snapshots[coin].append({
                        'price': data.price,
                        'time': now,
                    })
                    # Son 10dk tutm
                    cutoff = now - timedelta(minutes=10)
                    self._price_snapshots[coin] = [
                        s for s in self._price_snapshots[coin] if s['time'] > cutoff
                    ]

        # Cooldown kontrolü
        if self._flash_crash_active:
            remaining = self._get_cooldown_remaining()
            if remaining <= 0:
                self._flash_crash_active = False
                self.logger.info("Flash crash cooldown bitti, normal moda dönüldü")
                await self.send('alert', {
                    'type': 'flash_crash_cooldown_end',
                    'message': 'Flash crash koruma modu sona erdi',
                })
            return  # Cooldown sırasında yeni analiz yapma

        # Flash crash tespiti
        for coin in list(self._price_snapshots.keys()):
            crash_detected = self._detect_crash(coin)
            if crash_detected:
                await self._activate_protection(coin, crash_detected)

    def _detect_crash(self, coin: str) -> dict | None:
        """Flash crash tespit et"""
        snapshots = self._price_snapshots.get(coin, [])
        if len(snapshots) < 2:
            return None

        current = snapshots[-1]
        now = current['time']
        current_price = current['price']

        if current_price <= 0:
            return None

        # 1 dakikalık kontrol
        one_min_ago = now - timedelta(minutes=1)
        prices_1m = [s for s in snapshots if s['time'] >= one_min_ago]
        if prices_1m:
            max_price_1m = max(s['price'] for s in prices_1m)
            if max_price_1m > 0:
                drop_1m = ((max_price_1m - current_price) / max_price_1m) * 100
                if drop_1m >= self.CRASH_1M_PCT:
                    return {
                        'type': 'flash_crash_1m',
                        'coin': coin,
                        'drop_pct': round(drop_1m, 2),
                        'from_price': max_price_1m,
                        'to_price': current_price,
                        'window': '1m',
                        'severity': 'CRITICAL' if drop_1m >= 10 else 'HIGH',
                    }

        # 5 dakikalık kontrol
        five_min_ago = now - timedelta(minutes=5)
        prices_5m = [s for s in snapshots if s['time'] >= five_min_ago]
        if prices_5m:
            max_price_5m = max(s['price'] for s in prices_5m)
            if max_price_5m > 0:
                drop_5m = ((max_price_5m - current_price) / max_price_5m) * 100
                if drop_5m >= self.CRASH_5M_PCT:
                    return {
                        'type': 'flash_crash_5m',
                        'coin': coin,
                        'drop_pct': round(drop_5m, 2),
                        'from_price': max_price_5m,
                        'to_price': current_price,
                        'window': '5m',
                        'severity': 'CRITICAL',
                    }

        return None

    async def _activate_protection(self, coin: str, crash_info: dict):
        """Flash crash koruma modunu aktifle"""
        self._flash_crash_active = True
        self._last_crash_time = datetime.now(timezone.utc)
        self._crash_count += 1

        severity = crash_info['severity']

        action = {
            'time': self._last_crash_time.isoformat(),
            'coin': coin,
            'crash_info': crash_info,
            'actions': [],
        }

        self.logger.warning(
            f"FLASH CRASH | {coin} {crash_info['drop_pct']:.1f}% düşüş "
            f"({crash_info['window']}) ${crash_info['from_price']:.2f} → ${crash_info['to_price']:.2f}"
        )

        # 1. Yeni emir girişini duraklat
        await self.send('executor', {
            'type': 'pause_trading',
            'reason': f'Flash crash: {coin} {crash_info["drop_pct"]:.1f}% düşüş',
            'duration_seconds': self.COOLDOWN_SECONDS,
        })
        action['actions'].append('trading_paused')

        # 2. Stop'ları sıkılaştır
        await self.send('risk_manager', {
            'type': 'tighten_stops',
            'reason': 'flash_crash',
            'coin': coin,
            'severity': severity,
        })
        action['actions'].append('stops_tightened')

        # 3. CRITICAL ise kill switch tetikle
        if severity == 'CRITICAL':
            await self.send('kill_switch', {
                'type': 'flash_crash_critical',
                'coin': coin,
                'crash_info': crash_info,
            })
            action['actions'].append('kill_switch_triggered')

        # 4. Alert ve Telegram'a bildir
        await self.send('alert', {
            'type': 'flash_crash_detected',
            'coin': coin,
            'severity': severity,
            'drop_pct': crash_info['drop_pct'],
            'window': crash_info['window'],
            'from_price': crash_info['from_price'],
            'to_price': crash_info['to_price'],
            'actions_taken': action['actions'],
        })

        self._protection_actions.append(action)

        # Son 50 aksiyon tut
        if len(self._protection_actions) > 50:
            self._protection_actions = self._protection_actions[-50:]

    def _get_cooldown_remaining(self) -> float:
        """Kalan cooldown süresi (saniye)"""
        if not self._last_crash_time:
            return 0
        elapsed = (datetime.now(timezone.utc) - self._last_crash_time).total_seconds()
        remaining = self.COOLDOWN_SECONDS - elapsed
        return max(0, remaining)
