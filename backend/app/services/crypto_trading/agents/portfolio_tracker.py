"""
Portfolio Tracker Agent - Portföy takibi
Tüm trade geçmişini, P&L'i ve portföy performansını takip eder.
Açık pozisyonların anlık kâr/zarar hesaplaması yapar.
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
        self._open_positions: dict[str, dict] = {}  # coin → position info
        self._closed_trades: list[dict] = []
        self._total_invested: float = 0.0
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self._win_count: int = 0
        self._loss_count: int = 0
        self._latest_prices: dict = {}
        self._report_counter: int = 0

    @property
    def portfolio_stats(self) -> dict:
        total = self._win_count + self._loss_count
        win_rate = (self._win_count / total * 100) if total > 0 else 0
        total_pnl = self._realized_pnl + self._unrealized_pnl
        return {
            'total_trades': len(self._trades),
            'open_positions': len(self._open_positions),
            'closed_trades': len(self._closed_trades),
            'total_invested': round(self._total_invested, 2),
            'total_pnl': round(total_pnl, 2),
            'realized_pnl': round(self._realized_pnl, 2),
            'unrealized_pnl': round(self._unrealized_pnl, 2),
            'win_count': self._win_count,
            'loss_count': self._loss_count,
            'win_rate': round(win_rate, 1),
            'positions': {coin: {
                'side': p['side'],
                'entry_price': p['entry_price'],
                'current_price': p.get('current_price', p['entry_price']),
                'quantity': p['quantity'],
                'size_usdt': p['size_usdt'],
                'pnl': round(p.get('pnl', 0), 2),
                'pnl_pct': round(p.get('pnl_pct', 0), 2),
            } for coin, p in self._open_positions.items()},
            'trades': self._trades[-20:],
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'trade_executed':
                order = msg.get('order', {})
                signal = msg.get('signal', {})
                coin = order.get('coin', '')
                side = order.get('side', '')
                price = order.get('price', 0)
                quantity = order.get('quantity', 0)
                size_usdt = signal.get('position_size_usdt', 0)
                # Fallback: Signal size=0 ise gerçekten yürütülen qty*price'tan hesapla
                if not size_usdt and quantity and price:
                    size_usdt = quantity * price

                self._trades.append({
                    'coin': coin,
                    'side': side,
                    'quantity': quantity,
                    'price': price,
                    'size_usdt': size_usdt,
                    'status': order.get('status'),
                    'time': datetime.now(timezone.utc).isoformat(),
                    'sentiment_score': signal.get('sentiment_score'),
                })
                self._total_invested += size_usdt

                # Açık pozisyon kaydet
                self._open_positions[coin] = {
                    'side': side,
                    'entry_price': price,
                    'current_price': price,
                    'quantity': quantity,
                    'size_usdt': size_usdt,
                    'pnl': 0,
                    'pnl_pct': 0,
                    'opened_at': datetime.now(timezone.utc).isoformat(),
                }

            elif msg.get('type') == 'price_update':
                new_prices = msg.get('price_objects', {})
                if new_prices:
                    self._latest_prices.update(new_prices)

            elif msg.get('type') == 'position_closed':
                coin = msg.get('coin', '')
                pnl = msg.get('pnl', 0)
                if pnl > 0:
                    self._win_count += 1
                elif pnl < 0:
                    self._loss_count += 1
                self._realized_pnl += pnl

                # Closed trade'e taşı
                if coin in self._open_positions:
                    pos = self._open_positions.pop(coin)
                    pos['pnl'] = pnl
                    pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                    self._closed_trades.append(pos)

                await self.send('drawdown', {
                    'type': 'trade_result',
                    'pnl': pnl,
                    'coin': coin,
                })
                await self.send('daily_report', {
                    'type': 'position_closed',
                    'coin': coin,
                    'pnl': pnl,
                })

        # Açık pozisyonların PnL'ini güncelle
        self._update_unrealized_pnl()

        # Her 5 döngüde bir rapor
        self._report_counter += 1
        if self._report_counter % 5 == 0:
            total = self._win_count + self._loss_count
            win_rate = (self._win_count / total * 100) if total > 0 else 0
            total_pnl = self._realized_pnl + self._unrealized_pnl
            total_balance = self._total_invested + total_pnl

            portfolio_msg = {
                'type': 'portfolio_update',
                'total_balance': round(total_balance, 2),
                'total_pnl': round(total_pnl, 2),
                'realized_pnl': round(self._realized_pnl, 2),
                'unrealized_pnl': round(self._unrealized_pnl, 2),
                'total_invested': round(self._total_invested, 2),
                'open_positions': len(self._open_positions),
                'win_rate': round(win_rate, 1),
            }
            await self.send('drawdown', portfolio_msg)
            await self.send('balance_verify', portfolio_msg)
            await self.send('funding_cost', portfolio_msg)
            await self.send('daily_report', portfolio_msg)

            if self._trades:
                # Pozisyon detaylarıyla raporla
                positions_summary = []
                for coin, p in self._open_positions.items():
                    emoji = "🟢" if p.get('pnl', 0) >= 0 else "🔴"
                    positions_summary.append(
                        f"{emoji} {coin} {p['side']} "
                        f"entry=${p['entry_price']} now=${p.get('current_price', 0):.4f} "
                        f"PnL=${p.get('pnl', 0):+.2f} ({p.get('pnl_pct', 0):+.1f}%)"
                    )

                report_text = (
                    f"📈 PORTFÖY RAPORU\n"
                    f"Açık: {len(self._open_positions)} | Kapalı: {len(self._closed_trades)}\n"
                    f"Gerçekleşen PnL: ${self._realized_pnl:+.2f}\n"
                    f"Açık PnL: ${self._unrealized_pnl:+.2f}\n"
                    f"Toplam PnL: ${total_pnl:+.2f}\n"
                    f"Win Rate: %{win_rate:.0f}\n"
                )
                if positions_summary:
                    report_text += "\n".join(positions_summary[:5])

                await self.send('alert', {
                    'type': 'portfolio_report',
                    'report_text': report_text,
                    **self.portfolio_stats,
                })

                self.logger.info(
                    f"PORTFOY | Trades={len(self._trades)} "
                    f"Açık={len(self._open_positions)} "
                    f"PnL=${total_pnl:+.2f} "
                    f"(realized=${self._realized_pnl:+.2f} unrealized=${self._unrealized_pnl:+.2f}) "
                    f"WinRate={win_rate:.0f}%"
                )

    def _update_unrealized_pnl(self):
        """Açık pozisyonların anlık PnL'ini hesapla"""
        self._unrealized_pnl = 0

        for coin, pos in self._open_positions.items():
            # Güncel fiyatı bul
            price_data = self._latest_prices.get(coin)
            if price_data:
                if hasattr(price_data, 'price'):
                    current_price = price_data.price
                elif isinstance(price_data, dict):
                    current_price = price_data.get('price', pos['entry_price'])
                else:
                    current_price = pos['entry_price']
            else:
                current_price = pos['entry_price']

            pos['current_price'] = current_price

            entry = pos['entry_price']
            qty = pos['quantity']
            side = pos['side']

            if entry > 0 and qty > 0:
                if side == 'BUY':
                    pnl = (current_price - entry) * qty
                    pnl_pct = ((current_price - entry) / entry) * 100
                else:  # SELL
                    pnl = (entry - current_price) * qty
                    pnl_pct = ((entry - current_price) / entry) * 100
            else:
                pnl = 0
                pnl_pct = 0

            pos['pnl'] = round(pnl, 4)
            pos['pnl_pct'] = round(pnl_pct, 4)
            self._unrealized_pnl += pnl
