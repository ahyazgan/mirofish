"""
Whale Tracker Agent - Büyük balina transferlerini izler
Blockchain explorer API'leri ile büyük transferleri tespit eder.
Ücretsiz API - ek maliyet yok.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class WhaleTrackerAgent(BaseAgent):
    """
    Görev: Büyük kripto transferlerini izle (>$500K)
    Girdi: Blockchain explorer API'leri
    Çıktı: Balina hareketleri → Strategist, Alert
    """

    # İzlenecek büyük coinler ve blockchain API'leri
    TRACKED_CHAINS = {
        'BTC': {
            'url': 'https://blockchain.info/unconfirmed-transactions?format=json',
            'min_value_usd': 500_000,
        },
        'ETH': {
            'url': 'https://api.blockchair.com/ethereum/mempool/transactions?limit=10&s=value(desc)',
            'min_value_usd': 500_000,
        },
    }

    # Whale Alert API (ücretsiz tier - 10 request/dakika)
    WHALE_ALERT_URL = 'https://api.whale-alert.io/v1/transactions'

    def __init__(self, interval: float = 120.0):
        super().__init__('Balina Takipcisi', interval=interval)
        self._recent_alerts: list[dict] = []
        self._seen_txids: set[str] = set()
        self._latest_prices: dict = {}

    @property
    def whale_events(self) -> list[dict]:
        return self._recent_alerts[-50:]

    async def run_cycle(self):
        messages = await self.receive_all()
        for msg in messages:
            if msg.get('type') == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

        whale_events = []

        # Yöntem 1: Binance büyük trade'leri (ücretsiz, auth gerekmez)
        binance_whales = await self._check_binance_large_trades()
        whale_events.extend(binance_whales)

        # Yöntem 2: Blockchain.info büyük BTC transferleri
        btc_whales = await self._check_btc_whales()
        whale_events.extend(btc_whales)

        if whale_events:
            self._recent_alerts.extend(whale_events)
            # Son 100 event tut
            self._recent_alerts = self._recent_alerts[-100:]

            await self.send('strategist', {
                'type': 'whale_activity',
                'events': whale_events,
            })
            await self.send('alert', {
                'type': 'whale_alert',
                'count': len(whale_events),
                'events': whale_events,
            })

            for event in whale_events:
                self.logger.info(
                    f"BALINA | {event['coin']} {event['direction']} "
                    f"${event['value_usd']:,.0f} ({event['source']})"
                )

    async def _check_binance_large_trades(self) -> list[dict]:
        """Binance'den son büyük trade'leri kontrol et"""
        events = []
        # En likit 5 coin için kontrol et
        top_coins = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB']

        for coin in top_coins:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        'https://api.binance.com/api/v3/trades',
                        params={
                            'symbol': f'{coin}USDT',
                            'limit': 50,
                        }
                    )
                    if resp.status_code != 200:
                        continue

                    trades = resp.json()
                    for trade in trades:
                        qty = float(trade['qty'])
                        price = float(trade['price'])
                        value_usd = qty * price
                        trade_id = str(trade['id'])

                        # $100K+ trade'ler
                        if value_usd >= 100_000 and trade_id not in self._seen_txids:
                            self._seen_txids.add(trade_id)
                            is_buy = not trade['isBuyerMaker']
                            events.append({
                                'coin': coin,
                                'direction': 'BUY' if is_buy else 'SELL',
                                'value_usd': round(value_usd, 2),
                                'quantity': qty,
                                'price': price,
                                'source': 'binance_trades',
                                'time': datetime.now(timezone.utc).isoformat(),
                                'signal_score': 0.15 if is_buy else -0.15,
                            })
            except Exception:
                pass

        # Çok fazla eski txid biriktirmesin
        if len(self._seen_txids) > 10000:
            self._seen_txids = set(list(self._seen_txids)[-5000:])

        return events

    async def _check_btc_whales(self) -> list[dict]:
        """Blockchain.info'dan büyük BTC transferlerini kontrol et"""
        events = []
        btc_price = 0
        if 'BTC' in self._latest_prices:
            btc_price = self._latest_prices['BTC'].price
        if btc_price <= 0:
            return events

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    'https://blockchain.info/unconfirmed-transactions',
                    params={'format': 'json'},
                )
                if resp.status_code != 200:
                    return events

                data = resp.json()
                txs = data.get('txs', [])[:100]  # Son 100 tx

                for tx in txs:
                    tx_hash = tx.get('hash', '')[:16]
                    if tx_hash in self._seen_txids:
                        continue

                    # Toplam output değeri
                    total_out_btc = sum(
                        o.get('value', 0) for o in tx.get('out', [])
                    ) / 1e8  # satoshi → BTC

                    value_usd = total_out_btc * btc_price

                    if value_usd >= 500_000:
                        self._seen_txids.add(tx_hash)
                        # Exchange'e mi gidiyor?
                        direction = 'TRANSFER'
                        events.append({
                            'coin': 'BTC',
                            'direction': direction,
                            'value_usd': round(value_usd, 2),
                            'quantity': round(total_out_btc, 4),
                            'price': btc_price,
                            'source': 'blockchain',
                            'time': datetime.now(timezone.utc).isoformat(),
                            'signal_score': 0.0,  # Transfer yönü bilinmiyor
                        })
        except Exception:
            pass

        return events
