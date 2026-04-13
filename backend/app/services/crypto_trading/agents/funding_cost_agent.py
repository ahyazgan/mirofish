"""
Fonlama Maliyeti Hesaplayıcı - Futures pozisyonlarının fonlama maliyetini hesaplar.
Yüksek fonlama oranında pozisyon kapatma önerisi. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class FundingCostAgent(BaseAgent):
    """
    Görev: Fonlama maliyetlerini takip et ve uyar
    Girdi: Funding Rate Agent'tan oranlar, Portfolio Tracker'dan pozisyonlar
    Çıktı: Maliyet uyarıları → Strategist, Risk Manager, Alert

    Mantık:
    - Açık pozisyonlar × fonlama oranı = maliyet
    - Günlük maliyet eşik: $5 (küçük hesap) / %0.1 (portföy)
    - Yüksek fonlama → pozisyon kapatma önerisi
    - Negatif fonlama → fırsat sinyali (short tarafında ödeme alırsın)
    """

    # Eşikler
    WARN_DAILY_COST_PCT = 0.05     # Günlük %0.05 maliyet → uyarı
    HIGH_DAILY_COST_PCT = 0.10     # Günlük %0.10 maliyet → kapatma önerisi
    OPPORTUNITY_RATE = -0.01       # -%0.01 fonlama → fırsat (ödeme alırsın)
    FUNDING_INTERVAL_HOURS = 8     # Fonlama her 8 saatte bir

    def __init__(self, interval: float = 30.0):
        super().__init__('Fonlama Maliyet Hesaplayici', interval=interval)
        self._funding_rates: dict[str, float] = {}  # coin → current rate
        self._open_positions: dict[str, dict] = {}   # coin → position info
        self._daily_costs: dict[str, float] = {}     # coin → accumulated cost
        self._total_daily_cost: float = 0
        self._portfolio_value: float = 0
        self._cost_history: list[dict] = []
        self._cost_stats = {
            'warnings': 0,
            'close_suggestions': 0,
            'opportunities_found': 0,
        }

    @property
    def funding_cost_stats(self) -> dict:
        return {
            **self._cost_stats,
            'total_daily_cost': round(self._total_daily_cost, 4),
            'active_positions': len(self._open_positions),
            'cost_pct': round(
                (self._total_daily_cost / self._portfolio_value * 100)
                if self._portfolio_value > 0 else 0, 4
            ),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'funding_rate_update':
                coin = msg.get('coin', '')
                rate = msg.get('rate', 0)
                self._funding_rates[coin] = rate

            elif msg_type == 'position_update':
                coin = msg.get('coin', '')
                if msg.get('quantity', 0) > 0:
                    self._open_positions[coin] = {
                        'side': msg.get('side', ''),
                        'quantity': msg.get('quantity', 0),
                        'entry_price': msg.get('entry_price', 0),
                        'notional': msg.get('notional', 0),
                    }
                else:
                    self._open_positions.pop(coin, None)
                    self._daily_costs.pop(coin, None)

            elif msg_type == 'portfolio_update':
                self._portfolio_value = msg.get('total_balance', 0)

            elif msg_type == 'position_closed':
                coin = msg.get('coin', '')
                self._open_positions.pop(coin, None)
                self._daily_costs.pop(coin, None)

        # Fonlama maliyetlerini hesapla
        await self._calculate_costs()

    async def _calculate_costs(self):
        """Her pozisyon için fonlama maliyeti hesapla"""
        if not self._open_positions:
            self._total_daily_cost = 0
            return

        self._total_daily_cost = 0

        for coin, pos in self._open_positions.items():
            rate = self._funding_rates.get(coin, 0)
            notional = pos.get('notional', 0)
            side = pos.get('side', '')

            if notional <= 0 or rate == 0:
                continue

            # Fonlama maliyeti: LONG pozisyon + rate ödüyor, SHORT pozisyon + rate alıyor
            if side == 'BUY':  # LONG
                cost_per_funding = notional * rate  # Pozitif rate = maliyet
            else:  # SHORT
                cost_per_funding = -notional * rate  # Pozitif rate = kazanç

            # Günlük maliyet (3 fonlama periyodu × 8 saat)
            daily_cost = cost_per_funding * (24 / self.FUNDING_INTERVAL_HOURS)
            self._daily_costs[coin] = daily_cost
            self._total_daily_cost += daily_cost

        # Portföy yüzdesi olarak günlük maliyet
        if self._portfolio_value > 0:
            cost_pct = abs(self._total_daily_cost) / self._portfolio_value * 100
        else:
            cost_pct = 0

        # Yüksek maliyet kontrolü
        if cost_pct >= self.HIGH_DAILY_COST_PCT:
            self._cost_stats['close_suggestions'] += 1

            # En maliyetli pozisyonu bul
            worst_coin = max(self._daily_costs, key=lambda c: abs(self._daily_costs[c]))
            worst_cost = self._daily_costs[worst_coin]

            self.logger.warning(
                f"FONLAMA YUKSEK | Günlük maliyet=${self._total_daily_cost:.4f} "
                f"(%{cost_pct:.3f}) En pahalı={worst_coin} ${worst_cost:.4f}"
            )

            await self.send('risk_manager', {
                'type': 'funding_cost_high',
                'daily_cost': round(self._total_daily_cost, 4),
                'cost_pct': round(cost_pct, 4),
                'worst_coin': worst_coin,
                'worst_cost': round(worst_cost, 4),
                'suggestion': 'close_or_reduce',
            })

            await self.send('strategist', {
                'type': 'funding_cost_signal',
                'coin': worst_coin,
                'signal': 'reduce',
                'daily_cost_pct': round(cost_pct, 4),
            })

            await self.send('alert', {
                'type': 'funding_cost_warning',
                'daily_cost': round(self._total_daily_cost, 4),
                'cost_pct': round(cost_pct, 4),
                'worst_coin': worst_coin,
            })

        elif cost_pct >= self.WARN_DAILY_COST_PCT:
            self._cost_stats['warnings'] += 1
            self.logger.info(
                f"FONLAMA UYARI | Günlük maliyet=${self._total_daily_cost:.4f} "
                f"(%{cost_pct:.3f})"
            )

        # Fırsat tespiti: negatif fonlama oranı olan coinler
        for coin, rate in self._funding_rates.items():
            if rate <= self.OPPORTUNITY_RATE and coin not in self._open_positions:
                self._cost_stats['opportunities_found'] += 1

                await self.send('strategist', {
                    'type': 'funding_cost_signal',
                    'coin': coin,
                    'signal': 'opportunity',
                    'funding_rate': round(rate, 6),
                    'estimated_daily_income_pct': round(abs(rate) * 3 * 100, 4),
                })

        # Maliyet geçmişi
        if self._total_daily_cost != 0:
            self._cost_history.append({
                'time': datetime.now(timezone.utc).isoformat(),
                'daily_cost': round(self._total_daily_cost, 4),
                'cost_pct': round(cost_pct, 4),
                'positions': len(self._open_positions),
            })
            if len(self._cost_history) > 300:
                self._cost_history = self._cost_history[-300:]
