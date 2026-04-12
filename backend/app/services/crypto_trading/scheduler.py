"""
7/24 Otomasyon Scheduler
Haber tarama, sentiment analizi, sinyal üretimi ve trade execution'ı
otomatik olarak çalıştırır.
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

from .config import CryptoTradingConfig
from .signal_engine import SignalEngine, SignalAction, SignalStrength
from .trade_executor import TradeExecutor

logger = logging.getLogger('crypto_trading.scheduler')


class TradingScheduler:
    """
    7/24 çalışan ana otomasyon döngüsü.

    Döngü:
    1. Her NEWS_SCAN_INTERVAL saniyede haberleri tara
    2. Her SIGNAL_EVAL_INTERVAL saniyede sinyalleri değerlendir
    3. Uygun sinyalleri otomatik execute et
    4. Pozisyonları takip et
    """

    def __init__(self, auto_execute: bool = True):
        self.signal_engine = SignalEngine()
        self.trade_executor = TradeExecutor()
        self.auto_execute = auto_execute
        self._running = False
        self._stats = {
            'started_at': None,
            'total_scans': 0,
            'total_signals': 0,
            'total_trades': 0,
            'total_pnl': 0.0,
            'last_scan_at': None,
            'errors': 0,
        }
        self._pending_signals = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            'started_at': self._stats['started_at'].isoformat() if self._stats['started_at'] else None,
            'last_scan_at': self._stats['last_scan_at'].isoformat() if self._stats['last_scan_at'] else None,
            'is_running': self._running,
            'auto_execute': self.auto_execute,
            'pending_signals': len(self._pending_signals),
            'active_positions': len(self.trade_executor.get_active_positions()),
            'mode': 'TESTNET' if CryptoTradingConfig.BINANCE_TESTNET else 'MAINNET',
        }

    async def start(self):
        """Scheduler'ı başlat"""
        if self._running:
            logger.warning("Scheduler zaten çalışıyor")
            return

        self._running = True
        self._stats['started_at'] = datetime.now(timezone.utc)

        # Konfigürasyon kontrolü
        errors, warnings = CryptoTradingConfig.validate()
        if errors:
            logger.error(f"Konfigürasyon hataları: {errors}")
            self._running = False
            return

        for w in warnings:
            logger.warning(w)

        logger.info("=" * 60)
        logger.info("MiroFish Crypto Trading Scheduler başlatıldı")
        logger.info(f"  Mod: {'TESTNET' if CryptoTradingConfig.BINANCE_TESTNET else 'MAINNET'}")
        logger.info(f"  Auto Execute: {self.auto_execute}")
        logger.info(f"  Takip Edilen Coinler: {CryptoTradingConfig.TRACKED_COINS}")
        logger.info(f"  Haber Tarama Aralığı: {CryptoTradingConfig.NEWS_SCAN_INTERVAL}s")
        logger.info(f"  Sinyal Aralığı: {CryptoTradingConfig.SIGNAL_EVAL_INTERVAL}s")
        logger.info(f"  Max Pozisyon: {CryptoTradingConfig.MAX_POSITION_SIZE} USDT")
        logger.info(f"  Stop-Loss: %{CryptoTradingConfig.STOP_LOSS_PCT}")
        logger.info(f"  Take-Profit: %{CryptoTradingConfig.TAKE_PROFIT_PCT}")
        logger.info("=" * 60)

        # Ana döngüyü başlat
        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Scheduler iptal edildi")
        except Exception as e:
            logger.error(f"Scheduler hatası: {e}")
            self._stats['errors'] += 1
        finally:
            self._running = False
            logger.info("Scheduler durduruldu")

    async def stop(self):
        """Scheduler'ı durdur"""
        logger.info("Scheduler durduruluyor...")
        self._running = False

    async def _main_loop(self):
        """Ana çalışma döngüsü"""
        scan_interval = CryptoTradingConfig.NEWS_SCAN_INTERVAL
        eval_interval = CryptoTradingConfig.SIGNAL_EVAL_INTERVAL

        while self._running:
            try:
                cycle_start = datetime.now(timezone.utc)

                # 1. Haberleri tara ve sinyalleri üret
                logger.info(f"--- Tarama döngüsü başladı: {cycle_start.strftime('%H:%M:%S UTC')} ---")
                signals = await self.signal_engine.generate_signals()

                self._stats['total_scans'] += 1
                self._stats['last_scan_at'] = cycle_start
                self._stats['total_signals'] += len(signals)

                if signals:
                    logger.info(f"{len(signals)} yeni sinyal üretildi")
                    for sig in signals:
                        logger.info(f"  {sig.coin}: {sig.action.value} "
                                   f"(güç={sig.strength.value}, skor={sig.sentiment_score}, "
                                   f"güven={sig.confidence})")

                    # 2. Auto-execute modunda sinyalleri işle
                    if self.auto_execute:
                        await self._process_signals(signals)
                    else:
                        self._pending_signals.extend(signals)
                else:
                    logger.info("Bu döngüde sinyal üretilmedi")

                # 3. Mevcut pozisyonları kontrol et
                await self._check_positions()

            except Exception as e:
                logger.error(f"Döngü hatası: {e}")
                self._stats['errors'] += 1

            # Sonraki döngüyü bekle
            await asyncio.sleep(scan_interval)

    async def _process_signals(self, signals):
        """Sinyalleri değerlendir ve execute et"""
        for signal in signals:
            # Sadece STRONG ve MODERATE sinyalleri execute et
            if signal.strength == SignalStrength.WEAK:
                logger.info(f"Zayıf sinyal atlandı: {signal.coin} {signal.action.value}")
                continue

            # Aynı coin'de zaten aktif pozisyon var mı?
            active = self.trade_executor.get_active_positions()
            if signal.coin in active:
                logger.info(f"Zaten aktif pozisyon var: {signal.coin}, sinyal atlandı")
                continue

            # Execute et
            try:
                order = await self.trade_executor.execute_signal(signal)
                if order and order.status in ('FILLED', 'SIMULATED'):
                    self._stats['total_trades'] += 1
                    logger.info(f"Trade gerçekleştirildi: {order.coin} {order.side} "
                               f"qty={order.quantity} price={order.price}")
            except Exception as e:
                logger.error(f"Trade execution hatası: {e}")
                self._stats['errors'] += 1

    async def _check_positions(self):
        """Aktif pozisyonları kontrol et (SL/TP takibi)"""
        active = self.trade_executor.get_active_positions()
        if not active:
            return

        prices = await self.signal_engine.price_service.get_prices(
            list(active.keys()), force=True
        )

        for coin, position_dict in active.items():
            price_data = prices.get(coin)
            if not price_data:
                continue

            current_price = price_data.price
            entry_price = position_dict['price']
            side = position_dict['side']

            # P&L hesapla
            if side == 'BUY':
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100

            if abs(pnl_pct) > 1:
                logger.info(f"Pozisyon {coin}: entry={entry_price}, "
                           f"current={current_price}, PnL={pnl_pct:.2f}%")

    async def execute_pending(self, signal_id: Optional[str] = None):
        """Bekleyen sinyalleri manuel execute et"""
        if signal_id:
            signals = [s for s in self._pending_signals if s.id == signal_id]
        else:
            signals = self._pending_signals.copy()

        for signal in signals:
            order = await self.trade_executor.execute_signal(signal)
            if order:
                self._pending_signals.remove(signal)
                self._stats['total_trades'] += 1

    def get_pending_signals(self) -> list[dict]:
        return [s.to_dict() for s in self._pending_signals]

    def get_full_status(self) -> dict:
        """Tam durum raporu"""
        return {
            'scheduler': self.stats,
            'signal_history': self.signal_engine.get_signal_history(20),
            'order_history': self.trade_executor.get_order_history(20),
            'active_positions': self.trade_executor.get_active_positions(),
            'pending_signals': self.get_pending_signals(),
        }


# Global scheduler instance
_scheduler: Optional[TradingScheduler] = None
_scheduler_task: Optional[asyncio.Task] = None


def get_scheduler() -> TradingScheduler:
    """Global scheduler instance'ı getir veya oluştur"""
    global _scheduler
    if _scheduler is None:
        auto_exec = os.environ.get('CRYPTO_AUTO_EXECUTE', 'true').lower() == 'true'
        _scheduler = TradingScheduler(auto_execute=auto_exec)
    return _scheduler


async def start_scheduler():
    """Scheduler'ı background task olarak başlat"""
    global _scheduler_task
    scheduler = get_scheduler()
    if scheduler.is_running:
        return {'status': 'already_running', **scheduler.stats}

    _scheduler_task = asyncio.create_task(scheduler.start())
    # Kısa bekle ki başlasın
    await asyncio.sleep(0.5)
    return {'status': 'started', **scheduler.stats}


async def stop_scheduler():
    """Scheduler'ı durdur"""
    global _scheduler_task
    scheduler = get_scheduler()
    await scheduler.stop()
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
    return {'status': 'stopped', **scheduler.stats}
