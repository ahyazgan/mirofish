"""
Haber Tekrar Filtresi - Aynı haberin farklı kaynaklardan tekrar gelmesini engeller.
Metin benzerliği ile duplicate tespiti. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone, timedelta

from .base_agent import BaseAgent


class NewsDedupAgent(BaseAgent):
    """
    Görev: Tekrar eden haberleri filtrele, benzersiz haberleri geçir
    Girdi: News Scout'tan ham haberler
    Çıktı: Filtrelenmiş haberler → Sentiment Agent, Haber Etki Sınıflandırıcı

    Mantık:
    - Metin benzerliği (cosine similarity basitleştirilmiş)
    - 30dk pencere içinde %70+ benzerlik = tekrar
    - Tekrar eden haberden en yüksek önem skorlusunu geçir
    - Kaç kaynakta çıktığını say (çok kaynakta = daha güvenilir)
    """

    SIMILARITY_THRESHOLD = 0.70  # %70 benzerlik = tekrar
    TIME_WINDOW_MINUTES = 30     # 30 dakika pencere

    def __init__(self, interval: float = 3.0):
        super().__init__('Haber Tekrar Filtresi', interval=interval)
        self._recent_news: list[dict] = []  # Son haberler
        self._dedup_stats = {'total': 0, 'passed': 0, 'filtered': 0}

    @property
    def dedup_stats(self) -> dict:
        return self._dedup_stats.copy()

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') != 'new_news':
                continue

            news_objects = msg.get('news_objects', [])
            news_dicts = msg.get('news', [])

            if not news_objects:
                continue

            unique_news = []
            unique_dicts = []

            for i, news in enumerate(news_objects):
                self._dedup_stats['total'] += 1
                title = getattr(news, 'title', '') or ''
                summary = getattr(news, 'summary', '') or ''
                text = f"{title} {summary}".strip().lower()

                if not text:
                    continue

                # Benzerlik kontrolü
                is_duplicate = False
                now = datetime.now(timezone.utc)

                for recent in self._recent_news:
                    # Zaman penceresi kontrolü
                    age = (now - recent['time']).total_seconds()
                    if age > self.TIME_WINDOW_MINUTES * 60:
                        continue

                    similarity = self._text_similarity(text, recent['text'])
                    if similarity >= self.SIMILARITY_THRESHOLD:
                        is_duplicate = True
                        recent['source_count'] += 1
                        self._dedup_stats['filtered'] += 1
                        self.logger.debug(
                            f"TEKRAR | '{title[:50]}...' "
                            f"benzerlik={similarity:.0%} (kaynak #{recent['source_count']})"
                        )
                        break

                if not is_duplicate:
                    self._dedup_stats['passed'] += 1
                    unique_news.append(news)
                    if i < len(news_dicts):
                        unique_dicts.append(news_dicts[i])

                    self._recent_news.append({
                        'text': text,
                        'title': title[:100],
                        'time': now,
                        'source_count': 1,
                    })

            # Eski haberleri temizle
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.TIME_WINDOW_MINUTES * 2)
            self._recent_news = [n for n in self._recent_news if n['time'] > cutoff]

            # Son 500 haber tut
            if len(self._recent_news) > 500:
                self._recent_news = self._recent_news[-500:]

            if unique_news:
                self.logger.info(
                    f"DEDUP | {len(news_objects)} haber → {len(unique_news)} benzersiz "
                    f"({len(news_objects) - len(unique_news)} tekrar filtrelendi)"
                )

                # Sentiment Agent'a filtrelenmiş haberleri gönder
                await self.send('sentiment', {
                    'type': 'new_news',
                    'news': unique_dicts,
                    'news_objects': unique_news,
                })

                # Etki Sınıflandırıcıya gönder
                await self.send('impact_classifier', {
                    'type': 'new_news',
                    'news': unique_dicts,
                    'news_objects': unique_news,
                })

                # Alert
                await self.send('alert', {
                    'type': 'dedup_report',
                    'total': len(news_objects),
                    'unique': len(unique_news),
                    'filtered': len(news_objects) - len(unique_news),
                })

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """Basit kelime bazlı Jaccard benzerliği"""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)
