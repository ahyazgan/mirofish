"""
Sentiment Agent - LLM ile haber analizi
News Scout'tan gelen haberleri analiz eder, sonuçları Signal Strategist'e gönderir.
"""

from .base_agent import BaseAgent
from ..sentiment_analyzer import SentimentAnalyzer


class SentimentAgent(BaseAgent):
    """
    Görev: Haberleri LLM ile analiz et, sentiment skoru üret
    Girdi: News Scout'tan haberler
    Çıktı: Sentiment sonuçları → Signal Strategist'e
    """

    def __init__(self, interval: float = 5.0):
        super().__init__('Duygu Analizcisi', interval=interval)
        self.analyzer = SentimentAnalyzer()

    async def run_cycle(self):
        messages = await self.receive_all()
        if not messages:
            return

        for msg in messages:
            if msg.get('type') != 'new_news':
                continue

            news_objects = msg.get('news_objects', [])
            if not news_objects:
                continue

            self.logger.info(f"{len(news_objects)} haber analiz ediliyor...")

            all_results = []
            for news in news_objects:
                for coin in news.coins[:3]:  # Her haberde max 3 coin analiz et
                    results = self.analyzer.analyze(news, target_coin=coin)
                    all_results.extend(results)

            if all_results:
                self.logger.info(f"{len(all_results)} sentiment sonucu üretildi")

                # Signal Strategist'e gönder
                await self.send('strategist', {
                    'type': 'sentiment_results',
                    'results': [r.to_dict() for r in all_results],
                    'result_objects': all_results,
                })

                # Alert Agent'a bildir
                bullish = sum(1 for r in all_results if r.sentiment == 'bullish')
                bearish = sum(1 for r in all_results if r.sentiment == 'bearish')
                await self.send('alert', {
                    'type': 'sentiment_complete',
                    'total': len(all_results),
                    'bullish': bullish,
                    'bearish': bearish,
                })
