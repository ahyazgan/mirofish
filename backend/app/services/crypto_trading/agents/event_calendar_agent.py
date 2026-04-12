"""
Olay Takvimi Takipcisi - Bilinen yaklaşan olayları takip eder.
FOMC, CPI, token unlock, halving, fork tarihleri.
CoinMarketCal API + sabit takvim - ücretsiz.
"""

import httpx
from datetime import datetime, timezone, timedelta

from .base_agent import BaseAgent


class EventCalendarAgent(BaseAgent):
    """
    Görev: Yaklaşan önemli olayları takip et, trade kararlarını bilgilendir
    Girdi: CoinMarketCal API, manuel takvim
    Çıktı: Olay uyarıları → Strategist, Alert, Risk Manager

    Mantık:
    - FOMC toplantısından 2 saat önce → Yeni pozisyon açma
    - Token unlock 24 saat içinde → İlgili coinde dikkatli ol
    - Halving yaklaşıyor → Uzun vadeli bullish
    - Hard fork → Volatilite beklenir
    """

    COINMARKETCAL_URL = 'https://developers.coinmarketcal.com/v1/events'

    # Sabit makroekonomik takvim (yaklaşık tarihler - her ay güncellenir)
    RECURRING_EVENTS = {
        'FOMC': {'frequency': 'monthly', 'impact': 'HIGH', 'applies_to': 'all'},
        'CPI': {'frequency': 'monthly', 'impact': 'HIGH', 'applies_to': 'all'},
        'NFP': {'frequency': 'monthly', 'impact': 'MEDIUM', 'applies_to': 'all'},
        'BTC_OPTIONS_EXPIRY': {'frequency': 'monthly', 'impact': 'HIGH', 'applies_to': 'BTC'},
        'ETH_OPTIONS_EXPIRY': {'frequency': 'monthly', 'impact': 'HIGH', 'applies_to': 'ETH'},
    }

    # Bilinen büyük olaylar (manuel güncellenir)
    KNOWN_EVENTS: list[dict] = [
        # Örnek format - gerçek tarihler eklenebilir
        # {'name': 'BTC Halving', 'date': '2028-04-01', 'coin': 'BTC', 'impact': 'CRITICAL'},
    ]

    def __init__(self, interval: float = 600.0):  # 10 dakikada bir
        super().__init__('Olay Takvimi Takipcisi', interval=interval)
        self._upcoming_events: list[dict] = []
        self._alerted_events: set[str] = set()

    @property
    def calendar_stats(self) -> dict:
        return {
            'upcoming_events': len(self._upcoming_events),
            'events': self._upcoming_events[:10],
        }

    async def run_cycle(self):
        await self.receive_all()

        # 1. CoinMarketCal'dan kripto olayları çek
        crypto_events = await self._fetch_crypto_events()

        # 2. Bilinen olayları kontrol et
        known = self._check_known_events()

        all_events = crypto_events + known
        self._upcoming_events = sorted(all_events, key=lambda x: x.get('date', ''))

        # 3. Yaklaşan olaylar için sinyal gönder
        signals = []
        now = datetime.now(timezone.utc)

        for event in all_events:
            event_id = f"{event.get('name', '')}_{event.get('date', '')}"
            if event_id in self._alerted_events:
                continue

            event_date_str = event.get('date', '')
            if not event_date_str:
                continue

            try:
                event_date = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue

            hours_until = (event_date - now).total_seconds() / 3600

            # 24 saat içindeki olaylar için sinyal
            if 0 < hours_until <= 24:
                self._alerted_events.add(event_id)
                impact = event.get('impact', 'MEDIUM')
                coin = event.get('coin', 'MARKET')

                # Yüksek etkili olaylardan önce risk azalt
                if impact in ('CRITICAL', 'HIGH') and hours_until <= 4:
                    signal_score = -0.15  # Etkilenen coinde dikkat
                    reason = f"UYARI: {event['name']} {hours_until:.0f} saat içinde! Yeni pozisyon açma"
                else:
                    signal_score = 0.0  # Bilgilendirme
                    reason = f"Yaklaşan olay: {event['name']} ({hours_until:.0f} saat)"

                signals.append({
                    'coin': coin,
                    'event_name': event['name'],
                    'hours_until': round(hours_until, 1),
                    'impact': impact,
                    'signal_score': signal_score,
                    'applies_to': event.get('applies_to', coin),
                    'reason': reason,
                    'source': 'event_calendar',
                })

        if signals:
            await self.send('strategist', {
                'type': 'calendar_signals',
                'signals': signals,
            })
            await self.send('risk_manager', {
                'type': 'upcoming_events',
                'events': signals,
            })
            await self.send('alert', {
                'type': 'calendar_alert',
                'count': len(signals),
                'events': [{'name': s['event_name'], 'hours': s['hours_until']} for s in signals],
            })

            for s in signals[:3]:
                self.logger.info(f"TAKVIM | {s['event_name']} - {s['hours_until']:.0f}h kaldı ({s['impact']})")

        # Eski alertleri temizle
        if len(self._alerted_events) > 500:
            self._alerted_events = set(list(self._alerted_events)[-250:])

    async def _fetch_crypto_events(self) -> list[dict]:
        """CoinMarketCal'dan kripto olayları çek"""
        events = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # CoinMarketCal free tier
                resp = await client.get(
                    'https://developers.coinmarketcal.com/v1/events',
                    params={
                        'max': 20,
                        'sortBy': 'date_event',
                    },
                    headers={'Accept': 'application/json'},
                )
                if resp.status_code != 200:
                    return events

                data = resp.json()
                for item in data.get('body', data if isinstance(data, list) else []):
                    if isinstance(item, dict):
                        coins = item.get('coins', [])
                        coin_symbol = coins[0].get('symbol', 'UNKNOWN') if coins else 'UNKNOWN'
                        categories = item.get('categories', [])

                        # Etki seviyesi
                        impact = 'MEDIUM'
                        cat_names = [c.get('name', '').lower() for c in categories] if categories else []
                        if any(c in cat_names for c in ['exchange', 'listing', 'partnership']):
                            impact = 'HIGH'
                        elif any(c in cat_names for c in ['hard_fork', 'halving', 'burn']):
                            impact = 'CRITICAL'

                        events.append({
                            'name': item.get('title', {}).get('en', 'Unknown Event') if isinstance(item.get('title'), dict) else str(item.get('title', 'Unknown')),
                            'date': item.get('date_event', ''),
                            'coin': coin_symbol,
                            'impact': impact,
                            'source': 'coinmarketcal',
                        })
        except Exception:
            pass

        return events[:20]

    def _check_known_events(self) -> list[dict]:
        """Bilinen sabit olayları kontrol et"""
        events = []
        now = datetime.now(timezone.utc)

        for event in self.KNOWN_EVENTS:
            try:
                event_date = datetime.fromisoformat(event['date']).replace(tzinfo=timezone.utc)
                if event_date > now:
                    events.append({**event, 'source': 'manual'})
            except (ValueError, KeyError):
                continue

        return events
