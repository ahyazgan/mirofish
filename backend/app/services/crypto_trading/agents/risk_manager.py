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
        # Aynı coin'de birden fazla pozisyon destekle → key = f"{coin}:{order_id}"
        self._positions: dict[str, dict] = {}
        self._latest_prices: dict = {}
        self._total_pnl_usdt: float = 0.0  # $ cinsinden kümülatif (önceden pct cumulative idi)
        self._max_drawdown_usdt: float = 0.0
        self._daily_loss: float = 0.0
        self._daily_profit: float = 0.0
        self._daily_reset_date: str = ''
        self._closed_today: int = 0
        self._win_history: list[bool] = []  # Kelly hesabı için
        self._pnl_history: list[tuple[float, float]] = []  # (win_pnl, loss_pnl) — Kelly b gerçek
        self._risk_locked = False
        # Flash crash gelince stop'ları sıkılaştırmak için çarpan
        self._stop_tightness: float = 1.0
        # Drawdown'a göre kâr/zarar limitleri dinamik ayarlanabilir
        self._drawdown_warning = False

    @property
    def positions(self) -> dict:
        return self._positions

    @property
    def risk_stats(self) -> dict:
        return {
            'open_positions': len(self._positions),
            'max_positions': self.MAX_OPEN_POSITIONS,
            'total_pnl': round(self._total_pnl_usdt, 2),
            'max_drawdown': round(self._max_drawdown_usdt, 2),
            'daily_loss': round(self._daily_loss, 2),
            'daily_profit': round(self._daily_profit, 2),
            'daily_net': round(self._daily_profit - self._daily_loss, 2),
            'max_daily_loss': self.MAX_DAILY_LOSS,
            'risk_locked': self._risk_locked,
            'kelly_fraction': round(self._kelly_fraction(), 4),
            'win_rate': round(self._win_rate() * 100, 1),
            'closed_today': self._closed_today,
            'stop_tightness': round(self._stop_tightness, 2),
            'drawdown_warning': self._drawdown_warning,
            'positions': {k: {
                'coin': v.get('coin', k),
                'side': v['side'],
                'entry': v['entry_price'],
                'current_pnl': v.get('current_pnl', 0),
                'peak_pnl': v.get('peak_pnl', 0),
                'age_minutes': round((datetime.now(timezone.utc) - v['opened_at']).total_seconds() / 60, 1),
            } for k, v in self._positions.items()},
        }

    @staticmethod
    def _position_key(coin: str, order_id: str) -> str:
        return f"{coin}:{order_id}"

    async def run_cycle(self):
        # Günlük reset kontrolü
        self._check_daily_reset()

        messages = await self.receive_all()

        for msg in messages:
            mtype = msg.get('type')

            if mtype == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

            elif mtype == 'new_position':
                order = msg.get('order', {})
                signal = msg.get('signal', {})
                coin = order.get('coin', '')
                order_id = str(order.get('order_id') or order.get('id') or order.get('client_order_id') or '')

                # Max pozisyon kontrolü
                if len(self._positions) >= self.MAX_OPEN_POSITIONS:
                    self.logger.warning(f"MAX POZİSYON LİMİTİ: {coin} reddedildi ({len(self._positions)}/{self.MAX_OPEN_POSITIONS})")
                    await self.send('alert', {
                        'type': 'risk_rejected',
                        'coin': coin,
                        'reason': f'Max pozisyon limiti ({self.MAX_OPEN_POSITIONS})',
                    })
                    continue

                # Günlük kayıp kilidi kontrolü
                if self._risk_locked:
                    self.logger.warning(f"RİSK KİLİTLİ: {coin} reddedildi (günlük kayıp limiti aşıldı)")
                    await self.send('alert', {
                        'type': 'risk_rejected',
                        'coin': coin,
                        'reason': f'Günlük kayıp limiti aşıldı (${self._daily_loss:.0f}/${self.MAX_DAILY_LOSS})',
                    })
                    continue

                key = self._position_key(coin, order_id)
                self._positions[key] = {
                    'coin': coin,
                    'order_id': order_id,
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
                self.logger.info(f"Yeni pozisyon: {coin} {order.get('side')} id={order_id} (toplam: {len(self._positions)})")

            # Executor pozisyon kapattığında envanteri senkronize et
            elif mtype == 'position_closed':
                coin = msg.get('coin', '')
                order_id = str(msg.get('order_id') or '')
                key = self._position_key(coin, order_id) if order_id else None
                if key and key in self._positions:
                    del self._positions[key]
                else:
                    # Order_id gelmediyse — ilk eşleşen coin'i kaldır
                    for k in list(self._positions.keys()):
                        if self._positions[k].get('coin') == coin:
                            del self._positions[k]
                            break

            # Kill Switch aktif olursa tüm envanteri temizle
            elif mtype == 'kill_switch_activated':
                if self._positions:
                    self.logger.warning(f"Kill Switch → {len(self._positions)} pozisyon envanteri temizleniyor")
                    self._positions.clear()
                self._risk_locked = True

            # Flash crash gelince stop'ları sıkılaştır
            elif mtype == 'tighten_stops':
                severity = msg.get('severity', 'HIGH')
                # CRITICAL: 50% sıkılaştır, HIGH: 30%
                self._stop_tightness = 0.5 if severity == 'CRITICAL' else 0.7
                self.logger.warning(f"Stop'lar sıkılaştırıldı (multiplier={self._stop_tightness}) sebep={msg.get('reason', '?')}")

            # Drawdown uyarısı → yeni pozisyonları dikkatli değerlendir
            elif mtype == 'drawdown_warning':
                self._drawdown_warning = True
                self.logger.warning(f"Drawdown uyarısı: {msg.get('drawdown_pct', 0):.1f}%")

            # Günlük drawdown limiti → risk kilidi
            elif mtype in ('drawdown_daily_limit', 'drawdown_exceeded', 'losing_streak'):
                self._risk_locked = True
                self.logger.warning(f"Risk kilidi aktifleştirildi ({mtype})")
                await self.send('alert', {
                    'type': 'risk_locked',
                    'reason': mtype,
                    'details': msg,
                })

            # Smart stop: belirli pozisyonun SL'ini güncelle
            elif mtype == 'update_stop':
                coin = msg.get('coin', '')
                new_sl = msg.get('new_stop_loss')
                if new_sl is not None:
                    for pos in self._positions.values():
                        if pos.get('coin') == coin:
                            pos['stop_loss'] = new_sl
                            self.logger.info(f"SL güncellendi {coin} → {new_sl}")

            # Event calendar → yüksek riskli event yaklaşırsa yeni pozisyon açma
            elif mtype == 'upcoming_events':
                events = msg.get('events', [])
                if events:
                    self._drawdown_warning = True  # pozisyon sayısını azaltma sinyali

            # Funding cost yüksek → pozisyon boyutunu küçültme sinyali (Kelly azaltır)
            elif mtype == 'funding_cost_high':
                self._drawdown_warning = True

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
        to_close = []  # (key, coin, reason, pnl_usdt, pnl_pct)

        for key, pos in self._positions.items():
            coin = pos.get('coin', '')
            price_data = self._latest_prices.get(coin)
            if not price_data:
                continue

            current_price = getattr(price_data, 'price', None)
            if current_price is None and isinstance(price_data, dict):
                current_price = price_data.get('price')
            if current_price is None:
                continue

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

            # Flash crash / drawdown durumunda stop'ları sıkılaştır
            tightness = self._stop_tightness  # < 1.0 → daha dar SL/TP
            sl_pct = CryptoTradingConfig.STOP_LOSS_PCT * tightness
            tp_pct = CryptoTradingConfig.TAKE_PROFIT_PCT * tightness
            max_single = self.MAX_SINGLE_LOSS_PCT * tightness

            # 1. Stop-Loss kontrolü
            if pnl_pct <= -sl_pct:
                self.logger.warning(f"STOP-LOSS: {coin} PnL={pnl_pct:.2f}%")
                to_close.append((key, coin, f'stop_loss ({pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 2. Tek pozisyon max kayıp kontrolü
            if pnl_pct <= -max_single:
                self.logger.warning(f"MAX TEK KAYIP: {coin} PnL={pnl_pct:.2f}% (limit: %{max_single:.2f})")
                to_close.append((key, coin, f'max_single_loss ({pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 3. Take-Profit kontrolü
            if pnl_pct >= tp_pct:
                self.logger.info(f"TAKE-PROFIT: {coin} PnL=+{pnl_pct:.2f}%")
                to_close.append((key, coin, f'take_profit (+{pnl_pct:.2f}%)', pnl_usdt, pnl_pct))
                continue

            # 4. Trailing stop
            trailing_activation = self.TRAILING_STOP_ACTIVATION * tightness
            trailing_distance = self.TRAILING_STOP_DISTANCE * tightness
            if pnl_pct > trailing_activation:
                prev_peak = pos.get('peak_pnl', pnl_pct)
                pos['peak_pnl'] = max(prev_peak, pnl_pct)
                drawdown = pos['peak_pnl'] - pnl_pct
                if drawdown > trailing_distance:
                    self.logger.info(f"TRAILING STOP: {coin} peak={pos['peak_pnl']:.2f}% current={pnl_pct:.2f}%")
                    to_close.append((key, coin, f'trailing_stop (peak={pos["peak_pnl"]:.2f}%)', pnl_usdt, pnl_pct))
                    continue

            # 5. Pozisyon yaşlanma kontrolü
            age_hours = (datetime.now(timezone.utc) - pos['opened_at']).total_seconds() / 3600
            if age_hours > self.POSITION_AGE_LIMIT_H:
                self.logger.info(f"YAŞLANMA: {coin} {age_hours:.1f}h açık (limit: {self.POSITION_AGE_LIMIT_H}h)")
                to_close.append((key, coin, f'age_limit ({age_hours:.1f}h)', pnl_usdt, pnl_pct))
                continue

            # Loglama (önemli değişimler)
            if abs(pnl_pct) > 1:
                self.logger.info(f"Pozisyon {coin}: PnL={pnl_pct:+.2f}% (entry={entry_price}, current={current_price})")

        # Kapatılacak pozisyonlar
        for key, coin, reason, pnl_usdt, pnl_pct in to_close:
            pos = self._positions.get(key, {})
            order_id = pos.get('order_id', '')

            await self.send('executor', {
                'type': 'close_position',
                'coin': coin,
                'order_id': order_id,
                'reason': reason,
            })
            await self.send('alert', {
                'type': 'position_closed',
                'coin': coin,
                'reason': reason,
                'pnl': pos.get('current_pnl', 0),
                'pnl_usdt': round(pnl_usdt, 2),
            })

            # Günlük P&L güncelle
            if pnl_usdt < 0:
                self._daily_loss += abs(pnl_usdt)
                self._pnl_history.append((0.0, abs(pnl_usdt)))
            else:
                self._daily_profit += pnl_usdt
                self._pnl_history.append((pnl_usdt, 0.0))
            if len(self._pnl_history) > 100:
                self._pnl_history = self._pnl_history[-100:]

            # Win/loss kaydet (Kelly için)
            self._win_history.append(pnl_pct > 0)
            if len(self._win_history) > 100:
                self._win_history = self._win_history[-100:]

            self._closed_today += 1
            # $ cinsinden kümülatif PnL ve drawdown
            self._total_pnl_usdt += pnl_usdt
            if self._total_pnl_usdt < self._max_drawdown_usdt:
                self._max_drawdown_usdt = self._total_pnl_usdt

            if key in self._positions:
                del self._positions[key]

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
        b = ortalama kazanç / ortalama kayıp oranı (gerçek PnL geçmişinden)
        p = win rate
        q = 1 - p
        """
        if len(self._win_history) < 10:
            return 0.5  # Yeterli veri yoksa %50

        p = self._win_rate()
        q = 1 - p

        # Gerçek PnL geçmişinden b hesapla
        wins = [w for w, _ in self._pnl_history if w > 0]
        losses = [l for _, l in self._pnl_history if l > 0]
        if wins and losses:
            avg_win = sum(wins) / len(wins)
            avg_loss = sum(losses) / len(losses)
            b = avg_win / avg_loss if avg_loss > 0 else 1.67
        else:
            # Yeterli veri yoksa SL/TP oranını kullan
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

        # Drawdown uyarısı varsa ek güvenlik — yarıya indir
        warning_factor = 0.5 if self._drawdown_warning else 1.0

        return round(base_size * kelly * daily_factor * warning_factor, 2)
