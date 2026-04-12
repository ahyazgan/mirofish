"""
Order Book Agent - Emir defteri analizi
Binance order book'tan büyük alım/satım duvarlarını tespit eder.
Binance public API - ücretsiz, auth gerekmez.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class OrderBookAgent(BaseAgent):
    """
    Görev: Emir defterindeki büyük duvarları tespit et
    Girdi: Binance Order Book API (ücretsiz)
    Çıktı: Order book sinyalleri → Strategist, Alert

    Mantık:
    - Büyük alım duvarı (bid wall) → Destek seviyesi, bullish
    - Büyük satım duvarı (ask wall) → Direnç seviyesi, bearish
    - Bid/Ask oranı > 1.5 → Alım baskısı, bullish
    - Bid/Ask oranı < 0.67 → Satış baskısı, bearish
    """

    BINANCE_DEPTH_URL = 'https://api.binance.com/api/v3/depth'

    def __init__(self, interval: float = 60.0):
        super().__init__('Emir Defteri Analizcisi', interval=interval)
        self._bid_ask_history: dict[str, list[dict]] = {}

    async def run_cycle(self):
        await self.receive_all()

        # En popüler 15 coin için order book analizi
        top_coins = [
            'BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'ADA', 'DOGE',
            'AVAX', 'DOT', 'LINK', 'MATIC', 'UNI', 'LTC', 'NEAR', 'SUI',
        ]

        signals = []

        for coin in top_coins:
            result = await self._analyze_orderbook(coin)
            if result:
                signals.append(result)

        if signals:
            await self.send('strategist', {
                'type': 'orderbook_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'orderbook_analysis',
                'count': len(signals),
                'coins': [s['coin'] for s in signals],
            })

            for s in signals[:3]:
                self.logger.info(
                    f"ORDERBOOK | {s['coin']} ratio={s['bid_ask_ratio']:.2f} "
                    f"score={s['signal_score']} - {s['reason']}"
                )

    async def _analyze_orderbook(self, coin: str) -> dict | None:
        """Tek coin için order book analizi"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.BINANCE_DEPTH_URL,
                    params={
                        'symbol': f'{coin}USDT',
                        'limit': 100,  # 100 seviye
                    }
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                bids = data.get('bids', [])  # [[price, qty], ...]
                asks = data.get('asks', [])

                if not bids or not asks:
                    return None

                # Toplam bid ve ask hacmi
                total_bid_vol = sum(float(b[0]) * float(b[1]) for b in bids)
                total_ask_vol = sum(float(a[0]) * float(a[1]) for a in asks)

                if total_ask_vol == 0:
                    return None

                bid_ask_ratio = total_bid_vol / total_ask_vol

                # Büyük duvar tespiti
                avg_bid_size = total_bid_vol / len(bids)
                avg_ask_size = total_ask_vol / len(asks)

                bid_walls = []
                ask_walls = []

                for b in bids:
                    size_usdt = float(b[0]) * float(b[1])
                    if size_usdt > avg_bid_size * 5:  # 5x ortalama
                        bid_walls.append({
                            'price': float(b[0]),
                            'size_usdt': round(size_usdt, 2),
                        })

                for a in asks:
                    size_usdt = float(a[0]) * float(a[1])
                    if size_usdt > avg_ask_size * 5:
                        ask_walls.append({
                            'price': float(a[0]),
                            'size_usdt': round(size_usdt, 2),
                        })

                # Geçmiş kaydet
                if coin not in self._bid_ask_history:
                    self._bid_ask_history[coin] = []
                self._bid_ask_history[coin].append({
                    'ratio': bid_ask_ratio,
                    'time': datetime.now(timezone.utc).isoformat(),
                })
                if len(self._bid_ask_history[coin]) > 50:
                    self._bid_ask_history[coin] = self._bid_ask_history[coin][-50:]

                # Sinyal üret
                signal_score = 0.0
                reasons = []

                # Bid/Ask oranı
                if bid_ask_ratio > 1.5:
                    signal_score += 0.2
                    reasons.append(f'Güçlü alım baskısı (bid/ask={bid_ask_ratio:.2f})')
                elif bid_ask_ratio > 1.2:
                    signal_score += 0.1
                    reasons.append(f'Alım baskısı (bid/ask={bid_ask_ratio:.2f})')
                elif bid_ask_ratio < 0.67:
                    signal_score -= 0.2
                    reasons.append(f'Güçlü satış baskısı (bid/ask={bid_ask_ratio:.2f})')
                elif bid_ask_ratio < 0.83:
                    signal_score -= 0.1
                    reasons.append(f'Satış baskısı (bid/ask={bid_ask_ratio:.2f})')

                # Büyük duvarlar
                if bid_walls and not ask_walls:
                    signal_score += 0.15
                    reasons.append(f'{len(bid_walls)} büyük destek duvarı')
                elif ask_walls and not bid_walls:
                    signal_score -= 0.15
                    reasons.append(f'{len(ask_walls)} büyük direnç duvarı')

                if abs(signal_score) < 0.1:
                    return None

                return {
                    'coin': coin,
                    'bid_ask_ratio': round(bid_ask_ratio, 3),
                    'total_bid_usdt': round(total_bid_vol, 2),
                    'total_ask_usdt': round(total_ask_vol, 2),
                    'bid_walls': bid_walls[:3],
                    'ask_walls': ask_walls[:3],
                    'signal_score': round(signal_score, 3),
                    'reason': '; '.join(reasons),
                    'source': 'orderbook',
                }

        except Exception:
            return None
