"""
Signal Strategist Agent - Sinyal üretim stratejisti
20 ajandan gelen verileri birleştirip trading sinyalleri üretir.
"""

from datetime import datetime, timezone

from .base_agent import BaseAgent
from ..config import CryptoTradingConfig
from ..signal_engine import SignalAction, SignalStrength, TradingSignal


class SignalStrategistAgent(BaseAgent):
    """
    Görev: Tüm veri kaynaklarını birleştirip sinyal üret
    Girdi:
        - Sentiment Agent (haber duygu analizi)
        - Technical Analysis Agent (RSI, MACD, Bollinger)
        - Social Media Agent (Reddit sentiment)
        - Whale Tracker Agent (balina hareketleri)
        - Funding Rate Agent (futures fonlama)
        - Order Book Agent (emir defteri analizi)
        - Liquidation Agent (likidasyon verileri)
        - Correlation Agent (BTC dominans, F&G)
        - DeFi Monitor Agent (TVL, DEX hacmi)
        - Volatility Agent (ATR, Bollinger squeeze)
        - Market Regime Agent (trending/ranging/volatile)
        - Macro Tracker Agent (DXY, Altın, S&P500)
        - Price Tracker (fiyat verileri)
        - Backtest Agent (kalibrasyon)
    Çıktı: Trading sinyalleri → Trade Executor, Backtest
    """

    # Sinyal kaynak ağırlıkları (toplam ~1.0)
    SOURCE_WEIGHTS = {
        'news_sentiment': 0.15,      # Haber sentiment en önemli
        'news_impact': 0.06,         # Haber etki sınıfı
        'news_verification': 0.04,   # Haber doğrulama skoru
        'technical_analysis': 0.14,   # Teknik analiz
        'orderbook': 0.08,           # Emir defteri
        'funding_rate': 0.06,        # Fonlama oranı
        'social_media': 0.05,        # Reddit sentiment
        'whale_activity': 0.06,      # Balina hareketleri
        'liquidation': 0.05,         # Likidasyon
        'correlation': 0.06,         # Korelasyon & F&G
        'defi_monitor': 0.04,        # DeFi TVL & hacim
        'volatility': 0.04,          # Volatilite & breakout
        'market_regime': 0.03,       # Piyasa rejimi
        'macro': 0.03,               # Makroekonomik göstergeler
        'onchain': 0.04,             # On-chain metrikler
        'regulation': 0.04,          # Regülasyon haberleri
        'exchange_listing': 0.04,    # Borsa listeleme/çıkarma
        'event_calendar': 0.02,      # Etkinlik takvimi
        'funding_cost': 0.01,        # Fonlama maliyeti
    }

    def __init__(self, interval: float = 5.0):
        super().__init__('Sinyal Stratejisti', interval=interval)
        self._latest_prices: dict = {}
        self._sentiment_buffer: list = []
        self._technical_buffer: list[dict] = []
        self._social_buffer: list[dict] = []
        self._whale_buffer: list[dict] = []
        self._funding_buffer: list[dict] = []
        self._orderbook_buffer: list[dict] = []
        self._liquidation_buffer: list[dict] = []
        self._correlation_buffer: list[dict] = []
        self._defi_buffer: list[dict] = []
        self._volatility_buffer: list[dict] = []
        self._regime_buffer: list[dict] = []
        self._macro_buffer: list[dict] = []
        self._onchain_buffer: list[dict] = []
        self._regulation_buffer: list[dict] = []
        self._listing_buffer: list[dict] = []
        self._calendar_buffer: list[dict] = []
        self._news_impact_buffer: list[dict] = []
        self._news_verify_buffer: list[dict] = []
        self._funding_cost_buffer: list[dict] = []
        self._signal_counter = 0
        self._signal_history: list[dict] = []
        self._source_calibration: dict[str, float] = {}  # Backtest'ten gelen kalibrasyon
        self._current_regime: str = 'UNKNOWN'  # Market Regime'dan gelen rejim

    @property
    def signal_history(self) -> list[dict]:
        return self._signal_history

    async def run_cycle(self):
        messages = await self.receive_all()
        if not messages:
            return

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'price_update':
                self._latest_prices = msg.get('price_objects', {})

            elif msg_type == 'sentiment_results':
                results = msg.get('result_objects', [])
                self._sentiment_buffer.extend(results)

            elif msg_type == 'price_spike':
                for alert in msg.get('alerts', []):
                    self.logger.info(f"Ani hareket: {alert['coin']} %{alert['change_pct']}")

            # === YENİ VERİ KAYNAKLARI ===
            elif msg_type == 'technical_signals':
                self._technical_buffer.extend(msg.get('signals', []))

            elif msg_type == 'social_signals':
                self._social_buffer.extend(msg.get('signals', []))

            elif msg_type == 'whale_activity':
                self._whale_buffer.extend(msg.get('events', []))

            elif msg_type == 'funding_rate_signals':
                self._funding_buffer.extend(msg.get('signals', []))

            elif msg_type == 'orderbook_signals':
                self._orderbook_buffer.extend(msg.get('signals', []))

            elif msg_type == 'liquidation_signals':
                self._liquidation_buffer.extend(msg.get('signals', []))

            elif msg_type == 'correlation_signals':
                self._correlation_buffer.extend(msg.get('signals', []))

            elif msg_type == 'defi_signals':
                self._defi_buffer.extend(msg.get('signals', []))

            elif msg_type == 'volatility_signals':
                self._volatility_buffer.extend(msg.get('signals', []))

            elif msg_type == 'regime_signals':
                self._regime_buffer.extend(msg.get('signals', []))
                # Overall regime bilgisini de kullan
                overall = msg.get('overall_regime', '')
                if overall:
                    self._current_regime = overall

            elif msg_type == 'macro_signals':
                self._macro_buffer.extend(msg.get('signals', []))

            elif msg_type == 'onchain_signals':
                self._onchain_buffer.extend(msg.get('signals', []))

            elif msg_type == 'regulation_signals':
                self._regulation_buffer.extend(msg.get('signals', []))

            elif msg_type == 'listing_signals':
                self._listing_buffer.extend(msg.get('signals', []))

            elif msg_type == 'calendar_signals':
                self._calendar_buffer.extend(msg.get('signals', []))

            elif msg_type == 'news_impact_signals':
                self._news_impact_buffer.extend(msg.get('signals', []))

            elif msg_type == 'news_verification_signals':
                self._news_verify_buffer.extend(msg.get('signals', []))

            elif msg_type == 'funding_cost_signal':
                self._funding_cost_buffer.append(msg)

            elif msg_type == 'backtest_calibration':
                # Backtest'ten kalibrasyon verisi
                source_stats = msg.get('source_stats', {})
                for source, stats in source_stats.items():
                    if stats.get('total', 0) >= 5:  # En az 5 doğrulama
                        accuracy = stats.get('accuracy', 50) / 100
                        self._source_calibration[source] = accuracy

        # Sentiment buffer'da veri varsa veya diğer kaynaklardan veri geldiyse
        has_data = (
            self._sentiment_buffer or self._technical_buffer or
            self._social_buffer or self._whale_buffer or
            self._funding_buffer or self._orderbook_buffer or
            self._liquidation_buffer or self._correlation_buffer or
            self._defi_buffer or self._volatility_buffer or
            self._regime_buffer or self._macro_buffer or
            self._onchain_buffer or self._regulation_buffer or
            self._listing_buffer or self._calendar_buffer or
            self._news_impact_buffer or self._news_verify_buffer or
            self._funding_cost_buffer
        )

        if not has_data or not self._latest_prices:
            return

        await self._generate_signals()

    async def _generate_signals(self):
        """Tüm kaynakları birleştirip sinyal üret"""

        # Coin bazlı tüm skorları topla
        coin_scores: dict[str, dict] = {}

        # 1. Haber Sentiment Skorları
        self._process_sentiment_scores(coin_scores)

        # 2. Teknik Analiz Skorları
        self._process_technical_scores(coin_scores)

        # 3. Social Media Skorları
        self._process_generic_scores(coin_scores, self._social_buffer, 'social_media')

        # 4. Whale Activity Skorları
        self._process_whale_scores(coin_scores)

        # 5. Funding Rate Skorları
        self._process_generic_scores(coin_scores, self._funding_buffer, 'funding_rate')

        # 6. Order Book Skorları
        self._process_generic_scores(coin_scores, self._orderbook_buffer, 'orderbook')

        # 7. Liquidation Skorları
        self._process_generic_scores(coin_scores, self._liquidation_buffer, 'liquidation')

        # 8. Correlation Skorları (global - tüm coinlere uygulanır)
        self._process_correlation_scores(coin_scores)

        # 9. DeFi Monitor Skorları
        self._process_generic_scores(coin_scores, self._defi_buffer, 'defi_monitor')

        # 10. Volatility Skorları
        self._process_generic_scores(coin_scores, self._volatility_buffer, 'volatility')

        # 11. Market Regime Skorları
        self._process_generic_scores(coin_scores, self._regime_buffer, 'market_regime')

        # 12. Macro Skorları (global - tüm coinlere uygulanır)
        self._process_macro_scores(coin_scores)

        # 13. OnChain Skorları
        self._process_generic_scores(coin_scores, self._onchain_buffer, 'onchain')

        # 14. Regulation Skorları
        self._process_generic_scores(coin_scores, self._regulation_buffer, 'regulation')

        # 15. Exchange Listing Skorları
        self._process_generic_scores(coin_scores, self._listing_buffer, 'exchange_listing')

        # 16. Event Calendar Skorları
        self._process_generic_scores(coin_scores, self._calendar_buffer, 'event_calendar')

        # 17. News Impact Skorları
        self._process_generic_scores(coin_scores, self._news_impact_buffer, 'news_impact')

        # 18. News Verification Skorları
        self._process_generic_scores(coin_scores, self._news_verify_buffer, 'news_verification')

        # 19. Funding Cost Skorları
        self._process_generic_scores(coin_scores, self._funding_cost_buffer, 'funding_cost')

        # Buffer'ları temizle
        self._sentiment_buffer.clear()
        self._technical_buffer.clear()
        self._social_buffer.clear()
        self._whale_buffer.clear()
        self._funding_buffer.clear()
        self._orderbook_buffer.clear()
        self._liquidation_buffer.clear()
        self._correlation_buffer.clear()
        self._defi_buffer.clear()
        self._volatility_buffer.clear()
        self._regime_buffer.clear()
        self._macro_buffer.clear()
        self._onchain_buffer.clear()
        self._regulation_buffer.clear()
        self._listing_buffer.clear()
        self._calendar_buffer.clear()
        self._news_impact_buffer.clear()
        self._news_verify_buffer.clear()
        self._funding_cost_buffer.clear()

        # Sinyal üret
        signals_generated = 0

        for coin, data in coin_scores.items():
            price_data = self._latest_prices.get(coin)
            if not price_data:
                continue

            # Ağırlıklı final skor
            final_score = self._calculate_weighted_score(data)

            # Minimum eşik
            if abs(final_score) < CryptoTradingConfig.MIN_SENTIMENT_SCORE:
                continue

            # Aksiyon
            action = SignalAction.BUY if final_score > 0 else SignalAction.SELL

            # Güç - kaynak çeşitliliği de etkili
            source_count = len(data.get('sources', set()))
            if abs(final_score) > 0.7 and source_count >= 3:
                strength = SignalStrength.STRONG
            elif abs(final_score) > 0.4 and source_count >= 2:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK

            # Weak atla
            if strength == SignalStrength.WEAK:
                continue

            # Pozisyon büyüklüğü
            base_size = CryptoTradingConfig.MAX_POSITION_SIZE
            position_size = base_size if strength == SignalStrength.STRONG else base_size * 0.6

            # SL/TP
            entry = price_data.price
            sl_pct = CryptoTradingConfig.STOP_LOSS_PCT / 100
            tp_pct = CryptoTradingConfig.TAKE_PROFIT_PCT / 100

            if action == SignalAction.BUY:
                stop_loss = entry * (1 - sl_pct)
                take_profit = entry * (1 + tp_pct)
            else:
                stop_loss = entry * (1 + sl_pct)
                take_profit = entry * (1 - tp_pct)

            # Sebepler
            reasons = data.get('reasons', [])[:5]

            self._signal_counter += 1
            signal = TradingSignal(
                id=f"SIG-{self._signal_counter:06d}",
                coin=coin,
                action=action,
                strength=strength,
                entry_price=round(entry, 8),
                stop_loss=round(stop_loss, 8),
                take_profit=round(take_profit, 8),
                position_size_usdt=round(position_size, 2),
                sentiment_score=round(final_score, 3),
                confidence=round(min(source_count / 4, 1.0), 3),
                reasons=reasons,
                news_ids=data.get('news_ids', [])[:5],
            )

            self._signal_history.append(signal.to_dict())

            # Conflict Resolver'a gönder (çakışma kontrolü sonrası executor'a iletilir)
            await self.send('conflict_resolver', {
                'type': 'trade_signal',
                'coin': coin,
                'side': action.value,
                'confidence': round(min(source_count / 4, 1.0), 3),
                'source': 'strategist',
                'sources': {s: scores.get(s, 0) for s in data.get('sources', set())},
                'size_usdt': round(position_size, 2),
                'signal': signal.to_dict(),
                'signal_object': signal,
            })

            # Backtest'e gönder (doğrulama için)
            await self.send('backtest', {
                'type': 'new_signal',
                'signal': signal.to_dict(),
            })

            # Alert
            sources_str = ','.join(data.get('sources', set()))
            await self.send('alert', {
                'type': 'signal_generated',
                'coin': coin,
                'action': action.value,
                'strength': strength.value,
                'score': round(final_score, 3),
                'entry_price': entry,
                'sources': sources_str,
                'source_count': source_count,
            })

            signals_generated += 1
            self.logger.info(
                f"SİNYAL: {coin} {action.value} ({strength.value}) "
                f"score={final_score:.3f} sources={sources_str} entry={entry}"
            )

        if signals_generated:
            self.logger.info(f"Toplam {signals_generated} sinyal üretildi")

    def _process_sentiment_scores(self, coin_scores: dict):
        """Haber sentiment skorlarını işle"""
        coin_sentiments: dict[str, list] = {}
        for result in self._sentiment_buffer:
            coin = result.coin
            if coin not in coin_sentiments:
                coin_sentiments[coin] = []
            coin_sentiments[coin].append(result)

        for coin, sentiments in coin_sentiments.items():
            total_weight = sum(s.confidence for s in sentiments)
            if total_weight == 0:
                continue
            avg_score = sum(s.score * s.confidence for s in sentiments) / total_weight
            high_impact = sum(1 for s in sentiments if s.impact == 'high')

            if coin not in coin_scores:
                coin_scores[coin] = {'scores': {}, 'reasons': [], 'sources': set(), 'news_ids': []}

            coin_scores[coin]['scores']['news_sentiment'] = avg_score
            coin_scores[coin]['sources'].add('news_sentiment')
            coin_scores[coin]['news_ids'] = [s.news_id for s in sentiments[:5]]

            for s in sentiments[:2]:
                coin_scores[coin]['reasons'].append(f"[haber/{s.impact}] {s.reasoning}")

    def _process_technical_scores(self, coin_scores: dict):
        """Teknik analiz skorlarını işle"""
        for signal in self._technical_buffer:
            coin = signal.get('coin', '')
            if not coin:
                continue
            if coin not in coin_scores:
                coin_scores[coin] = {'scores': {}, 'reasons': [], 'sources': set(), 'news_ids': []}

            coin_scores[coin]['scores']['technical_analysis'] = signal.get('score', 0)
            coin_scores[coin]['sources'].add('technical_analysis')
            for reason in signal.get('reasons', [])[:2]:
                coin_scores[coin]['reasons'].append(f"[teknik] {reason}")

    def _process_generic_scores(self, coin_scores: dict, buffer: list[dict], source_name: str):
        """Genel sinyal kaynaklarını işle"""
        for signal in buffer:
            coin = signal.get('coin', '')
            if not coin:
                continue
            if coin not in coin_scores:
                coin_scores[coin] = {'scores': {}, 'reasons': [], 'sources': set(), 'news_ids': []}

            score = signal.get('signal_score', 0)
            # Aynı kaynaktan birden fazla sinyal varsa ortala
            existing = coin_scores[coin]['scores'].get(source_name)
            if existing is not None:
                coin_scores[coin]['scores'][source_name] = (existing + score) / 2
            else:
                coin_scores[coin]['scores'][source_name] = score

            coin_scores[coin]['sources'].add(source_name)
            reason = signal.get('reason', '')
            if reason:
                coin_scores[coin]['reasons'].append(f"[{source_name}] {reason}")

    def _process_whale_scores(self, coin_scores: dict):
        """Whale activity skorlarını işle"""
        for event in self._whale_buffer:
            coin = event.get('coin', '')
            if not coin:
                continue
            if coin not in coin_scores:
                coin_scores[coin] = {'scores': {}, 'reasons': [], 'sources': set(), 'news_ids': []}

            score = event.get('signal_score', 0)
            coin_scores[coin]['scores']['whale_activity'] = score
            coin_scores[coin]['sources'].add('whale_activity')

            direction = event.get('direction', '')
            value = event.get('value_usd', 0)
            coin_scores[coin]['reasons'].append(
                f"[whale] {direction} ${value:,.0f}"
            )

    def _process_correlation_scores(self, coin_scores: dict):
        """Korelasyon skorlarını işle - global sinyaller tüm coinlere uygulanır"""
        global_score = 0.0
        global_reasons = []

        for signal in self._correlation_buffer:
            applies_to = signal.get('applies_to', 'all')
            score = signal.get('signal_score', 0)
            reason = signal.get('reason', '')

            if applies_to == 'all':
                global_score += score
                if reason:
                    global_reasons.append(f"[korelasyon] {reason}")
            elif applies_to == 'altcoins':
                # Altcoin'lere uygula (BTC hariç)
                for coin in coin_scores:
                    if coin != 'BTC':
                        existing = coin_scores[coin]['scores'].get('correlation', 0)
                        coin_scores[coin]['scores']['correlation'] = existing + score
                        coin_scores[coin]['sources'].add('correlation')
            else:
                # Spesifik coin
                coin = signal.get('coin', '')
                if coin and coin in coin_scores:
                    existing = coin_scores[coin]['scores'].get('correlation', 0)
                    coin_scores[coin]['scores']['correlation'] = existing + score
                    coin_scores[coin]['sources'].add('correlation')

        # Global skorları tüm coinlere uygula
        if global_score != 0:
            for coin in coin_scores:
                existing = coin_scores[coin]['scores'].get('correlation', 0)
                coin_scores[coin]['scores']['correlation'] = existing + global_score
                coin_scores[coin]['sources'].add('correlation')
                for r in global_reasons[:1]:
                    coin_scores[coin]['reasons'].append(r)

    def _process_macro_scores(self, coin_scores: dict):
        """Makro skorlarını işle - global sinyaller tüm coinlere uygulanır"""
        global_score = 0.0
        global_reasons = []

        for signal in self._macro_buffer:
            applies_to = signal.get('applies_to', 'all')
            score = signal.get('signal_score', 0)
            reason = signal.get('reason', '')

            if applies_to == 'all':
                global_score += score
                if reason:
                    global_reasons.append(f"[makro] {reason}")

        if global_score != 0:
            for coin in coin_scores:
                existing = coin_scores[coin]['scores'].get('macro', 0)
                coin_scores[coin]['scores']['macro'] = existing + global_score
                coin_scores[coin]['sources'].add('macro')
                for r in global_reasons[:1]:
                    coin_scores[coin]['reasons'].append(r)

    def _calculate_weighted_score(self, data: dict) -> float:
        """Ağırlıklı final skor hesapla"""
        scores = data.get('scores', {})
        if not scores:
            return 0.0

        weighted_sum = 0.0
        total_weight = 0.0

        for source, score in scores.items():
            base_weight = self.SOURCE_WEIGHTS.get(source, 0.05)

            # Backtest kalibrasyonu: doğruluk oranına göre ağırlık ayarla
            calibration = self._source_calibration.get(source)
            if calibration is not None:
                # %50 altı doğruluk → ağırlığı düşür
                # %70+ doğruluk → ağırlığı artır
                base_weight *= (calibration / 0.5)

            weighted_sum += score * base_weight
            total_weight += base_weight

        if total_weight == 0:
            return 0.0

        return weighted_sum / total_weight
