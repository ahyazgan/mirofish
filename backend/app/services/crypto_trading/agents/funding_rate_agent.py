"""
Funding Rate Agent - Binance Futures fonlama oranı izleme
Aşırı long/short pozisyon tespiti.
Binance public API - ücretsiz, auth gerekmez.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class FundingRateAgent(BaseAgent):
    """
    Görev: Perpetual futures funding rate'lerini izle
    Girdi: Binance Futures API (public, ücretsiz)
    Çıktı: Funding rate sinyalleri → Strategist, Alert

    Mantık:
    - Funding rate > +0.1% → Piyasa aşırı long → Düşüş beklenir
    - Funding rate < -0.1% → Piyasa aşırı short → Yükseliş beklenir
    """

    BINANCE_FUTURES_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'

    def __init__(self, interval: float = 300.0):  # 5 dakikada bir
        super().__init__('Fonlama Orani Izleyici', interval=interval)
        self._funding_rates: dict[str, list[dict]] = {}
        self._extreme_threshold = 0.001  # %0.1

    @property
    def funding_stats(self) -> dict:
        extreme_long = []
        extreme_short = []
        for coin, rates in self._funding_rates.items():
            if not rates:
                continue
            latest = rates[-1]['rate']
            if latest > self._extreme_threshold:
                extreme_long.append({'coin': coin, 'rate': latest})
            elif latest < -self._extreme_threshold:
                extreme_short.append({'coin': coin, 'rate': latest})

        return {
            'tracked_coins': len(self._funding_rates),
            'extreme_long': extreme_long,
            'extreme_short': extreme_short,
        }

    async def run_cycle(self):
        # Inbox mesajlarını oku (kullanılmasa bile temizle)
        await self.receive_all()

        funding_data = await self._fetch_funding_rates()
        if not funding_data:
            return

        signals = []

        for item in funding_data:
            symbol = item.get('symbol', '')
            if not symbol.endswith('USDT'):
                continue
            coin = symbol.replace('USDT', '')

            rate = float(item.get('lastFundingRate', 0))
            mark_price = float(item.get('markPrice', 0))

            if coin not in self._funding_rates:
                self._funding_rates[coin] = []
            self._funding_rates[coin].append({
                'rate': rate,
                'price': mark_price,
                'time': datetime.now(timezone.utc).isoformat(),
            })
            # Son 50 kayıt tut
            if len(self._funding_rates[coin]) > 50:
                self._funding_rates[coin] = self._funding_rates[coin][-50:]

            # Aşırı funding rate tespiti
            if abs(rate) > self._extreme_threshold:
                direction = 'extreme_long' if rate > 0 else 'extreme_short'
                # Aşırı long → bearish, Aşırı short → bullish (contrarian)
                signal_score = -0.2 if rate > 0 else 0.2

                # Çok aşırıysa sinyal gücünü artır
                if abs(rate) > 0.003:  # %0.3+
                    signal_score *= 2

                signals.append({
                    'coin': coin,
                    'funding_rate': round(rate * 100, 4),  # % olarak
                    'direction': direction,
                    'mark_price': mark_price,
                    'signal_score': signal_score,
                    'source': 'funding_rate',
                    'reason': f'Funding rate {rate*100:.4f}% ({direction})',
                })

        if signals:
            # En güçlü sinyalleri gönder (en aşırı funding rate'ler)
            signals.sort(key=lambda x: abs(x['signal_score']), reverse=True)
            top_signals = signals[:10]

            await self.send('strategist', {
                'type': 'funding_rate_signals',
                'signals': top_signals,
            })
            await self.send('alert', {
                'type': 'funding_rate_alert',
                'count': len(top_signals),
                'signals': top_signals,
            })

            for s in top_signals[:3]:
                self.logger.info(
                    f"FUNDING | {s['coin']} rate={s['funding_rate']}% "
                    f"({s['direction']}) score={s['signal_score']}"
                )

    async def _fetch_funding_rates(self) -> list[dict]:
        """Binance Futures'dan tüm funding rate'leri çek"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.BINANCE_FUTURES_URL)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            self.logger.error(f"Funding rate çekme hatası: {e}")
        return []
