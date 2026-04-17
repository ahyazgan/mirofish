"""
Borsa Listeleme Takipcisi - Yeni coin listeleme/delist duyurularını yakalar.
Binance ve Coinbase duyuru sayfalarını izler.
Ücretsiz - ek maliyet yok.
"""

import httpx
import re
from datetime import datetime, timezone

from .base_agent import BaseAgent


class ExchangeListingAgent(BaseAgent):
    """
    Görev: Borsa listeleme/delisting duyurularını tespit et
    Girdi: Binance, Coinbase duyuru API'leri
    Çıktı: Listeleme sinyalleri → Strategist, Alert (çok yüksek öncelik)

    Mantık:
    - Binance listeleme = coin %20-100 pompa
    - Coinbase listeleme = coin %10-50 pompa
    - Delisting = coin %30-50 düşüş
    - Listeleme haberi çıktıktan sonra hızlı hareket şart
    """

    # Binance duyuru API'si
    BINANCE_ANNOUNCE_URL = 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query'
    # CoinGecko yeni listelemeleri
    COINGECKO_NEW_URL = 'https://api.coingecko.com/api/v3/coins/list/new'

    # Listeleme anahtar kelimeleri
    LISTING_KEYWORDS = {
        'will list', 'lists', 'listing', 'listeleme',
        'adds', 'adding', 'new trading pair',
        'opens trading', 'launches',
    }

    DELISTING_KEYWORDS = {
        'delist', 'delisting', 'remove', 'removing',
        'suspend', 'suspending', 'will remove',
        'cease trading',
    }

    # Büyük borsalar ve etki çarpanları
    EXCHANGE_IMPACT = {
        'binance': 2.0,
        'coinbase': 1.8,
        'kraken': 1.3,
        'okx': 1.2,
        'bybit': 1.1,
    }

    def __init__(self, interval: float = 120.0):  # 2 dakikada bir
        super().__init__('Borsa Listeleme Takipcisi', interval=interval)
        self._seen_announcements: set[str] = set()
        self._listing_events: list[dict] = []

    @property
    def listing_stats(self) -> dict:
        return {
            'total_events': len(self._listing_events),
            'recent': self._listing_events[-5:],
        }

    async def run_cycle(self):
        await self.receive_all()

        signals = []

        # 1. Binance duyuruları
        binance_signals = await self._check_binance_announcements()
        signals.extend(binance_signals)

        if signals:
            self._listing_events.extend(signals)
            if len(self._listing_events) > 100:
                self._listing_events = self._listing_events[-100:]

            await self.send('strategist', {
                'type': 'listing_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'listing_alert',
                'count': len(signals),
                'events': [{'coin': s.get('coin', ''), 'action': s.get('listing_type', '')} for s in signals],
            })

            for s in signals:
                emoji = "🟢" if s.get('listing_type') == 'listing' else "🔴"
                self.logger.info(
                    f"LISTELEME | {s.get('exchange', '?')} {s.get('listing_type', '?')} "
                    f"{s.get('coin', '?')} score={s['signal_score']}"
                )

    async def _check_binance_announcements(self) -> list[dict]:
        """Binance duyurularını kontrol et"""
        signals = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self.BINANCE_ANNOUNCE_URL,
                    json={
                        'type': 1,
                        'catalogId': 48,  # New Cryptocurrency Listing
                        'pageNo': 1,
                        'pageSize': 10,
                    }
                )
                if resp.status_code != 200:
                    return signals

                data = resp.json()
                articles = data.get('data', {}).get('catalogs', [{}])
                if articles:
                    items = articles[0].get('articles', []) if articles else []
                else:
                    items = []

                for item in items:
                    article_id = str(item.get('id', ''))
                    if article_id in self._seen_announcements:
                        continue
                    self._seen_announcements.add(article_id)

                    title = item.get('title', '')
                    signal = self._analyze_listing(title, 'binance')
                    if signal:
                        signals.append(signal)

        except Exception as e:
            self.logger.debug(f"Exchange listing fetch hatası: {e}")

        # Seen cleanup
        if len(self._seen_announcements) > 2000:
            self._seen_announcements = set(list(self._seen_announcements)[-1000:])

        return signals

    def _analyze_listing(self, title: str, exchange: str) -> dict | None:
        """Listeleme duyurusunu analiz et"""
        title_lower = title.lower()

        # Listeleme mi delisting mi?
        is_listing = any(kw in title_lower for kw in self.LISTING_KEYWORDS)
        is_delisting = any(kw in title_lower for kw in self.DELISTING_KEYWORDS)

        if not is_listing and not is_delisting:
            return None

        # Coin sembollerini çıkar (büyük harfli 2-6 karakter)
        symbols = re.findall(r'\b([A-Z]{2,6})\b', title)
        # Yaygın olmayan kelimeleri filtrele
        common_words = {'THE', 'AND', 'FOR', 'NEW', 'WILL', 'HAS', 'NOT', 'ARE', 'WAS', 'CAN'}
        coins = [s for s in symbols if s not in common_words]

        if not coins:
            return None

        impact_multiplier = self.EXCHANGE_IMPACT.get(exchange, 1.0)

        if is_listing:
            listing_type = 'listing'
            base_score = 0.4 * impact_multiplier
        else:
            listing_type = 'delisting'
            base_score = -0.5 * impact_multiplier

        signal_score = max(-1.0, min(1.0, base_score))

        return {
            'coin': coins[0],
            'all_coins': coins[:5],
            'exchange': exchange,
            'listing_type': listing_type,
            'title': title[:200],
            'signal_score': round(signal_score, 3),
            'impact': 'CRITICAL',
            'reason': f'{exchange.upper()} {listing_type}: {", ".join(coins[:3])}',
            'source': 'exchange_listing',
            'time': datetime.now(timezone.utc).isoformat(),
        }
