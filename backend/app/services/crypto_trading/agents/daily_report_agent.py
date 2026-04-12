"""
Günlük Rapor Üreticisi - Her gün sonu detaylı performans raporu.
Telegram'a otomatik gönderir. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone, timedelta

from .base_agent import BaseAgent


class DailyReportAgent(BaseAgent):
    """
    Görev: Günlük performans raporu oluştur ve Telegram'a gönder
    Girdi: Tüm ajanlardan istatistikler
    Çıktı: Günlük rapor → Telegram, Alert

    İçerik:
    - Toplam trade sayısı, win rate
    - Günlük PnL (USD ve %)
    - En iyi ve en kötü trade
    - Ajan performans kartı
    - Risk metrikleri
    """

    def __init__(self, interval: float = 60.0):  # Her dakika kontrol et
        super().__init__('Gunluk Rapor Ureticisi', interval=interval)
        self._last_report_date: str = ''
        self._daily_trades: list[dict] = []
        self._daily_signals: int = 0
        self._daily_pnl: float = 0
        self._report_history: list[dict] = []

    @property
    def report_stats(self) -> dict:
        return {
            'last_report': self._last_report_date,
            'total_reports': len(self._report_history),
            'today_trades': len(self._daily_trades),
            'today_pnl': round(self._daily_pnl, 2),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'trade_executed':
                self._daily_trades.append({
                    'coin': msg.get('coin', ''),
                    'side': msg.get('side', ''),
                    'price': msg.get('price', 0),
                    'quantity': msg.get('quantity', 0),
                    'pnl': msg.get('pnl', 0),
                    'time': datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == 'signal_generated':
                self._daily_signals += 1

            elif msg_type == 'position_closing':
                pnl = msg.get('pnl', 0)
                self._daily_pnl += pnl

        # Gün sonu kontrolü (UTC 00:00)
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')

        if self._last_report_date and self._last_report_date != today:
            # Yeni gün başladı → dünün raporunu gönder
            await self._generate_report(self._last_report_date)
            self._reset_daily()

        self._last_report_date = today

    async def _generate_report(self, date: str):
        """Günlük rapor oluştur"""
        total_trades = len(self._daily_trades)
        winning = sum(1 for t in self._daily_trades if t.get('pnl', 0) > 0)
        losing = sum(1 for t in self._daily_trades if t.get('pnl', 0) < 0)
        win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

        # En iyi / en kötü trade
        best_trade = max(self._daily_trades, key=lambda t: t.get('pnl', 0)) if self._daily_trades else {}
        worst_trade = min(self._daily_trades, key=lambda t: t.get('pnl', 0)) if self._daily_trades else {}

        report = {
            'date': date,
            'total_trades': total_trades,
            'winning_trades': winning,
            'losing_trades': losing,
            'win_rate': round(win_rate, 1),
            'daily_pnl': round(self._daily_pnl, 2),
            'total_signals': self._daily_signals,
            'best_trade': {
                'coin': best_trade.get('coin', 'N/A'),
                'pnl': best_trade.get('pnl', 0),
            },
            'worst_trade': {
                'coin': worst_trade.get('coin', 'N/A'),
                'pnl': worst_trade.get('pnl', 0),
            },
        }

        self._report_history.append(report)
        if len(self._report_history) > 90:
            self._report_history = self._report_history[-90:]

        # Telegram formatında mesaj
        pnl_emoji = "🟢" if self._daily_pnl >= 0 else "🔴"
        report_text = (
            f"📊 *GÜNLÜK RAPOR - {date}*\n\n"
            f"{pnl_emoji} PnL: ${self._daily_pnl:+.2f}\n"
            f"📈 Trade: {total_trades} (W:{winning}/L:{losing})\n"
            f"🎯 Win Rate: %{win_rate:.1f}\n"
            f"📡 Sinyal: {self._daily_signals}\n\n"
        )

        if best_trade:
            report_text += f"✅ En iyi: {best_trade.get('coin', 'N/A')} ${best_trade.get('pnl', 0):+.2f}\n"
        if worst_trade:
            report_text += f"❌ En kötü: {worst_trade.get('coin', 'N/A')} ${worst_trade.get('pnl', 0):+.2f}\n"

        # Telegram'a gönder
        await self.send('telegram', {
            'type': 'portfolio_report',
            'total_trades': total_trades,
            'total_pnl': round(self._daily_pnl, 2),
            'win_rate': round(win_rate, 1),
            'report_text': report_text,
        })

        await self.send('alert', {
            'type': 'daily_report',
            'report': report,
        })

        self.logger.info(
            f"GUNLUK RAPOR | {date} | PnL=${self._daily_pnl:+.2f} "
            f"Trades={total_trades} WinRate={win_rate:.1f}%"
        )

    def _reset_daily(self):
        """Günlük sayaçları sıfırla"""
        self._daily_trades.clear()
        self._daily_signals = 0
        self._daily_pnl = 0
