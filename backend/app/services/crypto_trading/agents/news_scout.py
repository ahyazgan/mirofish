"""
News Scout Agent - Haber keşifçisi
4 kaynaktan haberleri sürekli tarar, yeni haber bulunca Sentiment Agent'a gönderir.
"""

from .base_agent import BaseAgent
from ..news_fetcher import NewsAggregator


class NewsScoutAgent(BaseAgent):
    """
    Görev: Sürekli haber kaynakları tara, yeni haberleri tespit et
    Çıktı: Yeni haberler → Sentiment Agent'a gönderir
    """

    def __init__(self, interval: float = 60.0):
        super().__init__('Haber Kesfedici', interval=interval)
        self.aggregator = NewsAggregator()
        self._processed_ids: set[str] = set()

    async def run_cycle(self):
        news_items = await self.aggregator.fetch_all(force=True)

        new_items = []
        for item in news_items:
            if item.id not in self._processed_ids:
                self._processed_ids.add(item.id)
                new_items.append(item)

        if new_items:
            self.logger.info(f"{len(new_items)} yeni haber bulundu")
            # News Dedup'a gönder (tekrar filtresi → sentiment → strategist)
            await self.send('news_dedup', {
                'type': 'new_news',
                'news': [n.to_dict() for n in new_items],
                'news_objects': new_items,
            })
            # Alert Agent'a bildir
            await self.send('alert', {
                'type': 'news_found',
                'count': len(new_items),
                'coins': list(set(c for n in new_items for c in n.coins)),
            })
        else:
            self.logger.debug("Yeni haber yok")
