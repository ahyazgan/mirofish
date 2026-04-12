"""
Volatility Scanner Agent - Volatilite analizi
ATR, Bollinger genişlik ve volatilite breakout tespiti.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from collections import defaultdict

from .base_agent import BaseAgent


class VolatilityAgent(BaseAgent):
    """
    Görev: Piyasa volatilitesini ölç, breakout/squeeze tespit et
    Girdi: Price Tracker'dan fiyat verileri
    Çıktı: Volatilite sinyalleri → Strategist, Alert

    Mantık:
    - Bollinger Squeeze (dar bant) → Patlama beklenir (yön belirsiz)
    - ATR artışı → Volatilite yükseliyor, dikkatli ol
    - ATR düşüşü → Sakin piyasa, pozisyon artırılabilir
    - Volatilite breakout → Momentum yönünde sinyal
    """

    def __init__(self, interval: float = 60.0):
        super().__init__('Volatilite Tarayici', interval=interval)
        self._price_history: dict[str, list[float]] = defaultdict(list)
        self._high_history: dict[str, list[float]] = defaultdict(list)
        self._low_history: dict[str, list[float]] = defaultdict(list)
        self._atr_history: dict[str, list[float]] = defaultdict(list)
        self._bb_width_history: dict[str, list[float]] = defaultdict(list)

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                prices = msg.get('price_objects', {})
                for coin, data in prices.items():
                    self._price_history[coin].append(data.price)
                    self._high_history[coin].append(data.high_24h if data.high_24h else data.price)
                    self._low_history[coin].append(data.low_24h if data.low_24h else data.price)
                    # Son 100 veri tut
                    for hist in (self._price_history, self._high_history, self._low_history):
                        if len(hist[coin]) > 100:
                            hist[coin] = hist[coin][-100:]

        if not self._price_history:
            return

        signals = []
        for coin in list(self._price_history.keys()):
            result = self._analyze_volatility(coin)
            if result:
                signals.append(result)

        if signals:
            await self.send('strategist', {
                'type': 'volatility_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'volatility_update',
                'count': len(signals),
                'coins': [s['coin'] for s in signals[:5]],
            })
            for s in signals[:3]:
                self.logger.info(
                    f"VOLATILITE | {s['coin']} ATR={s.get('atr_pct', 0):.2f}% "
                    f"BB_width={s.get('bb_width_pct', 0):.2f}% - {s['reason']}"
                )

    def _analyze_volatility(self, coin: str) -> dict | None:
        """Tek coin için volatilite analizi"""
        closes = self._price_history.get(coin, [])
        highs = self._high_history.get(coin, [])
        lows = self._low_history.get(coin, [])

        if len(closes) < 20:
            return None

        current_price = closes[-1]
        if current_price <= 0:
            return None

        # ATR hesapla (14 periyot)
        atr = self._calc_atr(closes, highs, lows, 14)
        atr_pct = (atr / current_price) * 100 if atr and current_price > 0 else 0

        # Bollinger Band genişliği
        bb_width_pct = self._calc_bb_width(closes, 20, 2)

        # Geçmişe kaydet
        self._atr_history[coin].append(atr_pct)
        self._bb_width_history[coin].append(bb_width_pct)
        if len(self._atr_history[coin]) > 50:
            self._atr_history[coin] = self._atr_history[coin][-50:]
        if len(self._bb_width_history[coin]) > 50:
            self._bb_width_history[coin] = self._bb_width_history[coin][-50:]

        # Sinyaller
        signal_score = 0.0
        reasons = []
        regime = 'normal'

        # 1. Bollinger Squeeze (dar bant → patlama beklenir)
        bb_history = self._bb_width_history[coin]
        if len(bb_history) >= 5:
            avg_bb = sum(bb_history[-10:]) / len(bb_history[-10:])
            if bb_width_pct < avg_bb * 0.5:
                regime = 'squeeze'
                reasons.append(f'Bollinger Squeeze: band={bb_width_pct:.2f}% (ort={avg_bb:.2f}%)')
                # Squeeze'de yön belli değil ama breakout yakın
                # Son momentum yönünde hafif sinyal
                momentum = closes[-1] - closes[-5] if len(closes) >= 5 else 0
                signal_score += 0.1 if momentum > 0 else -0.1

        # 2. ATR spike (ani volatilite artışı)
        atr_hist = self._atr_history[coin]
        if len(atr_hist) >= 5:
            avg_atr = sum(atr_hist[-10:]) / len(atr_hist[-10:])
            if atr_pct > avg_atr * 2:
                regime = 'high_volatility'
                reasons.append(f'ATR spike: {atr_pct:.2f}% (ort={avg_atr:.2f}%)')
                # Yüksek volatilite → mevcut sinyalleri güçlendir ama dikkat
                signal_score *= 0.5  # Risk azalt

        # 3. Düşük volatilite (güvenli ortam)
        if atr_pct < 1.0:
            regime = 'low_volatility'
            reasons.append(f'Düşük volatilite: ATR={atr_pct:.2f}%')

        # 4. Volatilite breakout
        if len(closes) >= 20:
            upper_band = max(closes[-20:])
            lower_band = min(closes[-20:])
            band_range = upper_band - lower_band
            if band_range > 0:
                if current_price > upper_band - band_range * 0.05:
                    signal_score += 0.15
                    reasons.append('Üst bant breakout')
                elif current_price < lower_band + band_range * 0.05:
                    signal_score -= 0.15
                    reasons.append('Alt bant breakout')

        if not reasons:
            return None

        return {
            'coin': coin,
            'atr': round(atr, 8) if atr else 0,
            'atr_pct': round(atr_pct, 4),
            'bb_width_pct': round(bb_width_pct, 4),
            'regime': regime,
            'signal_score': round(max(-1, min(1, signal_score)), 3),
            'reason': '; '.join(reasons),
            'source': 'volatility',
        }

    @staticmethod
    def _calc_atr(closes: list, highs: list, lows: list, period: int = 14) -> float | None:
        """Average True Range hesapla"""
        if len(closes) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return sum(true_ranges[-period:]) / period

    @staticmethod
    def _calc_bb_width(closes: list, period: int = 20, std_dev: int = 2) -> float:
        """Bollinger Band genişliğini yüzde olarak hesapla"""
        if len(closes) < period:
            return 0

        recent = closes[-period:]
        middle = sum(recent) / period
        if middle <= 0:
            return 0

        variance = sum((p - middle) ** 2 for p in recent) / period
        std = variance ** 0.5
        width = (2 * std_dev * std) / middle * 100
        return width
