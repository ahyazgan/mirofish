"""
Drawdown Yöneticisi - Portföy düşüşünü izler ve kontrol eder.
Günlük ve toplam drawdown limitlerini uygular. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class DrawdownAgent(BaseAgent):
    """
    Görev: Drawdown izle, limit aşımında müdahale et
    Girdi: Portfolio Tracker'dan bakiye, Trade Executor'dan PnL
    Çıktı: Uyarılar → Kill Switch, Risk Manager, Alert

    Limitler:
    - Günlük max drawdown: %3 (uyarı %2)
    - Toplam max drawdown: %10 (uyarı %7)
    - Streak: 5 üst üste zarar → pozisyon küçült
    - Recovery: Drawdown sonrası kademeli büyüme
    """

    # Drawdown limitleri
    DAILY_WARN_PCT = 2.0        # Günlük %2 → uyarı
    DAILY_MAX_PCT = 3.0         # Günlük %3 → durdur
    TOTAL_WARN_PCT = 7.0        # Toplam %7 → uyarı
    TOTAL_MAX_PCT = 10.0        # Toplam %10 → kill switch
    MAX_LOSING_STREAK = 5       # 5 üst üste zarar → pozisyon küçült

    # Recovery parametreleri
    RECOVERY_STEPS = [0.25, 0.50, 0.75, 1.0]  # Kademeli dönüş

    def __init__(self, interval: float = 10.0):
        super().__init__('Drawdown Yoneticisi', interval=interval)
        self._peak_balance: float = 0
        self._current_balance: float = 0
        self._daily_start_balance: float = 0
        self._current_date: str = ''
        self._losing_streak: int = 0
        self._recovery_mode: bool = False
        self._recovery_step: int = 0
        self._daily_pnl: float = 0
        self._drawdown_history: list[dict] = []
        self._stats = {
            'max_daily_dd': 0.0,
            'max_total_dd': 0.0,
            'daily_limit_hits': 0,
            'total_limit_hits': 0,
            'streak_reductions': 0,
        }

    @property
    def drawdown_stats(self) -> dict:
        daily_dd = self._calc_daily_drawdown()
        total_dd = self._calc_total_drawdown()
        return {
            **self._stats,
            'current_daily_dd': round(daily_dd, 2),
            'current_total_dd': round(total_dd, 2),
            'peak_balance': round(self._peak_balance, 2),
            'current_balance': round(self._current_balance, 2),
            'losing_streak': self._losing_streak,
            'recovery_mode': self._recovery_mode,
            'position_size_multiplier': self._get_size_multiplier(),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'portfolio_update':
                balance = msg.get('total_balance', 0)
                self._current_balance = balance

                # Peak güncelle
                if balance > self._peak_balance:
                    self._peak_balance = balance

                    # Recovery moddan çık
                    if self._recovery_mode:
                        self._recovery_step += 1
                        if self._recovery_step >= len(self.RECOVERY_STEPS):
                            self._recovery_mode = False
                            self._recovery_step = 0
                            self.logger.info("RECOVERY TAMAMLANDI | Normal trade boyutuna dönüldü")

            elif msg_type == 'trade_result':
                pnl = msg.get('pnl', 0)
                self._daily_pnl += pnl

                if pnl < 0:
                    self._losing_streak += 1
                else:
                    self._losing_streak = 0

            elif msg_type == 'daily_reset':
                self._daily_start_balance = self._current_balance
                self._daily_pnl = 0

        # Gün kontrolü
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')
        if self._current_date != today:
            if self._current_date:
                # Yeni gün → günlük sıfırla
                self._daily_start_balance = self._current_balance
                self._daily_pnl = 0
            self._current_date = today
            if self._daily_start_balance <= 0:
                self._daily_start_balance = self._current_balance

        # Drawdown kontrol
        await self._check_drawdown()

        # Losing streak kontrol
        await self._check_losing_streak()

    async def _check_drawdown(self):
        """Drawdown kontrolü"""
        if self._current_balance <= 0:
            return

        daily_dd = self._calc_daily_drawdown()
        total_dd = self._calc_total_drawdown()

        # İstatistik güncelle
        if daily_dd > self._stats['max_daily_dd']:
            self._stats['max_daily_dd'] = round(daily_dd, 2)
        if total_dd > self._stats['max_total_dd']:
            self._stats['max_total_dd'] = round(total_dd, 2)

        # Toplam drawdown → Kill Switch
        if total_dd >= self.TOTAL_MAX_PCT:
            self._stats['total_limit_hits'] += 1
            self.logger.warning(
                f"DRAWDOWN KRITIK | Toplam={total_dd:.1f}% (limit={self.TOTAL_MAX_PCT}%)"
            )

            await self.send('kill_switch', {
                'type': 'drawdown_exceeded',
                'drawdown_pct': round(total_dd, 2),
                'limit_pct': self.TOTAL_MAX_PCT,
                'peak_balance': round(self._peak_balance, 2),
                'current_balance': round(self._current_balance, 2),
            })

            await self.send('alert', {
                'type': 'drawdown_critical',
                'level': 'TOTAL',
                'drawdown_pct': round(total_dd, 2),
            })
            return

        # Toplam drawdown uyarı
        if total_dd >= self.TOTAL_WARN_PCT:
            self.logger.info(
                f"DRAWDOWN UYARI | Toplam={total_dd:.1f}% (limit={self.TOTAL_MAX_PCT}%)"
            )

            # Recovery moda geç
            if not self._recovery_mode:
                self._recovery_mode = True
                self._recovery_step = 0

            await self.send('risk_manager', {
                'type': 'drawdown_warning',
                'level': 'TOTAL',
                'drawdown_pct': round(total_dd, 2),
                'size_multiplier': self._get_size_multiplier(),
            })

            await self.send('alert', {
                'type': 'drawdown_warning',
                'level': 'TOTAL',
                'drawdown_pct': round(total_dd, 2),
            })

        # Günlük drawdown → Trade durdur
        if daily_dd >= self.DAILY_MAX_PCT:
            self._stats['daily_limit_hits'] += 1
            self.logger.warning(
                f"GUNLUK DRAWDOWN LIMIT | {daily_dd:.1f}% (limit={self.DAILY_MAX_PCT}%)"
            )

            await self.send('executor', {
                'type': 'pause_trading',
                'reason': f'Günlük drawdown limiti: {daily_dd:.1f}%',
                'duration_minutes': 60,
            })

            await self.send('risk_manager', {
                'type': 'drawdown_daily_limit',
                'drawdown_pct': round(daily_dd, 2),
            })

            await self.send('alert', {
                'type': 'drawdown_critical',
                'level': 'DAILY',
                'drawdown_pct': round(daily_dd, 2),
            })

        elif daily_dd >= self.DAILY_WARN_PCT:
            self.logger.info(
                f"GUNLUK DRAWDOWN UYARI | {daily_dd:.1f}% (limit={self.DAILY_MAX_PCT}%)"
            )

            await self.send('risk_manager', {
                'type': 'drawdown_warning',
                'level': 'DAILY',
                'drawdown_pct': round(daily_dd, 2),
                'size_multiplier': self._get_size_multiplier(),
            })

        # Geçmiş kaydet
        self._drawdown_history.append({
            'time': datetime.now(timezone.utc).isoformat(),
            'daily_dd': round(daily_dd, 2),
            'total_dd': round(total_dd, 2),
            'balance': round(self._current_balance, 2),
        })
        if len(self._drawdown_history) > 500:
            self._drawdown_history = self._drawdown_history[-500:]

    async def _check_losing_streak(self):
        """Üst üste zarar kontrolü"""
        if self._losing_streak >= self.MAX_LOSING_STREAK:
            self._stats['streak_reductions'] += 1

            if not self._recovery_mode:
                self._recovery_mode = True
                self._recovery_step = 0

            self.logger.warning(
                f"KAYIP SERISI | {self._losing_streak} üst üste zarar → "
                f"pozisyon boyutu x{self._get_size_multiplier():.2f}"
            )

            await self.send('risk_manager', {
                'type': 'losing_streak',
                'streak': self._losing_streak,
                'size_multiplier': self._get_size_multiplier(),
            })

            await self.send('alert', {
                'type': 'losing_streak',
                'streak': self._losing_streak,
            })

    def _calc_daily_drawdown(self) -> float:
        """Günlük drawdown yüzdesi"""
        if self._daily_start_balance <= 0:
            return 0
        dd = (self._daily_start_balance - self._current_balance) / self._daily_start_balance * 100
        return max(dd, 0)

    def _calc_total_drawdown(self) -> float:
        """Toplam drawdown yüzdesi (peak'ten)"""
        if self._peak_balance <= 0:
            return 0
        dd = (self._peak_balance - self._current_balance) / self._peak_balance * 100
        return max(dd, 0)

    def _get_size_multiplier(self) -> float:
        """Recovery modda pozisyon boyutu çarpanı"""
        if not self._recovery_mode:
            return 1.0

        step = min(self._recovery_step, len(self.RECOVERY_STEPS) - 1)
        return self.RECOVERY_STEPS[step]
