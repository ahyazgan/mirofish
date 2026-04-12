"""
Portfolio Tracker Agent - Portföy takibi
Tüm trade geçmişini, P&L'i ve portföy performansını takip eder.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class PortfolioTrackerAgent(BaseAgent):
    """
    Görev: Portföy durumunu, P&L'i ve trade geçmişini takip et
    Girdi: Executor'dan trade sonuçları, Price Tracker'dan fiyatlar
    Çıktı: Periyodik portföy raporu → Alert'e
    """

    def __init__(self, interval: float = 30.0):
        super().__init__('Portfoy Takipcisi', interval=interval)
        self._trades: list[dict] = []
        self._total_invested: float = 0.0
        self._total_pnl: float = 0.0
        self._win_count: int = 0
        self._loss_count: int = 0
        self._latest_prices: dict = {}
        self._report_counter: int = 0

    @property
    def portfolio_stats(self) -> dict:
        total = self._win_count + self._loss_count
        win_rate = (self._win_count / total * 100) if total > 0 else 0
        return {
            'total_trades': len(self._trades),
            'total_invested': round(self._total_invested, 2),
            'total_pnl': round(self._total_pnl, 2),
            'win_count': self._win_count,
            'loss_count': self._loss_count,
            'win_rate': round(win_rate, 1),
            'trades': self._trades[-20:],
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'trade_executed':
                order = msg.get('order', {})
                signal = msg.get('signal', {})
                self._trades.append({
                    'coin': order.get('coin'),
                    'side': order.get('side'),
                    'quantity': order.get('quantity'),
                    'price': order.get('price'),
                    'size_usdt': signal.get('position_size_usdt'),
                    'status': order.get('status'),
                    'time': datetime.now(timezone.utc).isoformat(),
                    'sentiment_score': signal.get('sentiment_score'),
                })
                size = signal.get('position_size_usdt', 0)
                self._total_invested += size

            elif msg.get('type') == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

            elif msg.get('type') == 'position_closed':
                coin = msg.get('coin', '')
                pnl = msg.get('pnl', 0)
                if pnl > 0:
                    self._win_count += 1
                elif pnl < 0:
                    self._loss_count += 1
                self._total_pnl += pnl

                # Drawdown'a trade sonucu bildir
                await self.send('drawdown', {
                    'type': 'trade_result',
                    'pnl': pnl,
                    'coin': coin,
                })

                # Daily Report'a bildir
                await self.send('daily_report', {
                    'type': 'position_closing',
                    'coin': coin,
                    'pnl': pnl,
                })

        # Her 5 döngüde bir rapor ve downstream mesajlar
        self._report_counter += 1
        if self._report_counter % 5 == 0:
            total = self._win_count + self._loss_count
            win_rate = (self._win_count / total * 100) if total > 0 else 0
            total_balance = self._total_invested + self._total_pnl

            # Downstream ajanlara portfolio_update gönder
            portfolio_msg = {
                'type': 'portfolio_update',
                'total_balance': round(total_balance, 2),
                'total_pnl': round(self._total_pnl, 2),
                'total_invested': round(self._total_invested, 2),
                'open_positions': len(self._trades),
                'win_rate': round(win_rate, 1),
            }
            await self.send('drawdown', portfolio_msg)
            await self.send('balance_verify', portfolio_msg)
            await self.send('funding_cost', portfolio_msg)
            await self.send('daily_report', portfolio_msg)

            if self._trades:
                await self.send('alert', {
                    'type': 'portfolio_report',
                    **self.portfolio_stats,
                })
