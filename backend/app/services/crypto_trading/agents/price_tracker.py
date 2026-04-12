"""
Price Tracker Agent - Sürekli fiyat takibi
Tüm coinlerin fiyatlarını gerçek zamanlı takip eder.
Risk Manager ve Signal Strategist'e fiyat verisi sağlar.
"""

from .base_agent import BaseAgent
from ..price_service import PriceService


class PriceTrackerAgent(BaseAgent):
    """
    Görev: Fiyatları sürekli güncel tut, ani hareketleri tespit et
    Çıktı: Fiyat verileri → Strategist, Risk Manager, Portfolio
    """

    def __init__(self, interval: float = 15.0):
        super().__init__('Fiyat Takipcisi', interval=interval)
        self.price_service = PriceService()
        self._prev_prices: dict[str, float] = {}

    async def run_cycle(self):
        prices = await self.price_service.get_prices(force=True)
        if not prices:
            return

        price_data = {}
        alerts = []

        for symbol, data in prices.items():
            price_data[symbol] = data

            # Ani fiyat hareketi tespiti
            prev = self._prev_prices.get(symbol)
            if prev and prev > 0:
                change_pct = ((data.price - prev) / prev) * 100
                if abs(change_pct) > 3:  # %3+ ani hareket
                    alerts.append({
                        'coin': symbol,
                        'change_pct': round(change_pct, 2),
                        'price': data.price,
                        'prev_price': prev,
                    })

            self._prev_prices[symbol] = data.price

        # Fiyat verisini paylaş
        price_msg = {
            'type': 'price_update',
            'prices': {k: v.to_dict() for k, v in price_data.items()},
            'price_objects': price_data,
        }
        await self.send('strategist', price_msg)
        await self.send('risk_manager', price_msg)
        await self.send('portfolio', price_msg)

        # Ani hareket varsa alert
        if alerts:
            for a in alerts:
                direction = "YUKARI" if a['change_pct'] > 0 else "ASAGI"
                self.logger.warning(f"ANI HAREKET: {a['coin']} %{a['change_pct']} {direction}")

            await self.send('alert', {
                'type': 'price_alert',
                'alerts': alerts,
            })
            # Strategist'e de haber ver - acil sinyal değerlendirmesi için
            await self.send('strategist', {
                'type': 'price_spike',
                'alerts': alerts,
            })
