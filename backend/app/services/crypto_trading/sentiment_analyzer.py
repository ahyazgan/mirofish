"""
LLM Tabanlı Kripto Haber Sentiment Analizi
MiroFish'in mevcut LLM altyapısını kullanarak haberlerin piyasa etkisini analiz eder.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI

from .config import CryptoTradingConfig
from .news_fetcher import NewsItem

logger = logging.getLogger('crypto_trading.sentiment')


@dataclass
class SentimentResult:
    """Sentiment analiz sonucu"""
    news_id: str
    coin: str
    sentiment: str          # 'bullish', 'bearish', 'neutral'
    score: float            # -1.0 (çok bearish) ile 1.0 (çok bullish) arası
    confidence: float       # 0.0 - 1.0 arası güven skoru
    impact: str             # 'high', 'medium', 'low'
    reasoning: str          # LLM'in açıklaması
    price_prediction: str   # 'up', 'down', 'sideways'
    timeframe: str          # 'short' (1-4h), 'medium' (1-3d), 'long' (1w+)
    analyzed_at: datetime = None

    def __post_init__(self):
        if self.analyzed_at is None:
            self.analyzed_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            'news_id': self.news_id,
            'coin': self.coin,
            'sentiment': self.sentiment,
            'score': self.score,
            'confidence': self.confidence,
            'impact': self.impact,
            'reasoning': self.reasoning,
            'price_prediction': self.price_prediction,
            'timeframe': self.timeframe,
            'analyzed_at': self.analyzed_at.isoformat(),
        }


SENTIMENT_SYSTEM_PROMPT = """Sen profesyonel bir kripto piyasa analisti ve trader'sın.
Görevin kripto para haberlerini analiz edip piyasa etkisini değerlendirmek.

Her haber için şunları belirle:
1. **sentiment**: "bullish" (yükseliş), "bearish" (düşüş) veya "neutral" (nötr)
2. **score**: -1.0 ile 1.0 arası sayısal skor (-1.0 = çok bearish, 1.0 = çok bullish)
3. **confidence**: 0.0 ile 1.0 arası güven skoru (analiz ne kadar güvenilir)
4. **impact**: "high", "medium" veya "low" - haberin piyasaya potansiyel etkisi
5. **reasoning**: Kısa analiz açıklaması (2-3 cümle)
6. **price_prediction**: "up", "down" veya "sideways"
7. **timeframe**: "short" (1-4 saat), "medium" (1-3 gün), "long" (1 hafta+)

Önemli kurallar:
- Regulasyon haberleri genelde kısa vadede bearish, uzun vadede duruma bağlı
- Büyük borsaların hack haberleri çok bearish
- Kurumsal yatırım haberleri bullish
- FUD (Fear, Uncertainty, Doubt) haberlerini gerçek haberlerden ayır
- Whale hareketleri dikkatle değerlendir
- Makroekonomik haberlerin kripto etkisini düşün (faiz kararları, enflasyon vb.)

JSON formatında yanıt ver."""

SENTIMENT_USER_PROMPT = """Aşağıdaki kripto haberini analiz et:

**Başlık**: {title}
**İçerik**: {body}
**Kaynak**: {source}
**İlgili Coinler**: {coins}
**Yayın Tarihi**: {published_at}

{coin_specific}

Yanıtını SADECE aşağıdaki JSON formatında ver, başka hiçbir şey ekleme:
{{
    "sentiment": "bullish|bearish|neutral",
    "score": <-1.0 ile 1.0 arası float>,
    "confidence": <0.0 ile 1.0 arası float>,
    "impact": "high|medium|low",
    "reasoning": "<2-3 cümle analiz>",
    "price_prediction": "up|down|sideways",
    "timeframe": "short|medium|long"
}}"""


class SentimentAnalyzer:
    """LLM tabanlı haber sentiment analiz motoru"""

    def __init__(self):
        self._client = OpenAI(
            api_key=CryptoTradingConfig.LLM_API_KEY,
            base_url=CryptoTradingConfig.LLM_BASE_URL,
        )
        self._model = CryptoTradingConfig.LLM_MODEL_NAME
        self._cache: dict[str, SentimentResult] = {}

    def analyze(self, news: NewsItem, target_coin: Optional[str] = None) -> list[SentimentResult]:
        """Tek bir haberi analiz et, her ilgili coin için sonuç döndür"""
        coins = [target_coin] if target_coin else (news.coins or ['GENERAL'])
        results = []

        for coin in coins:
            cache_key = f"{news.id}:{coin}"
            if cache_key in self._cache:
                results.append(self._cache[cache_key])
                continue

            try:
                result = self._analyze_single(news, coin)
                if result:
                    self._cache[cache_key] = result
                    results.append(result)
            except Exception as e:
                logger.error(f"Sentiment analiz hatası (news={news.id}, coin={coin}): {e}")

        return results

    def analyze_batch(self, news_list: list[NewsItem]) -> list[SentimentResult]:
        """Birden fazla haberi toplu analiz et"""
        all_results = []
        for news in news_list:
            results = self.analyze(news)
            all_results.extend(results)
        return all_results

    def _analyze_single(self, news: NewsItem, coin: str) -> Optional[SentimentResult]:
        """Tek haber + tek coin için LLM sentiment analizi"""
        coin_specific = ""
        if coin != 'GENERAL':
            coin_specific = f"Bu haberin özellikle **{coin}** üzerindeki etkisini analiz et."

        user_msg = SENTIMENT_USER_PROMPT.format(
            title=news.title,
            body=news.body[:800],
            source=news.source,
            coins=', '.join(news.coins) if news.coins else 'Genel Kripto',
            published_at=news.published_at.strftime('%Y-%m-%d %H:%M UTC'),
            coin_specific=coin_specific,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()

            # JSON parse - bazen LLM markdown code block içinde döndürür
            if content.startswith('```'):
                content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()

            data = json.loads(content)

            return SentimentResult(
                news_id=news.id,
                coin=coin,
                sentiment=data.get('sentiment', 'neutral'),
                score=max(-1.0, min(1.0, float(data.get('score', 0)))),
                confidence=max(0.0, min(1.0, float(data.get('confidence', 0.5)))),
                impact=data.get('impact', 'medium'),
                reasoning=data.get('reasoning', ''),
                price_prediction=data.get('price_prediction', 'sideways'),
                timeframe=data.get('timeframe', 'short'),
            )

        except json.JSONDecodeError as e:
            logger.error(f"LLM JSON parse hatası: {e}, raw: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"LLM API hatası: {e}")
            return None

    def get_aggregate_sentiment(self, coin: str, results: list[SentimentResult]) -> dict:
        """Bir coin için tüm sentiment sonuçlarını birleştir"""
        coin_results = [r for r in results if r.coin == coin]
        if not coin_results:
            return {'coin': coin, 'overall': 'neutral', 'avg_score': 0, 'count': 0}

        # Ağırlıklı ortalama (confidence * score)
        total_weight = sum(r.confidence for r in coin_results)
        if total_weight == 0:
            avg_score = 0
        else:
            avg_score = sum(r.score * r.confidence for r in coin_results) / total_weight

        high_impact_count = sum(1 for r in coin_results if r.impact == 'high')

        if avg_score > 0.3:
            overall = 'bullish'
        elif avg_score < -0.3:
            overall = 'bearish'
        else:
            overall = 'neutral'

        return {
            'coin': coin,
            'overall': overall,
            'avg_score': round(avg_score, 3),
            'count': len(coin_results),
            'high_impact_count': high_impact_count,
            'details': [r.to_dict() for r in coin_results],
        }

    def clear_cache(self):
        self._cache.clear()
