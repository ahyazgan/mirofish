"""
Bakiye Doğrulayıcı - Beklenen vs gerçek bakiyeyi karşılaştırır.
Yetkisiz işlem, API hatası veya bug tespiti.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent
from ..config import CryptoTradingConfig


class BalanceVerifyAgent(BaseAgent):
    """
    Görev: Hesaplanan bakiye ile gerçek bakiyeyi karşılaştır
    Girdi: Portfolio Tracker'dan beklenen bakiye, Binance API'den gerçek
    Çıktı: Uyumsuzluk uyarısı → Kill Switch, Alert

    Kontrol:
    - Her trade sonrası
    - Her 5 dakikada bir periyodik
    - %0.5+ fark = uyarı
    - %5+ fark = kill switch tetikle
    """

    WARN_DIFF_PCT = 0.5    # %0.5 fark → uyarı
    CRITICAL_DIFF_PCT = 5.0  # %5 fark → kill switch

    def __init__(self, interval: float = 300.0):  # 5 dakikada bir
        super().__init__('Bakiye Dogrulayici', interval=interval)
        self._expected_balance: float = 0
        self._actual_balance: float = 0
        self._last_check: datetime | None = None
        self._mismatch_count = 0
        self._check_history: list[dict] = []

    @property
    def balance_stats(self) -> dict:
        return {
            'expected': self._expected_balance,
            'actual': self._actual_balance,
            'diff_pct': self._calc_diff_pct(),
            'mismatch_count': self._mismatch_count,
            'last_check': self._last_check.isoformat() if self._last_check else None,
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'portfolio_update':
                self._expected_balance = msg.get('total_balance', 0)

            elif msg_type == 'actual_balance':
                self._actual_balance = msg.get('balance', 0)

            elif msg_type == 'trade_completed':
                # Trade sonrası bakiye kontrolü
                self._expected_balance = msg.get('expected_balance', self._expected_balance)

        # Periyodik kontrol
        await self._verify_balance()

    async def _verify_balance(self):
        """Bakiye doğrulama"""
        self._last_check = datetime.now(timezone.utc)

        # Simülasyon modunda bakiye doğrulama atla
        if CryptoTradingConfig.SIMULATION_MODE:
            return

        # Henüz veri yoksa
        if self._expected_balance <= 0 and self._actual_balance <= 0:
            return

        diff_pct = self._calc_diff_pct()

        check_result = {
            'time': self._last_check.isoformat(),
            'expected': round(self._expected_balance, 2),
            'actual': round(self._actual_balance, 2),
            'diff_pct': round(diff_pct, 4),
            'status': 'OK',
        }

        if abs(diff_pct) >= self.CRITICAL_DIFF_PCT:
            self._mismatch_count += 1
            check_result['status'] = 'CRITICAL'

            self.logger.warning(
                f"BAKIYE KRITIK | Beklenen=${self._expected_balance:.2f} "
                f"Gercek=${self._actual_balance:.2f} Fark={diff_pct:+.2f}%"
            )

            # Kill Switch tetikle
            await self.send('kill_switch', {
                'type': 'balance_mismatch',
                'expected': self._expected_balance,
                'actual': self._actual_balance,
                'diff_pct': round(diff_pct, 4),
            })

            await self.send('alert', {
                'type': 'balance_critical',
                'expected': round(self._expected_balance, 2),
                'actual': round(self._actual_balance, 2),
                'diff_pct': round(diff_pct, 2),
            })

        elif abs(diff_pct) >= self.WARN_DIFF_PCT:
            self._mismatch_count += 1
            check_result['status'] = 'WARNING'

            self.logger.info(
                f"BAKIYE UYARI | Beklenen=${self._expected_balance:.2f} "
                f"Gercek=${self._actual_balance:.2f} Fark={diff_pct:+.2f}%"
            )

            await self.send('alert', {
                'type': 'balance_warning',
                'expected': round(self._expected_balance, 2),
                'actual': round(self._actual_balance, 2),
                'diff_pct': round(diff_pct, 2),
            })

        self._check_history.append(check_result)
        if len(self._check_history) > 200:
            self._check_history = self._check_history[-200:]

    def _calc_diff_pct(self) -> float:
        """Fark yüzdesi hesapla"""
        if self._expected_balance <= 0:
            return 0
        return ((self._actual_balance - self._expected_balance) / self._expected_balance) * 100
