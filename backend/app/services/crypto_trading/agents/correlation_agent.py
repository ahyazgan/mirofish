"""
Correlation Agent - Piyasa korelasyon analizi
BTC dominansı, altcoin korelasyonu ve piyasa genel durumunu analiz eder.
Tamamen yerel hesaplama + ücretsiz API.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class CorrelationAgent(BaseAgent):
    """
    Görev: BTC dominansı, piyasa korelasyonu ve genel trend analizi
    Girdi: Price Tracker fiyatları + CoinGecko global veri
    Çıktı: Korelasyon sinyalleri → Strategist, Alert

    Mantık:
    - BTC dominans artıyor → Altcoin'ler düşebilir
    - BTC dominans düşüyor → Altcoin rally beklenir
    - Fear & Greed Index extreme → Contrarian sinyal
    """

    GLOBAL_URL = 'https://api.coingecko.com/api/v3/global'
    FEAR_GREED_URL = 'https://api.alternative.me/fng/'

    def __init__(self, interval: float = 300.0):  # 5 dakikada bir
        super().__init__('Korelasyon Analizcisi', interval=interval)
        self._btc_dominance_history: list[float] = []
        self._fear_greed_history: list[dict] = []
        self._market_cap_history: list[float] = []
        self._price_history: dict[str, list[float]] = {}

    @property
    def correlation_stats(self) -> dict:
        return {
            'btc_dominance': self._btc_dominance_history[-1] if self._btc_dominance_history else 0,
            'fear_greed': self._fear_greed_history[-1] if self._fear_greed_history else {},
            'market_cap_trend': self._get_trend(self._market_cap_history),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                prices = msg.get('price_objects', {})
                for coin, data in prices.items():
                    if coin not in self._price_history:
                        self._price_history[coin] = []
                    self._price_history[coin].append(data.price)
                    if len(self._price_history[coin]) > 100:
                        self._price_history[coin] = self._price_history[coin][-100:]

        signals = []

        # 1. Global piyasa verisi
        global_data = await self._fetch_global_data()
        if global_data:
            btc_dom = global_data.get('data', {}).get('market_cap_percentage', {}).get('btc', 0)
            total_mcap = global_data.get('data', {}).get('total_market_cap', {}).get('usd', 0)
            mcap_change = global_data.get('data', {}).get('market_cap_change_percentage_24h_usd', 0)

            self._btc_dominance_history.append(btc_dom)
            self._market_cap_history.append(total_mcap)

            if len(self._btc_dominance_history) > 100:
                self._btc_dominance_history = self._btc_dominance_history[-100:]
            if len(self._market_cap_history) > 100:
                self._market_cap_history = self._market_cap_history[-100:]

            # BTC dominans trendi
            if len(self._btc_dominance_history) >= 2:
                dom_change = self._btc_dominance_history[-1] - self._btc_dominance_history[-2]
                if abs(dom_change) > 0.3:  # %0.3+ değişim
                    # Dominans düşüyor → altcoin sezonu
                    signal = {
                        'type': 'btc_dominance',
                        'btc_dominance': round(btc_dom, 2),
                        'change': round(dom_change, 3),
                        'signal_score': -0.1 if dom_change > 0 else 0.1,  # Altcoinler için
                        'applies_to': 'altcoins',
                        'reason': f'BTC dominans {"artıyor" if dom_change > 0 else "düşüyor"} ({dom_change:+.2f}%)',
                        'source': 'correlation',
                    }
                    signals.append(signal)

            # Piyasa genel trendi
            if abs(mcap_change) > 3:  # %3+ günlük değişim
                signals.append({
                    'type': 'market_trend',
                    'market_cap_change_24h': round(mcap_change, 2),
                    'total_market_cap': total_mcap,
                    'signal_score': 0.15 if mcap_change > 0 else -0.15,
                    'applies_to': 'all',
                    'reason': f'Piyasa 24h değişim: {mcap_change:+.2f}%',
                    'source': 'correlation',
                })

        # 2. Fear & Greed Index
        fg_data = await self._fetch_fear_greed()
        if fg_data:
            fg_value = int(fg_data.get('value', 50))
            fg_class = fg_data.get('value_classification', 'Neutral')
            self._fear_greed_history.append({
                'value': fg_value,
                'class': fg_class,
                'time': datetime.now(timezone.utc).isoformat(),
            })
            if len(self._fear_greed_history) > 100:
                self._fear_greed_history = self._fear_greed_history[-100:]

            # Extreme fear → BUY sinyali (contrarian)
            # Extreme greed → SELL sinyali (contrarian)
            if fg_value <= 20:
                signals.append({
                    'type': 'fear_greed',
                    'value': fg_value,
                    'classification': fg_class,
                    'signal_score': 0.25,  # Extreme fear → BUY
                    'applies_to': 'all',
                    'reason': f'Fear & Greed: {fg_value} ({fg_class}) - Extreme Fear → Contrarian BUY',
                    'source': 'correlation',
                })
            elif fg_value >= 80:
                signals.append({
                    'type': 'fear_greed',
                    'value': fg_value,
                    'classification': fg_class,
                    'signal_score': -0.25,  # Extreme greed → SELL
                    'applies_to': 'all',
                    'reason': f'Fear & Greed: {fg_value} ({fg_class}) - Extreme Greed → Contrarian SELL',
                    'source': 'correlation',
                })

        # 3. BTC-Altcoin korelasyon
        btc_corr_signals = self._calc_btc_altcoin_correlation()
        signals.extend(btc_corr_signals)

        if signals:
            await self.send('strategist', {
                'type': 'correlation_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'correlation_update',
                'count': len(signals),
                'btc_dominance': self._btc_dominance_history[-1] if self._btc_dominance_history else 0,
                'fear_greed': self._fear_greed_history[-1].get('value') if self._fear_greed_history else 'N/A',
            })

            for s in signals[:3]:
                self.logger.info(f"KORELASYON | {s.get('type')} score={s['signal_score']} - {s['reason']}")

    def _calc_btc_altcoin_correlation(self) -> list[dict]:
        """BTC ile altcoin korelasyonunu hesapla"""
        signals = []
        btc_prices = self._price_history.get('BTC', [])
        if len(btc_prices) < 5:
            return signals

        btc_change = (btc_prices[-1] - btc_prices[-5]) / btc_prices[-5] * 100

        for coin, prices in self._price_history.items():
            if coin == 'BTC' or len(prices) < 5:
                continue

            coin_change = (prices[-1] - prices[-5]) / prices[-5] * 100

            # BTC düşerken altcoin yükseliyorsa → güçlü altcoin
            if btc_change < -1 and coin_change > 1:
                signals.append({
                    'type': 'decoupling',
                    'coin': coin,
                    'btc_change': round(btc_change, 2),
                    'coin_change': round(coin_change, 2),
                    'signal_score': 0.2,
                    'reason': f'{coin} BTC\'den bağımsız yükseliyor (BTC {btc_change:+.1f}% vs {coin} {coin_change:+.1f}%)',
                    'source': 'correlation',
                })

        return signals[:5]  # En fazla 5 decouple sinyal

    async def _fetch_global_data(self) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.GLOBAL_URL)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            self.logger.debug(f"Global data fetch hatası: {e}")
        return None

    async def _fetch_fear_greed(self) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.FEAR_GREED_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('data'):
                        return data['data'][0]
        except Exception as e:
            self.logger.debug(f"Fear&Greed fetch hatası: {e}")
        return None

    @staticmethod
    def _get_trend(history: list[float]) -> str:
        if len(history) < 2:
            return 'unknown'
        change = (history[-1] - history[0]) / history[0] * 100 if history[0] > 0 else 0
        if change > 2:
            return 'bullish'
        elif change < -2:
            return 'bearish'
        return 'neutral'
