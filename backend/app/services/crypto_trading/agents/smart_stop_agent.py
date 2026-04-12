"""
Akıllı Stop Ayarlayıcı - Dinamik stop-loss seviyeleri belirler.
ATR bazlı, trailing, zaman bazlı stop yönetimi.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .base_agent import BaseAgent


class SmartStopAgent(BaseAgent):
    """
    Görev: Açık pozisyonlar için dinamik stop-loss ayarla
    Girdi: Risk Manager'dan pozisyonlar, Volatility Agent'tan ATR
    Çıktı: Stop güncellemeleri → Risk Manager, Executor

    Stop Türleri:
    - ATR Stop: Volatiliteye göre otomatik (2x ATR mesafe)
    - Trailing Stop: Kâr arttıkça stop yukarı çekilir
    - Zaman Stop: X dakika kârda değilse kapat
    - Breakeven Stop: Belirli kâr sonrası stop'u girişe çek
    """

    ATR_MULTIPLIER = 2.0        # Stop mesafesi = 2x ATR
    TRAILING_START_PCT = 1.5    # %1.5 kârdan sonra trailing başla
    TRAILING_DISTANCE_PCT = 0.8  # Trailing mesafesi %0.8
    TIME_STOP_MINUTES = 60      # 60dk kârda değilse kapat
    BREAKEVEN_PCT = 1.0         # %1 kârda stop'u breakeven'a çek

    def __init__(self, interval: float = 10.0):
        super().__init__('Akilli Stop Ayarlayici', interval=interval)
        self._position_data: dict[str, dict] = {}  # coin → position info
        self._volatility_data: dict[str, float] = {}  # coin → ATR %
        self._stop_updates: list[dict] = []

    @property
    def stop_stats(self) -> dict:
        return {
            'tracked_positions': len(self._position_data),
            'total_updates': len(self._stop_updates),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'position_opened':
                coin = msg.get('coin', '')
                self._position_data[coin] = {
                    'entry_price': msg.get('entry_price', 0),
                    'side': msg.get('side', 'BUY'),
                    'current_stop': msg.get('stop_loss', 0),
                    'opened_at': datetime.now(timezone.utc),
                    'highest_pnl_pct': 0,
                    'trailing_active': False,
                    'breakeven_hit': False,
                }

            elif msg_type == 'position_closed':
                coin = msg.get('coin', '')
                self._position_data.pop(coin, None)

            elif msg_type == 'price_update':
                prices = msg.get('price_objects', {})
                for coin, data in prices.items():
                    if coin in self._position_data:
                        await self._update_stop(coin, data.price)

            elif msg_type == 'volatility_data':
                for signal in msg.get('signals', []):
                    coin = signal.get('coin', '')
                    atr_pct = signal.get('atr_pct', 0)
                    if coin and atr_pct:
                        self._volatility_data[coin] = atr_pct

    async def _update_stop(self, coin: str, current_price: float):
        """Pozisyon için stop güncelle"""
        pos = self._position_data.get(coin)
        if not pos or current_price <= 0:
            return

        entry_price = pos['entry_price']
        side = pos['side']
        current_stop = pos['current_stop']

        if entry_price <= 0:
            return

        # PnL hesapla
        if side == 'BUY':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # En yüksek PnL güncelle
        if pnl_pct > pos['highest_pnl_pct']:
            pos['highest_pnl_pct'] = pnl_pct

        new_stop = current_stop
        stop_reason = ''

        # 1. ATR bazlı stop (ilk ayar)
        atr_pct = self._volatility_data.get(coin, 2.0)
        atr_stop_distance = atr_pct * self.ATR_MULTIPLIER / 100

        if side == 'BUY':
            atr_stop = current_price * (1 - atr_stop_distance)
        else:
            atr_stop = current_price * (1 + atr_stop_distance)

        # 2. Breakeven stop
        if not pos['breakeven_hit'] and pnl_pct >= self.BREAKEVEN_PCT:
            pos['breakeven_hit'] = True
            if side == 'BUY':
                breakeven_stop = entry_price * 1.001  # Küçük marj
                if breakeven_stop > new_stop:
                    new_stop = breakeven_stop
                    stop_reason = f'Breakeven ({pnl_pct:.1f}% kâr)'
            else:
                breakeven_stop = entry_price * 0.999
                if breakeven_stop < new_stop or new_stop == 0:
                    new_stop = breakeven_stop
                    stop_reason = f'Breakeven ({pnl_pct:.1f}% kâr)'

        # 3. Trailing stop
        if pnl_pct >= self.TRAILING_START_PCT:
            pos['trailing_active'] = True
            trailing_distance = current_price * (self.TRAILING_DISTANCE_PCT / 100)

            if side == 'BUY':
                trailing_stop = current_price - trailing_distance
                if trailing_stop > new_stop:
                    new_stop = trailing_stop
                    stop_reason = f'Trailing ({pnl_pct:.1f}% kâr, ATR={atr_pct:.1f}%)'
            else:
                trailing_stop = current_price + trailing_distance
                if new_stop == 0 or trailing_stop < new_stop:
                    new_stop = trailing_stop
                    stop_reason = f'Trailing ({pnl_pct:.1f}% kâr)'

        # 4. Zaman stop
        age_minutes = (datetime.now(timezone.utc) - pos['opened_at']).total_seconds() / 60
        if age_minutes > self.TIME_STOP_MINUTES and pnl_pct <= 0:
            new_stop = current_price  # Şu anki fiyattan kapat
            stop_reason = f'Zaman stop ({age_minutes:.0f}dk, PnL={pnl_pct:.1f}%)'

        # Stop değiştiyse güncelle
        if new_stop != current_stop and stop_reason:
            pos['current_stop'] = new_stop

            await self.send('risk_manager', {
                'type': 'update_stop',
                'coin': coin,
                'new_stop': round(new_stop, 8),
                'reason': stop_reason,
                'pnl_pct': round(pnl_pct, 2),
            })

            await self.send('executor', {
                'type': 'update_stop_order',
                'coin': coin,
                'new_stop': round(new_stop, 8),
                'side': 'SELL' if side == 'BUY' else 'BUY',
            })

            self._stop_updates.append({
                'coin': coin,
                'old_stop': round(current_stop, 8),
                'new_stop': round(new_stop, 8),
                'reason': stop_reason,
                'time': datetime.now(timezone.utc).isoformat(),
            })

            # Son 200 güncelleme tut
            if len(self._stop_updates) > 200:
                self._stop_updates = self._stop_updates[-200:]

            self.logger.info(
                f"STOP GUNCELLEME | {coin} ${current_stop:.4f} → ${new_stop:.4f} "
                f"({stop_reason})"
            )
