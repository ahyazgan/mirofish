"""
Kill Switch - Acil durumda TÜM işlemleri durdurur.
Sistem güvenliğinin en kritik parçası.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class KillSwitchAgent(BaseAgent):
    """
    Görev: Acil durumda sistemi durdur, tüm pozisyonları kapat
    Girdi: Flash Crash, Drawdown Manager, API Monitor, manuel tetikleme
    Çıktı: Durdurma emirleri → TÜM ajanlar

    Tetikleme koşulları:
    - Flash crash tespiti (CRITICAL)
    - Drawdown limiti aşıldı
    - API hatası 3+ kez üst üste
    - Manuel tetikleme (Telegram /killswitch)
    - Bakiye uyumsuzluğu

    Aksiyonlar:
    1. Tüm açık emirleri iptal et
    2. Tüm pozisyonları kapat (market emir)
    3. Yeni emir girişini kilitle
    4. Telegram bildirimi gönder
    5. Durumu logla

    Yeniden başlatma: SADECE manuel onay ile
    """

    def __init__(self, interval: float = 2.0):
        super().__init__('Kill Switch', interval=interval)
        self._activated = False
        self._activation_time: datetime | None = None
        self._activation_reason = ''
        self._activation_history: list[dict] = []
        self._api_error_count = 0
        self._consecutive_errors = 0

    @property
    def kill_switch_stats(self) -> dict:
        return {
            'activated': self._activated,
            'activation_time': self._activation_time.isoformat() if self._activation_time else None,
            'reason': self._activation_reason,
            'total_activations': len(self._activation_history),
            'history': self._activation_history[-5:],
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            # Flash crash → CRITICAL
            if msg_type == 'flash_crash':
                await self._activate(
                    reason=f"Flash crash: {msg.get('coin', '?')} {msg.get('crash_info', {}).get('drop_pct', 0):.1f}% düşüş",
                    severity=msg.get('severity', 'CRITICAL'),
                )

            # Drawdown limiti
            elif msg_type == 'drawdown_exceeded':
                await self._activate(
                    reason=f"Drawdown limiti aşıldı: {msg.get('drawdown_pct', 0):.1f}%",
                    severity='HIGH',
                )

            # API hatası
            elif msg_type == 'api_critical_error':
                self._consecutive_errors += 1
                if self._consecutive_errors >= 3:
                    await self._activate(
                        reason=f"API hatası {self._consecutive_errors}x üst üste",
                        severity='HIGH',
                    )

            elif msg_type == 'api_ok':
                self._consecutive_errors = 0

            # Bakiye uyumsuzluğu
            elif msg_type == 'balance_mismatch':
                diff_pct = msg.get('diff_pct', 0)
                if abs(diff_pct) > 5:  # %5+ fark
                    await self._activate(
                        reason=f"Bakiye uyumsuzluğu: {diff_pct:.1f}% fark",
                        severity='CRITICAL',
                    )

            # Manuel tetikleme (Telegram'dan)
            elif msg_type == 'manual_kill':
                await self._activate(
                    reason=f"Manuel tetikleme: {msg.get('user', 'unknown')}",
                    severity='MANUAL',
                )

            # Manuel yeniden başlatma
            elif msg_type == 'manual_restart':
                if self._activated:
                    self._activated = False
                    self._activation_reason = ''
                    self.logger.info("KILL SWITCH deaktif edildi (manuel onay)")
                    await self.send('alert', {
                        'type': 'kill_switch_deactivated',
                        'message': 'Kill Switch deaktif edildi, sistem yeniden çalışıyor',
                    })
                    await self.send('executor', {
                        'type': 'resume_trading',
                        'reason': 'Kill Switch deaktif',
                    })

    async def _activate(self, reason: str, severity: str):
        """Kill Switch'i aktifle"""
        if self._activated:
            self.logger.warning(f"Kill Switch zaten aktif, yeni tetikleme: {reason}")
            return

        self._activated = True
        self._activation_time = datetime.now(timezone.utc)
        self._activation_reason = reason

        self._activation_history.append({
            'time': self._activation_time.isoformat(),
            'reason': reason,
            'severity': severity,
        })

        self.logger.warning(f"{'='*60}")
        self.logger.warning(f"  KILL SWITCH AKTIF!")
        self.logger.warning(f"  Sebep: {reason}")
        self.logger.warning(f"  Seviye: {severity}")
        self.logger.warning(f"  Zaman: {self._activation_time.isoformat()}")
        self.logger.warning(f"{'='*60}")

        # 1. Tüm emirleri iptal et
        await self.send('executor', {
            'type': 'cancel_all_orders',
            'reason': f'Kill Switch: {reason}',
        })

        # 2. Tüm pozisyonları kapat
        await self.send('executor', {
            'type': 'close_all_positions',
            'reason': f'Kill Switch: {reason}',
            'order_type': 'MARKET',
        })

        # 3. Yeni emir girişini kilitle
        await self.send('executor', {
            'type': 'lock_trading',
            'reason': f'Kill Switch: {reason}',
        })

        # 4. Diğer ajanları bilgilendir
        await self.send('risk_manager', {
            'type': 'kill_switch_activated',
            'reason': reason,
        })

        # 5. Alert ve Telegram'a bildir
        await self.send('alert', {
            'type': 'kill_switch_activated',
            'reason': reason,
            'severity': severity,
            'time': self._activation_time.isoformat(),
        })
