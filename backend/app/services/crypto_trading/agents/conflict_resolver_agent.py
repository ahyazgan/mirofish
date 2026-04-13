"""
Çakışma Çözücü - Ajanlardan gelen çelişkili sinyalleri çözer.
Öncelik bazlı karar mekanizması. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone
from collections import defaultdict

from .base_agent import BaseAgent


class ConflictResolverAgent(BaseAgent):
    """
    Görev: Çelişkili sinyalleri tespit et ve çöz
    Girdi: Strategist'ten gelen sinyaller, Risk Manager kararları
    Çıktı: Nihai karar → Executor

    Senaryolar:
    - Sentiment LONG ama teknik SHORT → çöz
    - Risk Manager izin vermiyor ama sinyal güçlü → değerlendir
    - Birden fazla coin için aynı anda sinyal → öncelikle
    - Kill Switch aktifken gelen sinyaller → engelle
    """

    # Sinyal kaynağı öncelik ağırlıkları (yüksek = daha güvenilir)
    SOURCE_PRIORITY = {
        'kill_switch': 100,      # Her zaman en öncelikli
        'risk_manager': 90,      # Risk kararları kritik
        'flash_crash': 85,       # Acil durum
        'news_impact': 80,       # Haber etkisi güçlü
        'technical': 70,         # Teknik analiz
        'sentiment': 60,         # Duygu analizi
        'whale': 55,             # Balina hareketleri
        'funding_rate': 50,      # Fonlama oranı
        'onchain': 45,           # On-chain veriler
        'correlation': 40,       # Korelasyon
        'social_media': 35,      # Sosyal medya
        'macro': 30,             # Makro göstergeler
    }

    # Aynı anda maksimum açık sinyal sayısı
    MAX_CONCURRENT_SIGNALS = 3

    def __init__(self, interval: float = 3.0):
        super().__init__('Cakisma Cozucu', interval=interval)
        self._pending_signals: list[dict] = []
        self._active_decisions: dict[str, dict] = {}  # coin → decision
        self._conflict_history: list[dict] = []
        self._kill_switch_active = False
        self._resolver_stats = {
            'total_conflicts': 0,
            'resolved': 0,
            'blocked_by_kill': 0,
            'blocked_by_risk': 0,
        }

    @property
    def resolver_stats(self) -> dict:
        return {
            **self._resolver_stats,
            'pending_signals': len(self._pending_signals),
            'active_decisions': len(self._active_decisions),
            'kill_switch_active': self._kill_switch_active,
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'kill_switch_activated':
                self._kill_switch_active = True
                self._pending_signals.clear()
                self._active_decisions.clear()
                self.logger.warning("Kill Switch aktif → tüm sinyaller temizlendi")

            elif msg_type == 'resume_trading':
                self._kill_switch_active = False
                self.logger.info("Kill Switch deaktif → sinyal kabul başladı")

            elif msg_type == 'trade_signal':
                if self._kill_switch_active:
                    self._resolver_stats['blocked_by_kill'] += 1
                    continue

                self._pending_signals.append({
                    'coin': msg.get('coin', ''),
                    'side': msg.get('side', ''),
                    'confidence': msg.get('confidence', 0),
                    'source': msg.get('source', 'unknown'),
                    'sources': msg.get('sources', {}),
                    'size_usdt': msg.get('size_usdt', 0),
                    'signal': msg.get('signal', {}),
                    'signal_object': msg.get('signal_object'),
                    'time': datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == 'risk_rejected':
                coin = msg.get('coin', '')
                reason = msg.get('reason', '')
                if coin in self._active_decisions:
                    del self._active_decisions[coin]
                self._resolver_stats['blocked_by_risk'] += 1
                self.logger.info(f"RISK RED | {coin} sebep={reason}")

            elif msg_type == 'position_closed':
                coin = msg.get('coin', '')
                if coin in self._active_decisions:
                    del self._active_decisions[coin]

        # Bekleyen sinyalleri çöz
        if self._pending_signals and not self._kill_switch_active:
            await self._resolve_conflicts()

    async def _resolve_conflicts(self):
        """Çelişkili sinyalleri çöz"""
        if not self._pending_signals:
            return

        # Coin bazında grupla
        coin_signals: dict[str, list[dict]] = defaultdict(list)
        for sig in self._pending_signals:
            coin_signals[sig['coin']].append(sig)

        self._pending_signals.clear()

        resolved = []

        for coin, signals in coin_signals.items():
            # Zaten aktif karar varsa atla
            if coin in self._active_decisions:
                continue

            if len(signals) == 1:
                # Tek sinyal → doğrudan geç
                resolved.append(signals[0])
                continue

            # Çoklu sinyal → çakışma var
            self._resolver_stats['total_conflicts'] += 1

            # Yön çakışması kontrol
            buy_signals = [s for s in signals if s['side'] == 'BUY']
            sell_signals = [s for s in signals if s['side'] == 'SELL']

            if buy_signals and sell_signals:
                # Zıt yönlerde sinyal → ağırlıklı karar
                buy_score = self._calc_weighted_score(buy_signals)
                sell_score = self._calc_weighted_score(sell_signals)

                if abs(buy_score - sell_score) < 0.1:
                    # Çok yakın → işlem yapma
                    self.logger.info(
                        f"CAKISMA ESIT | {coin} BUY={buy_score:.2f} SELL={sell_score:.2f} → PAS"
                    )
                    self._conflict_history.append({
                        'coin': coin,
                        'result': 'SKIP',
                        'buy_score': round(buy_score, 3),
                        'sell_score': round(sell_score, 3),
                        'time': datetime.now(timezone.utc).isoformat(),
                    })
                    continue

                winner = buy_signals if buy_score > sell_score else sell_signals
                winner_side = 'BUY' if buy_score > sell_score else 'SELL'
                winner_score = max(buy_score, sell_score)

                # En yüksek güvenilirlikli sinyali seç
                best = max(winner, key=lambda s: s.get('confidence', 0))
                best['confidence'] = min(best['confidence'], winner_score)
                resolved.append(best)

                self.logger.info(
                    f"CAKISMA COZULDU | {coin} BUY={buy_score:.2f} SELL={sell_score:.2f} "
                    f"→ {winner_side}"
                )

                self._conflict_history.append({
                    'coin': coin,
                    'result': winner_side,
                    'buy_score': round(buy_score, 3),
                    'sell_score': round(sell_score, 3),
                    'time': datetime.now(timezone.utc).isoformat(),
                })
            else:
                # Aynı yönde birden fazla sinyal → en güçlüsünü seç
                best = max(signals, key=lambda s: s.get('confidence', 0))
                resolved.append(best)

            self._resolver_stats['resolved'] += 1

        # Eşzamanlı sinyal limiti
        if len(resolved) > self.MAX_CONCURRENT_SIGNALS:
            resolved.sort(key=lambda s: s.get('confidence', 0), reverse=True)
            resolved = resolved[:self.MAX_CONCURRENT_SIGNALS]
            self.logger.info(
                f"SINYAL LIMIT | {len(resolved)} sinyal, "
                f"max {self.MAX_CONCURRENT_SIGNALS} seçildi"
            )

        # Kazanan sinyalleri executor'a gönder
        for signal in resolved:
            coin = signal['coin']
            self._active_decisions[coin] = {
                'side': signal['side'],
                'confidence': signal['confidence'],
                'time': datetime.now(timezone.utc).isoformat(),
            }

            await self.send('executor', {
                'type': 'execute_signal',
                'coin': coin,
                'side': signal['side'],
                'confidence': signal['confidence'],
                'size_usdt': signal.get('size_usdt', 0),
                'source': 'conflict_resolver',
                'original_sources': signal.get('sources', {}),
                'signal': signal.get('signal', {}),
                'signal_object': signal.get('signal_object'),
            })

        if len(self._conflict_history) > 200:
            self._conflict_history = self._conflict_history[-200:]

    def _calc_weighted_score(self, signals: list[dict]) -> float:
        """Ağırlıklı skor hesapla"""
        total_score = 0
        total_weight = 0

        for sig in signals:
            source = sig.get('source', 'unknown')
            priority = self.SOURCE_PRIORITY.get(source, 20)
            confidence = sig.get('confidence', 0)

            weight = priority / 100
            total_score += confidence * weight
            total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0
