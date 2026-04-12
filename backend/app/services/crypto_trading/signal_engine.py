"""
Trading Sinyal Motoru
Sentiment analizi + fiyat verisi + teknik göstergeler birleştirilerek
al/sat/bekle sinyalleri üretilir.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .config import CryptoTradingConfig
from .news_fetcher import NewsAggregator, NewsItem
from .price_service import PriceData, PriceService
from .sentiment_analyzer import SentimentAnalyzer, SentimentResult

logger = logging.getLogger('crypto_trading.signal')


class SignalAction(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'


class SignalStrength(str, Enum):
    STRONG = 'STRONG'
    MODERATE = 'MODERATE'
    WEAK = 'WEAK'


@dataclass
class TradingSignal:
    """Trading sinyali"""
    id: str
    coin: str
    action: SignalAction
    strength: SignalStrength
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_usdt: float
    sentiment_score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)
    news_ids: list[str] = field(default_factory=list)
    created_at: datetime = None
    executed: bool = False

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            'id': self.id,
            'coin': self.coin,
            'action': self.action.value,
            'strength': self.strength.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'position_size_usdt': self.position_size_usdt,
            'sentiment_score': self.sentiment_score,
            'confidence': self.confidence,
            'reasons': self.reasons,
            'news_ids': self.news_ids,
            'created_at': self.created_at.isoformat(),
            'executed': self.executed,
        }


class SignalEngine:
    """
    Sinyal üretim motoru.
    Haber → Sentiment → Fiyat → Sinyal pipeline'ı yönetir.
    """

    def __init__(self):
        self.news_aggregator = NewsAggregator()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.price_service = PriceService()
        self._signal_history: list[TradingSignal] = []
        self._signal_counter = 0

    async def generate_signals(self) -> list[TradingSignal]:
        """Ana sinyal üretim döngüsü - haberlerde geçen TÜM coinleri dinamik trade eder"""
        signals = []

        # 1. Haberleri topla
        news_items = await self.news_aggregator.fetch_all()
        if not news_items:
            logger.info("Yeni haber yok, sinyal üretilmedi")
            return signals

        # 2. Haberlerde geçen tüm coinleri bul (dinamik - Binance'deki her coin)
        detected_coins: dict[str, list] = {}
        for news in news_items:
            for coin in news.coins:
                coin = coin.strip().upper()
                if coin not in detected_coins:
                    detected_coins[coin] = []
                detected_coins[coin].append(news)

        if not detected_coins:
            logger.info("Haberlerde coin tespit edilemedi")
            return signals

        logger.info(f"Haberlerde {len(detected_coins)} farklı coin tespit edildi: "
                    f"{', '.join(list(detected_coins.keys())[:20])}")

        # 3. Tespit edilen coinlerin fiyatlarını al
        coin_list = list(detected_coins.keys())
        prices = await self.price_service.get_prices(coin_list, force=True)

        # 4. Her coin için sentiment analizi ve sinyal değerlendirmesi
        for coin, coin_news in detected_coins.items():
            price_data = prices.get(coin)
            if not price_data:
                continue

            # Sentiment analizi (en fazla 5 haber - maliyet kontrolü)
            sentiment_results = []
            for news in coin_news[:5]:
                results = self.sentiment_analyzer.analyze(news, target_coin=coin)
                sentiment_results.extend(results)

            if not sentiment_results:
                continue

            # Aggregate sentiment
            agg = self.sentiment_analyzer.get_aggregate_sentiment(coin, sentiment_results)

            # Sinyal üret
            signal = self._evaluate_signal(coin, price_data, agg, sentiment_results, coin_news)
            if signal:
                signals.append(signal)
                self._signal_history.append(signal)
                logger.info(f"Sinyal üretildi: {signal.coin} {signal.action.value} "
                           f"(strength={signal.strength.value}, score={signal.sentiment_score})")

        return signals

    def _evaluate_signal(
        self,
        coin: str,
        price: PriceData,
        aggregate: dict,
        sentiments: list[SentimentResult],
        news: list[NewsItem],
    ) -> Optional[TradingSignal]:
        """Sentiment + fiyat verisini birleştirip sinyal üret"""
        avg_score = aggregate['avg_score']
        high_impact = aggregate['high_impact_count']
        overall = aggregate['overall']

        # Minimum sentiment eşiği kontrolü
        if abs(avg_score) < CryptoTradingConfig.MIN_SENTIMENT_SCORE:
            return None

        # Aksiyon belirleme
        if avg_score > 0:
            action = SignalAction.BUY
        elif avg_score < 0:
            action = SignalAction.SELL
        else:
            return None

        # Sinyal gücü belirleme
        if abs(avg_score) > 0.8 and high_impact > 0:
            strength = SignalStrength.STRONG
        elif abs(avg_score) > 0.5:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Fiyat bazlı filtreler
        reasons = []

        # Momentum kontrolü - fiyat trendi ile sentiment uyumlu mu?
        if action == SignalAction.BUY and price.change_1h < -5:
            reasons.append(f"Dikkat: Son 1 saatte %{price.change_1h} düşüş var, dip alım fırsatı olabilir")
        elif action == SignalAction.SELL and price.change_1h > 5:
            reasons.append(f"Dikkat: Son 1 saatte %{price.change_1h} yükseliş var, zirve satışı olabilir")

        # Sentiment kaynaklı sebepler
        for s in sentiments[:3]:
            reasons.append(f"[{s.impact}] {s.reasoning}")

        # Pozisyon büyüklüğü (sinyal gücüne göre)
        base_size = CryptoTradingConfig.MAX_POSITION_SIZE
        if strength == SignalStrength.STRONG:
            position_size = base_size
        elif strength == SignalStrength.MODERATE:
            position_size = base_size * 0.6
        else:
            position_size = base_size * 0.3

        # Stop-loss ve take-profit hesaplama
        entry_price = price.price
        sl_pct = CryptoTradingConfig.STOP_LOSS_PCT / 100
        tp_pct = CryptoTradingConfig.TAKE_PROFIT_PCT / 100

        if action == SignalAction.BUY:
            stop_loss = entry_price * (1 - sl_pct)
            take_profit = entry_price * (1 + tp_pct)
        else:
            stop_loss = entry_price * (1 + sl_pct)
            take_profit = entry_price * (1 - tp_pct)

        # Güven skoru: sentiment confidence ortalaması
        avg_confidence = sum(s.confidence for s in sentiments) / len(sentiments) if sentiments else 0

        self._signal_counter += 1
        signal_id = f"SIG-{self._signal_counter:06d}"

        return TradingSignal(
            id=signal_id,
            coin=coin,
            action=action,
            strength=strength,
            entry_price=round(entry_price, 8),
            stop_loss=round(stop_loss, 8),
            take_profit=round(take_profit, 8),
            position_size_usdt=round(position_size, 2),
            sentiment_score=round(avg_score, 3),
            confidence=round(avg_confidence, 3),
            reasons=reasons,
            news_ids=[n.id for n in news[:5]],
        )

    def get_signal_history(self, limit: int = 50) -> list[dict]:
        """Sinyal geçmişi"""
        return [s.to_dict() for s in self._signal_history[-limit:]]

    def get_active_signals(self) -> list[TradingSignal]:
        """Henüz execute edilmemiş sinyaller"""
        return [s for s in self._signal_history if not s.executed]

    def mark_executed(self, signal_id: str):
        """Sinyali execute edildi olarak işaretle"""
        for s in self._signal_history:
            if s.id == signal_id:
                s.executed = True
                break
