"""
Trade Executor Agent - Emir yönetimi
Sinyalleri alır, Binance'e emir gönderir, sonuçları paylaşır.
"""

import asyncio

from .base_agent import BaseAgent
from ..trade_executor import TradeExecutor
from ..signal_engine import SignalAction, TradingSignal


class TradeExecutorAgent(BaseAgent):
    """
    Görev: Sinyalleri Binance emirlerine dönüştür
    Girdi: Conflict Resolver, Kill Switch, Flash Crash, Drawdown, Position Speed,
           Slippage, Smart Stop, Gradual Profit, Risk Manager
    Çıktı: Emir sonuçları → Risk Manager, Portfolio, Alert, Daily Report
    """

    def __init__(self, interval: float = 2.0):
        super().__init__('Emir Yurutucu', interval=interval)
        self.executor = TradeExecutor()
        self._executed_signals: set[str] = set()
        self._trading_paused = False
        self._trading_locked = False
        self._pause_task: asyncio.Task | None = None

    async def run_cycle(self):
        messages = await self.receive_all()
        if not messages:
            return

        for msg in messages:
            msg_type = msg.get('type', '')

            # === SINYAL EXECUTION ===
            if msg_type == 'new_signal':
                await self._handle_new_signal(msg)

            elif msg_type == 'execute_signal':
                await self._handle_execute_signal(msg)

            # === KONTROL KOMUTLARI ===
            elif msg_type == 'pause_trading':
                duration = msg.get('duration_minutes', 0)
                reason = msg.get('reason', 'unknown')
                self._trading_paused = True
                self.logger.warning(f"TRADING DURAKLATILDI | sebep={reason}")

                # Süre varsa otomatik resume
                if duration > 0:
                    if self._pause_task and not self._pause_task.done():
                        self._pause_task.cancel()
                    self._pause_task = asyncio.create_task(
                        self._auto_resume(duration * 60)
                    )

            elif msg_type == 'resume_trading':
                self._trading_paused = False
                self._trading_locked = False
                self.logger.info(f"TRADING DEVAM | sebep={msg.get('reason', '')}")

            elif msg_type == 'lock_trading':
                self._trading_locked = True
                self.logger.warning(
                    f"TRADING KILITLENDI | sebep={msg.get('reason', '')} "
                    f"(sadece manuel restart ile acilir)"
                )

            # === KILL SWITCH KOMUTLARI ===
            elif msg_type == 'cancel_all_orders':
                await self._handle_cancel_all(msg)

            elif msg_type == 'close_all_positions':
                await self._handle_close_all(msg)

            # === POZİSYON YÖNETİMİ ===
            elif msg_type == 'close_position':
                await self._handle_close_position(msg)

            elif msg_type == 'partial_close':
                await self._handle_partial_close(msg)

            elif msg_type == 'update_stop_order':
                await self._handle_update_stop(msg)

            # === STRATEJİK EMİR ===
            elif msg_type == 'execute_with_strategy':
                await self._handle_strategy_execute(msg)

            elif msg_type == 'slippage_estimate':
                await self._handle_slippage_estimate(msg)

    # ── Sinyal Handler'ları ──────────────────────────────

    async def _handle_new_signal(self, msg: dict):
        """Strategist'ten gelen klasik sinyal"""
        signal = msg.get('signal_object')
        if not signal:
            return

        if signal.id in self._executed_signals:
            return

        if not self._can_trade('new_signal'):
            return

        if msg.get('rejected'):
            self.logger.info(f"Sinyal reddedildi (Risk Manager): {signal.coin}")
            return

        await self._execute_and_notify(signal)

    async def _handle_execute_signal(self, msg: dict):
        """Conflict Resolver'dan gelen onaylanmış sinyal"""
        signal = msg.get('signal_object')
        if not signal:
            # signal_object yoksa signal dict'ten bilgi al
            signal_dict = msg.get('signal', {})
            if not signal_dict:
                return
            try:
                signal = TradingSignal(
                    id=signal_dict.get('id', f"CR-{self.stats['cycles']}"),
                    coin=signal_dict.get('coin', msg.get('coin', '')),
                    action=SignalAction.BUY if msg.get('side', signal_dict.get('action', '')) == 'BUY' else SignalAction.SELL,
                    strength=signal_dict.get('strength', 'MODERATE'),
                    entry_price=signal_dict.get('entry_price', 0),
                    stop_loss=signal_dict.get('stop_loss', 0),
                    take_profit=signal_dict.get('take_profit', 0),
                    position_size_usdt=msg.get('size_usdt', signal_dict.get('position_size_usdt', 0)),
                    sentiment_score=signal_dict.get('sentiment_score', 0),
                    confidence=msg.get('confidence', signal_dict.get('confidence', 0)),
                    reasons=signal_dict.get('reasons', []),
                )
            except Exception as e:
                self.logger.error(f"Signal parse hatası: {e}")
                return

        if signal.id in self._executed_signals:
            return

        if not self._can_trade('execute_signal'):
            return

        await self._execute_and_notify(signal)

    async def _execute_and_notify(self, signal):
        """Sinyali execute et ve tüm downstream ajanlara bildir"""
        self.logger.info(
            f"Emir gönderiliyor: {signal.coin} {signal.action.value} "
            f"size={signal.position_size_usdt} USDT"
        )

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

            # Daily Report'a bildir
            await self.send('daily_report', {
                'type': 'trade_executed',
                'coin': order.coin,
                'side': order.side,
                'price': order.price,
                'quantity': order.quantity,
            })

            # Slippage Agent'a bildir (gerçek fill bilgisi)
            await self.send('slippage', {
                'type': 'order_filled',
                'coin': signal.coin,
                'expected_price': signal.entry_price,
                'fill_price': order.price,
                'side': order.side,
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

    # ── Kill Switch Handler'ları ─────────────────────────

    async def _handle_cancel_all(self, msg: dict):
        """Tüm açık emirleri iptal et"""
        reason = msg.get('reason', 'kill_switch')
        self.logger.warning(f"TÜM EMİRLER İPTAL | sebep={reason}")

        if self.executor.is_configured:
            for coin in list(self.executor._active_positions.keys()):
                try:
                    await self.executor.cancel_all_orders(f"{coin}USDT")
                except Exception as e:
                    self.logger.error(f"Emir iptal hatası ({coin}): {e}")

        await self.send('alert', {
            'type': 'all_orders_cancelled',
            'reason': reason,
        })

    async def _handle_close_all(self, msg: dict):
        """Tüm pozisyonları market emriyle kapat"""
        reason = msg.get('reason', 'kill_switch')
        self.logger.warning(f"TÜM POZİSYONLAR KAPATILIYOR | sebep={reason}")

        positions = dict(self.executor._active_positions)
        for coin, position in positions.items():
            try:
                # Ters yönde market emri
                close_side = 'SELL' if position.side == 'BUY' else 'BUY'
                if self.executor.is_configured:
                    await self.executor._place_order(
                        symbol=f"{coin}USDT",
                        side=close_side,
                        order_type='MARKET',
                        quantity=position.quantity,
                    )
                # Pozisyonu temizle
                self.executor._active_positions.pop(coin, None)

                await self.send('risk_manager', {
                    'type': 'position_closed',
                    'coin': coin,
                    'reason': reason,
                })
                await self.send('portfolio', {
                    'type': 'position_closed',
                    'coin': coin,
                    'reason': reason,
                })
            except Exception as e:
                self.logger.error(f"Pozisyon kapatma hatası ({coin}): {e}")

        await self.send('alert', {
            'type': 'all_positions_closed',
            'reason': reason,
            'count': len(positions),
        })

    # ── Pozisyon Yönetimi Handler'ları ────���──────────────

    async def _handle_close_position(self, msg: dict):
        """Tek pozisyon kapatma (Risk Manager'dan)"""
        coin = msg.get('coin')
        reason = msg.get('reason', 'unknown')
        self.logger.warning(f"Pozisyon kapatılıyor: {coin} (sebep: {reason})")

        if self.executor.is_configured:
            await self.executor.cancel_all_orders(f"{coin}USDT")

        self.executor._active_positions.pop(coin, None)

        await self.send('portfolio', {
            'type': 'position_closed',
            'coin': coin,
            'reason': reason,
        })
        await self.send('alert', {
            'type': 'position_closed',
            'coin': coin,
            'reason': reason,
        })

    async def _handle_partial_close(self, msg: dict):
        """Kısmi pozisyon kapatma (Gradual Profit'ten)"""
        coin = msg.get('coin', '')
        quantity = msg.get('quantity', 0)
        tp_level = msg.get('tp_level', '?')
        reason = msg.get('reason', f'TP {tp_level}')

        if not coin or quantity <= 0:
            return

        if not self._can_trade('partial_close'):
            return

        self.logger.info(f"KISMI KAPATMA | {coin} qty={quantity} seviye={tp_level}")

        position = self.executor._active_positions.get(coin)
        if not position:
            return

        close_side = 'SELL' if position.side == 'BUY' else 'BUY'

        if self.executor.is_configured:
            try:
                await self.executor._place_order(
                    symbol=f"{coin}USDT",
                    side=close_side,
                    order_type='MARKET',
                    quantity=quantity,
                )
            except Exception as e:
                self.logger.error(f"Kısmi kapatma hatası ({coin}): {e}")
                return

        await self.send('portfolio', {
            'type': 'partial_close',
            'coin': coin,
            'quantity': quantity,
            'reason': reason,
        })
        await self.send('alert', {
            'type': 'partial_close',
            'coin': coin,
            'quantity': quantity,
            'tp_level': tp_level,
        })

    async def _handle_update_stop(self, msg: dict):
        """Stop-loss emrini güncelle (Smart Stop'tan)"""
        coin = msg.get('coin', '')
        new_stop = msg.get('new_stop_price', 0)
        reason = msg.get('reason', '')

        if not coin or new_stop <= 0:
            return

        position = self.executor._active_positions.get(coin)
        if not position:
            return

        self.logger.info(f"STOP GUNCELLEME | {coin} yeni_stop=${new_stop:.4f} sebep={reason}")

        if self.executor.is_configured and position.stop_loss_order_id:
            # Eski stop emrini iptal et
            try:
                await self.executor.cancel_all_orders(f"{coin}USDT")
            except Exception as e:
                self.logger.warning(f"Eski stop emri iptal edilemedi ({coin}): {e}")

            # Yeni stop emri koy
            close_side = 'SELL' if position.side == 'BUY' else 'BUY'
            sl_order = await self.executor._place_stop_loss(
                symbol=f"{coin}USDT",
                side=close_side,
                quantity=position.quantity,
                stop_price=new_stop,
            )
            if sl_order:
                position.stop_loss_order_id = str(sl_order.get('orderId', ''))

    # ── Stratejik Emir Handler'ları ──────────────────────

    async def _handle_strategy_execute(self, msg: dict):
        """Position Speed'den gelen strateji ile execute"""
        if not self._can_trade('strategy_execute'):
            return

        signal = msg.get('signal_object')
        if not signal:
            return

        # Strateji bilgileri
        strategy = msg.get('strategy', 'INSTANT')
        chunks = msg.get('chunks', [{'pct': 1.0, 'delay': 0}])

        self.logger.info(
            f"STRATEJIK EMIR | {signal.coin} strateji={strategy} "
            f"parcalar={len(chunks)}"
        )

        # İlk parçayı hemen execute et, geri kalanlar için task oluştur
        for i, chunk in enumerate(chunks):
            if i > 0:
                delay = chunk.get('delay', 5)
                await asyncio.sleep(delay)

            # Bu parça için büyüklük
            chunk_pct = chunk.get('pct', 1.0)
            original_size = signal.position_size_usdt
            signal.position_size_usdt = original_size * chunk_pct

            order = await self.executor.execute_signal(signal)
            signal.position_size_usdt = original_size  # Geri yükle

            if order:
                await self.send('portfolio', {
                    'type': 'trade_executed',
                    'order': order.to_dict(),
                    'signal': signal.to_dict(),
                })

        self._executed_signals.add(signal.id)

    async def _handle_slippage_estimate(self, msg: dict):
        """Slippage Agent'tan gelen tahmin sonucu"""
        coin = msg.get('coin', '')
        should_proceed = msg.get('should_proceed', True)
        recommendation = msg.get('recommendation', '')
        slippage_pct = msg.get('estimated_slippage_pct', 0)

        if not should_proceed:
            self.logger.warning(
                f"SLIPPAGE ENGEL | {coin} tahmini=%{slippage_pct:.2f} → emir iptal"
            )
            # Sinyali iptal et — hiçbir şey yapma
        elif 'LIMIT' in recommendation:
            self.logger.info(
                f"SLIPPAGE UYARI | {coin} → limit emir önerisi"
            )
            # Not: Limit emir stratejisi burada uygulanabilir

    # ── Yardımcı Metotlar ────────────────────────────────

    def _can_trade(self, action: str) -> bool:
        """Trading izni kontrolü"""
        if self._trading_locked:
            self.logger.warning(f"EMIR ENGEL | Trading kilitli, {action} reddedildi")
            return False
        if self._trading_paused:
            self.logger.info(f"EMIR BEKLET | Trading duraklatılmış, {action} reddedildi")
            return False
        return True

    async def _auto_resume(self, seconds: float):
        """Belirli süre sonra otomatik resume"""
        try:
            await asyncio.sleep(seconds)
            if self._trading_paused and not self._trading_locked:
                self._trading_paused = False
                self.logger.info(f"OTOMATIK DEVAM | {seconds/60:.0f}dk sonra trading devam")
        except asyncio.CancelledError:
            pass
