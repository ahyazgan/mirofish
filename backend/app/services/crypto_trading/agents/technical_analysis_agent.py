"""
Technical Analysis Agent - Teknik analiz
RSI, MACD, Bollinger Bands, EMA crossover hesaplar.
Tamamen yerel hesaplama - ek API maliyeti yok.
"""

import httpx
from collections import defaultdict

from .base_agent import BaseAgent


class TechnicalAnalysisAgent(BaseAgent):
    """
    Görev: Teknik indikatörler hesapla, sinyal üret
    Girdi: Price Tracker'dan fiyat verileri
    Çıktı: Teknik sinyaller → Strategist'e
    """

    def __init__(self, interval: float = 60.0):
        super().__init__('Teknik Analizci', interval=interval)
        self._price_history: dict[str, list[float]] = defaultdict(list)
        self._latest_prices: dict = {}
        self._kline_cache: dict[str, list] = {}

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                self._latest_prices = msg.get('price_objects', {})
                for coin, data in self._latest_prices.items():
                    self._price_history[coin].append(data.price)
                    # Son 200 fiyat tut
                    if len(self._price_history[coin]) > 200:
                        self._price_history[coin] = self._price_history[coin][-200:]

        if not self._latest_prices:
            return

        # Binance'den kline verisi çek (daha doğru analiz için)
        await self._fetch_klines()

        # Teknik analiz yap
        signals = []
        for coin in list(self._latest_prices.keys())[:20]:  # İlk 20 coin
            result = self._analyze_coin(coin)
            if result:
                signals.append(result)

        if signals:
            await self.send('strategist', {
                'type': 'technical_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'technical_analysis',
                'count': len(signals),
                'coins': [s['coin'] for s in signals],
            })
            self.logger.info(f"Teknik analiz: {len(signals)} sinyal üretildi")

    async def _fetch_klines(self):
        """Binance'den 1h kline verisi çek"""
        coins_to_fetch = [c for c in list(self._latest_prices.keys())[:20]
                         if c not in self._kline_cache]

        for coin in coins_to_fetch:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        'https://api.binance.com/api/v3/klines',
                        params={
                            'symbol': f'{coin}USDT',
                            'interval': '1h',
                            'limit': 50,
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        closes = [float(k[4]) for k in data]
                        volumes = [float(k[5]) for k in data]
                        highs = [float(k[2]) for k in data]
                        lows = [float(k[3]) for k in data]
                        self._kline_cache[coin] = {
                            'closes': closes,
                            'volumes': volumes,
                            'highs': highs,
                            'lows': lows,
                        }
            except Exception:
                pass

    def _analyze_coin(self, coin: str) -> dict | None:
        """Tek coin için teknik analiz"""
        kline = self._kline_cache.get(coin)
        if not kline or len(kline['closes']) < 26:
            return None

        closes = kline['closes']
        highs = kline['highs']
        lows = kline['lows']
        volumes = kline['volumes']

        # RSI (14 periyot)
        rsi = self._calc_rsi(closes, 14)

        # MACD (12, 26, 9)
        macd_line, signal_line, histogram = self._calc_macd(closes)

        # Bollinger Bands (20, 2)
        bb_upper, bb_middle, bb_lower = self._calc_bollinger(closes, 20, 2)

        # EMA Crossover (9 vs 21)
        ema9 = self._calc_ema(closes, 9)
        ema21 = self._calc_ema(closes, 21)

        # Volume analizi
        avg_volume = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        current_price = closes[-1]

        # Skor hesapla (-1.0 ile 1.0 arası)
        score = 0.0
        reasons = []

        # RSI sinyali
        if rsi is not None:
            if rsi < 30:
                score += 0.3
                reasons.append(f'RSI aşırı satım ({rsi:.1f})')
            elif rsi > 70:
                score -= 0.3
                reasons.append(f'RSI aşırı alım ({rsi:.1f})')
            elif rsi < 40:
                score += 0.1
            elif rsi > 60:
                score -= 0.1

        # MACD sinyali
        if macd_line is not None and signal_line is not None:
            if macd_line > signal_line and histogram > 0:
                score += 0.25
                reasons.append('MACD bullish crossover')
            elif macd_line < signal_line and histogram < 0:
                score -= 0.25
                reasons.append('MACD bearish crossover')

        # Bollinger Bands sinyali
        if bb_lower is not None:
            if current_price <= bb_lower:
                score += 0.2
                reasons.append('Fiyat Bollinger alt bandında')
            elif current_price >= bb_upper:
                score -= 0.2
                reasons.append('Fiyat Bollinger üst bandında')

        # EMA Crossover
        if ema9 is not None and ema21 is not None:
            if ema9 > ema21:
                score += 0.15
                reasons.append('EMA9 > EMA21 (bullish)')
            else:
                score -= 0.15
                reasons.append('EMA9 < EMA21 (bearish)')

        # Volume desteği
        if volume_ratio > 1.5:
            score *= 1.3  # Volume destekliyor
            reasons.append(f'Yüksek hacim (x{volume_ratio:.1f})')

        # Minimum sinyal gücü
        if abs(score) < 0.2:
            return None

        return {
            'coin': coin,
            'score': round(max(-1.0, min(1.0, score)), 3),
            'rsi': round(rsi, 1) if rsi else None,
            'macd': 'bullish' if (macd_line and signal_line and macd_line > signal_line) else 'bearish',
            'bollinger': 'lower' if (bb_lower and current_price <= bb_lower) else
                        'upper' if (bb_upper and current_price >= bb_upper) else 'middle',
            'ema_cross': 'bullish' if (ema9 and ema21 and ema9 > ema21) else 'bearish',
            'volume_ratio': round(volume_ratio, 2),
            'reasons': reasons,
            'source': 'technical_analysis',
        }

    @staticmethod
    def _calc_rsi(prices: list[float], period: int = 14) -> float | None:
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = deltas[-(period):]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_ema(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def _calc_macd(prices: list[float]) -> tuple:
        if len(prices) < 26:
            return None, None, None

        def ema(data, period):
            m = 2 / (period + 1)
            e = sum(data[:period]) / period
            for p in data[period:]:
                e = (p - e) * m + e
            return e

        # Tüm periyot boyunca EMA hesapla
        ema12_values = []
        ema26_values = []
        e12 = sum(prices[:12]) / 12
        e26 = sum(prices[:26]) / 26
        m12 = 2 / 13
        m26 = 2 / 27

        for i, p in enumerate(prices):
            if i < 12:
                continue
            e12 = (p - e12) * m12 + e12
            if i >= 25:
                e26 = (p - e26) * m26 + e26
                ema12_values.append(e12)
                ema26_values.append(e26)

        if not ema12_values:
            return None, None, None

        macd_line = ema12_values[-1] - ema26_values[-1]

        # Signal line (9-period EMA of MACD)
        macd_values = [e12 - e26 for e12, e26 in zip(ema12_values, ema26_values)]
        if len(macd_values) >= 9:
            signal = sum(macd_values[:9]) / 9
            ms = 2 / 10
            for v in macd_values[9:]:
                signal = (v - signal) * ms + signal
        else:
            signal = sum(macd_values) / len(macd_values)

        histogram = macd_line - signal
        return macd_line, signal, histogram

    @staticmethod
    def _calc_bollinger(prices: list[float], period: int = 20, std_dev: int = 2) -> tuple:
        if len(prices) < period:
            return None, None, None
        recent = prices[-period:]
        middle = sum(recent) / period
        variance = sum((p - middle) ** 2 for p in recent) / period
        std = variance ** 0.5
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return upper, middle, lower
