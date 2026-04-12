"""
Market Regime Agent - Piyasa rejimi tespiti
Piyasanın trending mi, ranging mi, volatile mi olduğunu tespit eder.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from collections import defaultdict

from .base_agent import BaseAgent


class MarketRegimeAgent(BaseAgent):
    """
    Görev: Piyasa rejimini tespit et, stratejiye yön ver
    Girdi: Price Tracker'dan fiyat verileri
    Çıktı: Rejim bilgisi → Strategist, Alert

    Rejimler:
    - TRENDING_UP:   Güçlü yükseliş trendi → BUY sinyalleri güçlü
    - TRENDING_DOWN: Güçlü düşüş trendi → SELL sinyalleri güçlü
    - RANGING:       Yatay piyasa → Mean reversion stratejisi
    - VOLATILE:      Yüksek volatilite → Pozisyon küçült
    - BREAKOUT:      Konsolidasyon sonrası kırılım → Momentum takip et
    """

    def __init__(self, interval: float = 120.0):  # 2 dakikada bir
        super().__init__('Piyasa Rejimi', interval=interval)
        self._price_history: dict[str, list[float]] = defaultdict(list)
        self._current_regime: dict[str, str] = {}
        self._regime_history: dict[str, list[str]] = defaultdict(list)

    @property
    def regime_stats(self) -> dict:
        return {
            'regimes': self._current_regime.copy(),
            'market_regime': self._get_overall_regime(),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                prices = msg.get('price_objects', {})
                for coin, data in prices.items():
                    self._price_history[coin].append(data.price)
                    if len(self._price_history[coin]) > 200:
                        self._price_history[coin] = self._price_history[coin][-200:]

        if not self._price_history:
            return

        signals = []

        # BTC rejimi en önemli (tüm piyasayı etkiler)
        btc_regime = self._detect_regime('BTC')
        if btc_regime:
            self._current_regime['BTC'] = btc_regime['regime']
            signals.append(btc_regime)

        # Top 10 coin rejimi
        top_coins = ['ETH', 'SOL', 'XRP', 'BNB', 'ADA', 'DOGE', 'AVAX', 'DOT', 'LINK']
        for coin in top_coins:
            if coin in self._price_history and len(self._price_history[coin]) >= 20:
                result = self._detect_regime(coin)
                if result:
                    self._current_regime[coin] = result['regime']
                    signals.append(result)

        if signals:
            overall = self._get_overall_regime()

            await self.send('strategist', {
                'type': 'regime_signals',
                'signals': signals,
                'overall_regime': overall,
            })
            await self.send('alert', {
                'type': 'regime_update',
                'overall': overall,
                'btc_regime': self._current_regime.get('BTC', 'UNKNOWN'),
                'count': len(signals),
            })

            self.logger.info(
                f"REJIM | Genel={overall} BTC={self._current_regime.get('BTC', '?')} "
                f"({len(signals)} coin analiz edildi)"
            )

    def _detect_regime(self, coin: str) -> dict | None:
        """Tek coin için piyasa rejimi tespit et"""
        prices = self._price_history.get(coin, [])
        if len(prices) < 20:
            return None

        current = prices[-1]
        if current <= 0:
            return None

        # === İndikatörler ===

        # 1. Trend gücü: ADX benzeri (fiyat yönü tutarlılığı)
        trend_strength = self._calc_trend_strength(prices, 20)

        # 2. Yön: SMA eğimi
        sma20 = sum(prices[-20:]) / 20
        sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sma20
        trend_direction = 'up' if current > sma20 > sma50 else 'down' if current < sma20 < sma50 else 'neutral'

        # 3. Volatilite
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(max(1, len(prices)-20), len(prices))]
        volatility = (sum(r**2 for r in returns) / len(returns)) ** 0.5 * 100 if returns else 0

        # 4. Range tespiti (fiyat dar bantta mı)
        recent = prices[-20:]
        price_range = (max(recent) - min(recent)) / current * 100

        # === Rejim Tespiti ===
        regime = 'RANGING'
        signal_score = 0.0
        confidence = 0.5
        reasons = []

        if trend_strength > 0.6 and trend_direction == 'up':
            regime = 'TRENDING_UP'
            signal_score = 0.2 * trend_strength
            confidence = trend_strength
            reasons.append(f'Güçlü yükseliş trendi (güç={trend_strength:.2f})')
        elif trend_strength > 0.6 and trend_direction == 'down':
            regime = 'TRENDING_DOWN'
            signal_score = -0.2 * trend_strength
            confidence = trend_strength
            reasons.append(f'Güçlü düşüş trendi (güç={trend_strength:.2f})')
        elif volatility > 3:
            regime = 'VOLATILE'
            signal_score = 0.0  # Yön belirsiz
            confidence = 0.3
            reasons.append(f'Yüksek volatilite ({volatility:.1f}%)')
        elif price_range < 3:
            # Dar bant → breakout beklentisi
            if trend_strength > 0.3:
                regime = 'BREAKOUT'
                signal_score = 0.1 if trend_direction == 'up' else -0.1
                confidence = 0.4
                reasons.append(f'Konsolidasyon sonrası kırılım beklentisi (range={price_range:.1f}%)')
            else:
                regime = 'RANGING'
                signal_score = 0.0
                confidence = 0.5
                reasons.append(f'Yatay piyasa (range={price_range:.1f}%)')

        # Rejim geçmişi
        self._regime_history[coin].append(regime)
        if len(self._regime_history[coin]) > 50:
            self._regime_history[coin] = self._regime_history[coin][-50:]

        return {
            'coin': coin,
            'regime': regime,
            'trend_strength': round(trend_strength, 3),
            'trend_direction': trend_direction,
            'volatility': round(volatility, 2),
            'price_range': round(price_range, 2),
            'signal_score': round(signal_score, 3),
            'confidence': round(confidence, 3),
            'reason': '; '.join(reasons),
            'source': 'market_regime',
        }

    def _get_overall_regime(self) -> str:
        """Genel piyasa rejimi (BTC ağırlıklı)"""
        btc = self._current_regime.get('BTC', 'UNKNOWN')
        if btc != 'UNKNOWN':
            return btc

        # BTC yoksa çoğunluk
        regimes = list(self._current_regime.values())
        if not regimes:
            return 'UNKNOWN'

        from collections import Counter
        most_common = Counter(regimes).most_common(1)[0][0]
        return most_common

    @staticmethod
    def _calc_trend_strength(prices: list[float], period: int) -> float:
        """
        Trend gücü hesapla (0-1 arası)
        Fiyat hareketlerinin ne kadar tutarlı olduğunu ölçer.
        """
        if len(prices) < period:
            return 0

        recent = prices[-period:]
        moves_up = 0
        moves_down = 0

        for i in range(1, len(recent)):
            if recent[i] > recent[i-1]:
                moves_up += 1
            elif recent[i] < recent[i-1]:
                moves_down += 1

        total = moves_up + moves_down
        if total == 0:
            return 0

        # Tutarlılık: bir yön ne kadar dominant
        dominant = max(moves_up, moves_down)
        consistency = dominant / total

        # Büyüklük: toplam hareket ne kadar büyük
        total_move = abs(recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
        magnitude = min(total_move * 10, 1.0)  # %10 hareket = 1.0

        return (consistency * 0.6 + magnitude * 0.4)
