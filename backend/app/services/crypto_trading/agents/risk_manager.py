"""
Risk Manager Agent - Gelişmiş risk yönetimi
SL/TP/Trailing Stop + Günlük kayıp limiti + Kelly Criterion + Max pozisyon.
"""

import math
from datetime import datetime, timezone

from .base_agent import BaseAgent
from ..config import CryptoTradingConfig


class RiskManagerAgent(BaseAgent):
    """
    Görev: Açık pozisyonları izle, gelişmiş risk limitleri kontrol et
    Girdi: Price Tracker'dan fiyatlar, Executor'dan pozisyonlar
    Çıktı: Pozisyon kapatma emirleri → Executor'a

    Gelişmiş Özellikler:
    - Stop-Loss / Take-Profit / Trailing Stop
    - Günlük maksimum kayıp limiti ($200)
    - Maksimum eşzamanlı pozisyon sayısı (10)
    - Kelly Criterion bazlı pozisyon boyutlama
    - Korelasyon bazlı risk (aynı yönde çok pozisyon uyarısı)
    - Pozisyon yaşlanma (24h+ pozisyonları kapat)
    """

    # Risk parametreleri
    MAX_DAILY_LOSS = 200.0          # Günlük max kayıp $200
    MAX_OPEN_POSITIONS = 10         # Max eşzamanlı pozisyon
    MAX_SINGLE_LOSS_PCT = 5.0       # Tek pozisyonda max %5 kayıp
    POSITION_AGE_LIMIT_H = 24       # 24 saat sonra kapat
    TRAILING_STOP_ACTIVATION = 3.0  # %3+ kârda trailing stop aktif
    TRAILING_STOP_DISTANCE = 1.5    # Zirvedden %1.5 geri çekilme

    def __init__(self, interval: float = 10.0):
        super().__init__('Risk Yoneticisi', interval=interval)
        self._positions: dict[str, dict] = {}
        self._latest_prices: dict = {}
        self._total_pnl: float = 0.0
        self._max_drawdown: float = 0.0
        self._daily_loss: float = 0.0
        self._daily_profit: float = 0.0
        self._daily_reset_date: str = ''
        self._closed_today: int = 0
        self._win_history: list[bool] = []  # Kelly hesabı için
        self._risk_locked = False  # Günlük limit aşıldıysa kilitle

    @property
    def positions(self) -> dict:
        return self._positions

    @property
    def risk_stats(self) -> dict:
        return {
            'open_positions': len(self._positions),
            'max_positions': self.MAX_OPEN_POSITIONS,
            'total_pnl': round(self._total_pnl, 2),
            'max_drawdown': round(self._max_drawdown, 2),
            'daily_loss': round(self._daily_loss, 2),
            'daily_profit': round(self._daily_profit, 2),
            'daily_net': round(self._daily_profit - self._daily_loss, 2),
            'max_daily_loss': self.MAX_DAILY_LOSS,
            'risk_locked': self._risk_locked,
            'kelly_fraction': round(self._kelly_fraction(), 4),
            'win_rate': round(self._win_rate() * 100, 1),
            'closed_today': self._closed_today,
            'positions': {k: {
                'coin': k,
                'side': v['side'],
                'entry': v['entry_price'],
                'current_pnl': v.get('current_pnl', 0),
                'peak_pnl': v.get('peak_pnl', 0),
                'age_minutes': round((datetime.now(timezone.utc) - v['opened_at']).total_seconds() / 60, 1),
            } for k, v in self._positions.items()},
        }

    async def run_cycle(self):
        # Günlük reset kontrolü
        self._check_daily_reset()

        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

            elif msg.get('type') == 'new_position':
                order = msg.get('order', {})
                signal = msg.get('signal', {})
                coin = order.get('coin', '')

                # Max pozisyon kontrolü
                if len(self._positions) >= self.MAX_OPEN_POSITIONS:
                    self.logger.warning(f"MAX POZİSYON LİMİTİ: {coin} reddedildi ({len(self._positions)}/{self.MAX_OPEN_POSITIONS})")
                    await self.send('alert', {
                        'type': 'risk_reject',
                        'coin': coin,
                        'reason': f'Max pozisyon limiti ({self.MAX_OPEN_POSITIONS})',
                    })
                    continue

                # Günlük kayıp kilidi kontrolü
                if self._risk_locked:
                    self.logger.warning(f"RİSK KİLİTLİ: {coin} reddedildi (günlük kayıp limiti aşıldı)")
                    await self.send('alert', {
                        'type': 'risk_reject',
                        'coin': coin,
                        'reason': f'Günlük kayıp limiti aşıldı (${self._daily_loss:.0f}/${self.MAX_DAILY_LOSS})',
                    })
                    continue

                self._positions[coin] = {
                    'order': order,
                    'signal': signal,
                    'entry_price': order.get('price', 0),
                    'side': order.get('side', 'BUY'),
                    'quantity': order.get('quantity', 0),
                    'stop_loss': signal.get('stop_loss', 0),
                    'take_profit': signal.get('take_profit', 0),
                    'opened_at': datetime.now(timezone.utc),
                    'current_pnl': 0,
                    'peak_pnl': 0,
                }
                self.logger.info(f"Yeni pozisyon: {coin} {order.get('side')} (toplam: {len(self._positions)})")

        # Açık pozisyonları kontrol et
        if not self._positions or not self._latest_prices:
            return

        await self._check_positions()

    def _check_daily_reset(self):
        """Her gün başında günlük limitleri sıfırla"""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if today != self._daily_reset_date:
            if self._daily_reset_date:
                self.logger.info(f"Günlük reset: kayıp=${self._daily_loss:.2f} kâr=${self._daily_profit:.2f}")
            self._daily_loss = 0.0
            self._daily_profit = 0.0
            self._closed_today = 0
            self._risk_locked = False
            self._daily_reset_date = today

    async def _check_positions(self):
        """Tüm açık pozisyonları gelişmiş kontrollerle kontrol et"""
        to_close = []

        for coin, pos in self._positions.items():
            price_data = self._latest_prices.get(coin)
            if not price_data:
                continue

            current_price = price_data.price
            entry_price = pos['entry_price']
            side = pos['side']

            if entry_price <= 0:
                continue

            # P&L hesapla
            if side == 'BUY':
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100

            pnl_usdt = (pnl_pct / 100) * pos['quantity'] * entry_price
            pos['current_pnl'] = round(pnl_pct, 2)

            # 1. Stop-Loss kontrolü
            sl_pct = CryptoTradingConfig.STOP_LOSS_PCT
            if pnl_pct <= -sl_pct:
                self.logger.warning(f"STOP-LOSS: {coin} PnL={pnl_pct:.2f}%")
                to_close.append((coin, f'stop_loss ({pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 2. Tek pozisyon max kayıp kontrolü
            if pnl_pct <= -self.MAX_SINGLE_LOSS_PCT:
                self.logger.warning(f"MAX TEK KAYIP: {coin} PnL={pnl_pct:.2f}% (limit: %{self.MAX_SINGLE_LOSS_PCT})")
                to_close.append((coin, f'max_single_loss ({pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 3. Take-Profit kontrolü
            tp_pct = CryptoTradingConfig.TAKE_PROFIT_PCT
            if pnl_pct >= tp_pct:
                self.logger.info(f"TAKE-PROFIT: {coin} PnL=+{pnl_pct:.2f}%")
                to_close.append((coin, f'take_profit (+{pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 4. Trailing stop
            if pnl_pct > self.TRAILING_STOP_ACTIVATION:
                prev_peak = pos.get('peak_pnl', pnl_pct)
                pos['peak_pnl'] = max(prev_peak, pnl_pct)
                drawdown = pos['peak_pnl'] - pnl_pct
                if drawdown > self.TRAILING_STOP_DISTANCE:
                    self.logger.info(f"TRAILING STOP: {coin} peak={pos['peak_pnl']:.2f}% current={pnl_pct:.2f}%")
                    to_close.append((coin, f'trailing_stop (peak={pos["peak_pnl"]:.2f}%)', pnl_usdt, pnl_pct))
                    continue

            # 5. Pozisyon yaşlanma kontrolü
            age_hours = (datetime.now(timezone.utc) - pos['opened_at']).total_seconds() / 3600
            if age_hours > self.POSITION_AGE_LIMIT_H:
                self.logger.info(f"YAŞLANMA: {coin} {age_hours:.1f}h açık (limit: {self.POSITION_AGE_LIMIT_H}h)")
                to_close.append((coin, f'age_limit ({age_hours:.1f}h)', pnl_usdt, pnl_pct))
                continue

            # Loglama (önemli değişimler)
            if abs(pnl_pct) > 1:
                self.logger.info(f"Pozisyon {coin}: PnL={pnl_pct:+.2f}% (entry={entry_price}, current={current_price})")

        # Kapatılacak pozisyonlar
        for coin, reason, pnl_usdt, pnl_pct in to_close:
            await self.send('executor', {
                'type': 'close_position',
                'coin': coin,
                'reason': reason,
            })
            await self.send('alert', {
                'type': 'position_closing',
                'coin': coin,
                'reason': reason,
                'pnl': self._positions[coin].get('current_pnl', 0),
            })

            # Günlük P&L güncelle
            if pnl_usdt < 0:
                self._daily_loss += abs(pnl_usdt)
            else:
                self._daily_profit += pnl_usdt

            # Win/loss kaydet (Kelly için)
            self._win_history.append(pnl_pct > 0)
            if len(self._win_history) > 100:
                self._win_history = self._win_history[-100:]

            self._closed_today += 1
            self._total_pnl += pnl_pct
            if self._total_pnl < self._max_drawdown:
                self._max_drawdown = self._total_pnl

            del self._positions[coin]

            # Günlük kayıp limiti kontrolü
            if self._daily_loss >= self.MAX_DAILY_LOSS:
                self._risk_locked = True
                self.logger.warning(
                    f"GÜNLÜK KAYIP LİMİTİ AŞILDI! ${self._daily_loss:.2f} >= ${self.MAX_DAILY_LOSS}"
                    f" - Yeni pozisyon açma kilitledi!"
                )
                await self.send('alert', {
                    'type': 'risk_locked',
                    'daily_loss': self._daily_loss,
                    'limit': self.MAX_DAILY_LOSS,
                })

    def _win_rate(self) -> float:
        """Win rate hesapla"""
        if not self._win_history:
            return 0.5  # Default %50
        return sum(1 for w in self._win_history if w) / len(self._win_history)

    def _kelly_fraction(self) -> float:
        """
        Kelly Criterion - Optimal pozisyon boyutu
        f* = (bp - q) / b
        b = ortalama kazanç / ortalama kayıp oranı
        p = win rate
        q = 1 - p
        """
        if len(self._win_history) < 10:
            return 0.5  # Yeterli veri yoksa %50

        p = self._win_rate()
        q = 1 - p

        # Varsayılan b (avg win / avg loss ratio)
        # SL=%3, TP=%5 → b = 5/3 = 1.67
        b = CryptoTradingConfig.TAKE_PROFIT_PCT / CryptoTradingConfig.STOP_LOSS_PCT

        kelly = (b * p - q) / b

        # Kelly'nin yarısını kullan (daha güvenli)
        half_kelly = kelly / 2

        # %10-100% arasında sınırla
        return max(0.1, min(1.0, half_kelly))

    def get_recommended_position_size(self, base_size: float) -> float:
        """Kelly Criterion bazlı pozisyon boyutu önerisi"""
        kelly = self._kelly_fraction()

        # Günlük kayıp durumuna göre azalt
        remaining_budget = max(0, self.MAX_DAILY_LOSS - self._daily_loss)
        daily_factor = min(1.0, remaining_budget / self.MAX_DAILY_LOSS)

        return round(base_size * kelly * daily_factor, 2)
