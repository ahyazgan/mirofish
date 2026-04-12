"""
Kademeli Kâr Alıcı - Pozisyondan kademeli olarak kâr alır.
TP1/TP2/TP3 seviyeleri ile kârı maximize eder.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class GradualProfitAgent(BaseAgent):
    """
    Görev: Açık pozisyonlardan kademeli kâr al
    Girdi: Risk Manager'dan pozisyonlar, Price Tracker'dan fiyatlar
    Çıktı: Kısmi satış emirleri → Executor

    Strateji:
    - TP1: Pozisyonun %30'u → 1:1 R:R'da (risk kadar kâr)
    - TP2: Pozisyonun %30'u → 1:2 R:R'da (risk x2 kâr)
    - TP3: Pozisyonun %40'u → Trailing stop ile (kârı koştur)
    """

    # Kademeli kâr alma planı
    PROFIT_PLAN = [
        {'name': 'TP1', 'portion': 0.30, 'rr_ratio': 1.0},   # %30 → 1:1
        {'name': 'TP2', 'portion': 0.30, 'rr_ratio': 2.0},   # %30 → 1:2
        {'name': 'TP3', 'portion': 0.40, 'rr_ratio': 0},      # %40 → trailing
    ]

    def __init__(self, interval: float = 5.0):
        super().__init__('Kademeli Kar Alici', interval=interval)
        self._position_plans: dict[str, dict] = {}  # coin → profit plan
        self._profit_taken: list[dict] = []

    @property
    def profit_stats(self) -> dict:
        return {
            'active_plans': len(self._position_plans),
            'total_profits_taken': len(self._profit_taken),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'position_opened':
                coin = msg.get('coin', '')
                entry = msg.get('entry_price', 0)
                stop_loss = msg.get('stop_loss', 0)
                side = msg.get('side', 'BUY')
                quantity = msg.get('quantity', 0)

                if entry > 0 and stop_loss > 0:
                    risk = abs(entry - stop_loss)
                    self._position_plans[coin] = {
                        'entry': entry,
                        'stop_loss': stop_loss,
                        'side': side,
                        'risk': risk,
                        'total_quantity': quantity,
                        'remaining_quantity': quantity,
                        'tp_hit': [],  # Hangi TP'ler vuruldu
                    }

            elif msg_type == 'position_closed':
                coin = msg.get('coin', '')
                self._position_plans.pop(coin, None)

            elif msg_type == 'price_update':
                prices = msg.get('price_objects', {})
                for coin, data in prices.items():
                    if coin in self._position_plans:
                        await self._check_profit_targets(coin, data.price)

    async def _check_profit_targets(self, coin: str, current_price: float):
        """Kâr hedeflerini kontrol et"""
        plan = self._position_plans.get(coin)
        if not plan or current_price <= 0:
            return

        entry = plan['entry']
        risk = plan['risk']
        side = plan['side']

        for i, tp in enumerate(self.PROFIT_PLAN):
            tp_name = tp['name']

            # Bu TP zaten vuruldu mu?
            if tp_name in plan['tp_hit']:
                continue

            # TP3 = trailing, ayrı yönetiliyor (Smart Stop Agent)
            if tp['rr_ratio'] == 0:
                continue

            # TP seviyesi hesapla
            if side == 'BUY':
                tp_price = entry + (risk * tp['rr_ratio'])
                hit = current_price >= tp_price
            else:
                tp_price = entry - (risk * tp['rr_ratio'])
                hit = current_price <= tp_price

            if hit:
                plan['tp_hit'].append(tp_name)
                sell_portion = tp['portion']
                sell_quantity = plan['total_quantity'] * sell_portion

                if sell_quantity <= 0:
                    continue

                plan['remaining_quantity'] -= sell_quantity

                # Kısmi satış emri gönder
                await self.send('executor', {
                    'type': 'partial_close',
                    'coin': coin,
                    'quantity': round(sell_quantity, 8),
                    'side': 'SELL' if side == 'BUY' else 'BUY',
                    'reason': f'{tp_name} hedefi vuruldu (R:R={tp["rr_ratio"]})',
                    'tp_level': tp_name,
                })

                pnl_pct = ((current_price - entry) / entry * 100) if side == 'BUY' else ((entry - current_price) / entry * 100)

                self._profit_taken.append({
                    'coin': coin,
                    'tp': tp_name,
                    'price': current_price,
                    'quantity': sell_quantity,
                    'pnl_pct': round(pnl_pct, 2),
                    'time': datetime.now(timezone.utc).isoformat(),
                })

                # Son 200 tut
                if len(self._profit_taken) > 200:
                    self._profit_taken = self._profit_taken[-200:]

                await self.send('alert', {
                    'type': 'profit_taken',
                    'coin': coin,
                    'tp_level': tp_name,
                    'price': current_price,
                    'pnl_pct': round(pnl_pct, 2),
                    'portion': f'{sell_portion:.0%}',
                    'remaining': f'{plan["remaining_quantity"]:.8f}',
                })

                self.logger.info(
                    f"KAR ALINDI | {coin} {tp_name} "
                    f"fiyat=${current_price:.4f} PnL={pnl_pct:.1f}% "
                    f"miktar={sell_quantity:.8f} ({sell_portion:.0%})"
                )
