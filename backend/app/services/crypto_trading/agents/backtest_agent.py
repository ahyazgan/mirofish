"""
Backtest Agent - Sinyal doğrulama ve strateji performans ölçümü
Üretilen sinyallerin gerçek fiyat hareketleriyle karşılaştırılması.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent


class BacktestAgent(BaseAgent):
    """
    Görev: Sinyal kalitesini ölç, strateji performansını raporla
    Girdi: Strategist'ten sinyaller, Price Tracker'dan fiyatlar
    Çıktı: Performans raporu → Alert, Strategist (kalibrasyon)

    Mantık:
    - Her sinyali kaydet (coin, yön, giriş fiyatı, zaman)
    - Belirli süre sonra gerçek fiyatı kontrol et
    - Doğru/yanlış sinyal oranını hesapla
    - Sinyal kaynaklarını puanla (hangi kaynak daha doğru)
    """

    def __init__(self, interval: float = 60.0):
        super().__init__('Sinyal Dogrulayici', interval=interval)
        self._pending_signals: list[dict] = []  # Doğrulanmayı bekleyen sinyaller
        self._completed_signals: list[dict] = []  # Doğrulanmış sinyaller
        self._latest_prices: dict = {}
        self._source_stats: dict[str, dict] = {}  # Kaynak bazlı istatistik
        self._verification_delay = 300  # 5 dakika sonra kontrol et (saniye)

    @property
    def backtest_stats(self) -> dict:
        total = len(self._completed_signals)
        correct = sum(1 for s in self._completed_signals if s.get('correct'))
        accuracy = (correct / total * 100) if total > 0 else 0

        return {
            'total_verified': total,
            'correct': correct,
            'wrong': total - correct,
            'accuracy': round(accuracy, 1),
            'pending': len(self._pending_signals),
            'source_stats': self._source_stats,
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

            elif msg.get('type') == 'new_signal':
                signal = msg.get('signal', {})
                self._pending_signals.append({
                    'signal': signal,
                    'entry_price': signal.get('entry_price', 0),
                    'coin': signal.get('coin', ''),
                    'action': signal.get('action', ''),
                    'strength': signal.get('strength', ''),
                    'score': signal.get('sentiment_score', 0),
                    'reasons': signal.get('reasons', []),
                    'created_at': datetime.now(timezone.utc),
                    'verified': False,
                })

        # Bekleyen sinyalleri doğrula
        await self._verify_signals()

        # Periyodik rapor (her 10 döngüde)
        if self._completed_signals and self.stats['cycles'] % 10 == 0:
            await self._send_report()

    async def _verify_signals(self):
        """Bekleyen sinyalleri gerçek fiyatla karşılaştır"""
        now = datetime.now(timezone.utc)
        still_pending = []

        for signal_data in self._pending_signals:
            elapsed = (now - signal_data['created_at']).total_seconds()

            if elapsed < self._verification_delay:
                still_pending.append(signal_data)
                continue

            coin = signal_data['coin']
            price_data = self._latest_prices.get(coin)
            if not price_data:
                # Fiyat verisi yoksa 10 dakika daha bekle
                if elapsed < self._verification_delay * 2:
                    still_pending.append(signal_data)
                continue

            current_price = price_data.price
            entry_price = signal_data['entry_price']
            action = signal_data['action']

            if entry_price <= 0:
                continue

            price_change_pct = ((current_price - entry_price) / entry_price) * 100

            # Doğruluk: BUY sinyalinde fiyat yükseldi mi? SELL sinyalinde düştü mü?
            if action == 'BUY':
                correct = price_change_pct > 0
            elif action == 'SELL':
                correct = price_change_pct < 0
            else:
                continue

            signal_data['verified'] = True
            signal_data['current_price'] = current_price
            signal_data['price_change_pct'] = round(price_change_pct, 2)
            signal_data['correct'] = correct
            signal_data['verified_at'] = now.isoformat()

            self._completed_signals.append(signal_data)

            # Kaynak bazlı istatistik güncelle
            self._update_source_stats(signal_data)

            status = "DOGRU" if correct else "YANLIS"
            self.logger.info(
                f"BACKTEST | {coin} {action} → {status} "
                f"(entry={entry_price:.2f} now={current_price:.2f} "
                f"change={price_change_pct:+.2f}%)"
            )

        self._pending_signals = still_pending

        # Son 500 doğrulanmış sinyal tut
        if len(self._completed_signals) > 500:
            self._completed_signals = self._completed_signals[-500:]

    def _update_source_stats(self, signal_data: dict):
        """Sinyal kaynak istatistiklerini güncelle"""
        reasons = signal_data.get('reasons', [])
        correct = signal_data.get('correct', False)

        # Her reason'dan kaynak çıkar
        sources = set()
        for reason in reasons:
            reason_lower = reason.lower()
            if 'rsi' in reason_lower or 'macd' in reason_lower or 'bollinger' in reason_lower:
                sources.add('technical_analysis')
            elif 'funding' in reason_lower:
                sources.add('funding_rate')
            elif 'whale' in reason_lower or 'balina' in reason_lower:
                sources.add('whale_tracker')
            elif 'orderbook' in reason_lower or 'bid' in reason_lower:
                sources.add('orderbook')
            elif 'reddit' in reason_lower or 'social' in reason_lower:
                sources.add('social_media')
            elif 'fear' in reason_lower or 'dominan' in reason_lower:
                sources.add('correlation')
            else:
                sources.add('news_sentiment')

        # Kaynak yoksa genel sentiment
        if not sources:
            sources.add('news_sentiment')

        for source in sources:
            if source not in self._source_stats:
                self._source_stats[source] = {
                    'total': 0,
                    'correct': 0,
                    'accuracy': 0,
                }
            self._source_stats[source]['total'] += 1
            if correct:
                self._source_stats[source]['correct'] += 1
            total = self._source_stats[source]['total']
            self._source_stats[source]['accuracy'] = round(
                self._source_stats[source]['correct'] / total * 100, 1
            )

    async def _send_report(self):
        """Performans raporunu gönder"""
        stats = self.backtest_stats

        await self.send('alert', {
            'type': 'backtest_report',
            'total_verified': stats['total_verified'],
            'accuracy': stats['accuracy'],
            'correct': stats['correct'],
            'wrong': stats['wrong'],
            'pending': stats['pending'],
            'source_stats': stats['source_stats'],
        })

        # Strategist'e kalibrasyon verisi gönder
        await self.send('strategist', {
            'type': 'backtest_calibration',
            'accuracy': stats['accuracy'],
            'source_stats': stats['source_stats'],
        })

        self.logger.info(
            f"BACKTEST RAPOR | Doğruluk: %{stats['accuracy']} "
            f"({stats['correct']}/{stats['total_verified']}) "
            f"Bekleyen: {stats['pending']}"
        )
