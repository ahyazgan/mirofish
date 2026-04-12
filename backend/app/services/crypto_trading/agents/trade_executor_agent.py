"""
Trade Executor Agent - Emir yönetimi
Sinyalleri alır, Binance'e emir gönderir, sonuçları paylaşır.
"""

from .base_agent import BaseAgent
from ..trade_executor import TradeExecutor


class TradeExecutorAgent(BaseAgent):
    """
    Görev: Sinyalleri Binance emirlerine dönüştür
    Girdi: Signal Strategist'ten sinyaller
    Çıktı: Emir sonuçları → Risk Manager, Portfolio, Alert
    """

    def __init__(self, interval: float = 2.0):
        super().__init__('Emir Yurutucu', interval=interval)
        self.executor = TradeExecutor()
        self._executed_signals: set[str] = set()

    async def run_cycle(self):
        messages = await self.receive_all()
        if not messages:
            return

        for msg in messages:
            if msg.get('type') == 'new_signal':
                signal = msg.get('signal_object')
                if not signal:
                    continue

                # Zaten execute edilmiş mi?
                if signal.id in self._executed_signals:
                    continue

                # Risk Manager'dan red gelmiş mi kontrol et
                if msg.get('rejected'):
                    self.logger.info(f"Sinyal reddedildi (Risk Manager): {signal.coin}")
                    continue

                # Execute et
                self.logger.info(f"Emir gönderiliyor: {signal.coin} {signal.action.value} "
                               f"size={signal.position_size_usdt} USDT")

                order = await self.executor.execute_signal(signal)
                self._executed_signals.add(signal.id)

                if order:
                    # Risk Manager'a bildir
                    await self.send('risk_manager', {
                        'type': 'new_position',
                        'order': order.to_dict(),
                        'signal': signal.to_dict(),
                    })

                    # Portfolio'ya bildir
                    await self.send('portfolio', {
                        'type': 'trade_executed',
                        'order': order.to_dict(),
                        'signal': signal.to_dict(),
                    })

                    # Alert
                    await self.send('alert', {
                        'type': 'trade_executed',
                        'coin': order.coin,
                        'side': order.side,
                        'quantity': order.quantity,
                        'price': order.price,
                        'status': order.status,
                    })

            elif msg.get('type') == 'close_position':
                # Risk Manager'dan pozisyon kapatma emri
                coin = msg.get('coin')
                reason = msg.get('reason', 'unknown')
                self.logger.warning(f"Pozisyon kapatılıyor: {coin} (sebep: {reason})")

                if self.executor.is_configured:
                    await self.executor.cancel_all_orders(f"{coin}USDT")

                await self.send('alert', {
                    'type': 'position_closed',
                    'coin': coin,
                    'reason': reason,
                })
