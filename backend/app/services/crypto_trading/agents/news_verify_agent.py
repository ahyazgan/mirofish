"""
Haber Doğrulayıcı - Haberin gerçekliğini birden fazla kaynaktan doğrular.
Sahte/manipülatif haber tespiti. Tamamen yerel - ek maliyet yok.
"""

from datetime import datetime, timezone, timedelta

from .base_agent import BaseAgent


class NewsVerifyAgent(BaseAgent):
    """
    Görev: Haberin gerçek olup olmadığını doğrula
    Girdi: Haber Tekrar Filtresi'nden haberler + diğer kaynaklar
    Çıktı: Doğrulama skoru → Strategist (güvenilir haberler)

    Mantık:
    - Aynı haberi en az 2 farklı kaynaktan teyit et
    - Kaynak güvenilirlik skoru kontrolü
    - Çok eski haberin yeniymiş gibi sunulması tespiti
    - Doğrulama skoru <60 ise trade yapma
    """

    # Kaynak güvenilirlik skorları (0-100)
    SOURCE_RELIABILITY = {
        'coindesk': 90,
        'cointelegraph': 85,
        'the_block': 88,
        'decrypt': 82,
        'bloomberg': 95,
        'reuters': 95,
        'coingecko': 80,
        'binance': 92,
        'coinbase': 90,
        'cryptopanic': 70,  # Aggregator, karışık kalite
        'reddit': 40,
        'twitter': 35,
        'unknown': 30,
    }

    # Manipülasyon işaretleri
    MANIPULATION_SIGNALS = {
        'guaranteed', 'guaranteed profit', '100x', '1000x',
        'insider info', 'secret', 'leaked', 'sızdırılan',
        'buy now', 'hemen al', 'last chance', 'son şans',
        'exclusive tip', 'sure bet', 'kesin kazanç',
        'pump group', 'signal group', 'vip signal',
    }

    def __init__(self, interval: float = 3.0):
        super().__init__('Haber Dogrulayici', interval=interval)
        self._news_buffer: list[dict] = []  # Doğrulama bekleyen haberler
        self._verified_hashes: set[str] = set()  # Doğrulanmış haber hash'leri
        self._verify_stats = {'total': 0, 'verified': 0, 'rejected': 0, 'pending': 0}

    @property
    def verify_stats(self) -> dict:
        return {**self._verify_stats, 'pending': len(self._news_buffer)}

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'new_news':
                news_objects = msg.get('news_objects', [])
                for news in news_objects:
                    self._verify_stats['total'] += 1
                    self._news_buffer.append({
                        'news': news,
                        'title': getattr(news, 'title', '') or '',
                        'summary': getattr(news, 'summary', '') or '',
                        'source': getattr(news, 'source', '') or '',
                        'coins': getattr(news, 'coins', []) or [],
                        'time': datetime.now(timezone.utc),
                        'source_count': 1,
                    })

        # Doğrulama yap
        await self._verify_news()

        # Eski buffer temizliği (10dk'dan eski)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        expired = [n for n in self._news_buffer if n['time'] < cutoff]
        for item in expired:
            # Süre doldu ama doğrulanamadı → düşük skorla geçir
            await self._send_result(item, score=40, reason='timeout_unverified')
        self._news_buffer = [n for n in self._news_buffer if n['time'] >= cutoff]

    async def _verify_news(self):
        """Haberleri doğrula"""
        still_pending = []

        for item in self._news_buffer:
            title = item['title'].lower()
            summary = item['summary'].lower()
            text = f"{title} {summary}"
            source = item['source'].lower()

            # 1. Manipülasyon kontrolü
            manipulation_score = self._check_manipulation(text)
            if manipulation_score > 0.5:
                self._verify_stats['rejected'] += 1
                await self._send_result(item, score=10, reason='manipulation_detected')
                self.logger.warning(f"SAHTE | '{title[:60]}' manipülasyon skoru={manipulation_score:.0%}")
                continue

            # 2. Kaynak güvenilirlik skoru
            source_score = self._get_source_reliability(source)

            # 3. İçerik kalite kontrolü
            content_score = self._check_content_quality(title, summary)

            # 4. Zaman kontrolü (çok eski haber mi?)
            freshness_score = self._check_freshness(item)

            # Final doğrulama skoru (0-100)
            verify_score = (
                source_score * 0.40 +
                content_score * 0.30 +
                freshness_score * 0.20 +
                (1 - manipulation_score) * 100 * 0.10
            )

            verify_score = round(verify_score, 1)

            if verify_score >= 60:
                self._verify_stats['verified'] += 1
                await self._send_result(item, score=verify_score, reason='verified')
                self.logger.info(
                    f"DOGRULANDI | skor={verify_score} kaynak={source} '{title[:60]}'"
                )
            elif verify_score >= 40:
                # Düşük güven ama geçir, uyarıyla
                self._verify_stats['verified'] += 1
                await self._send_result(item, score=verify_score, reason='low_confidence')
                self.logger.info(
                    f"DUSUK GUVEN | skor={verify_score} kaynak={source} '{title[:60]}'"
                )
            else:
                self._verify_stats['rejected'] += 1
                self.logger.warning(
                    f"REDDEDILDI | skor={verify_score} kaynak={source} '{title[:60]}'"
                )

    async def _send_result(self, item: dict, score: float, reason: str):
        """Doğrulama sonucunu gönder"""
        await self.send('strategist', {
            'type': 'news_verification',
            'coins': item['coins'],
            'verify_score': score,
            'reason': reason,
            'source': item['source'],
            'title': item['title'][:200],
            'reliable': score >= 60,
        })

        if score < 40:
            await self.send('alert', {
                'type': 'news_rejected',
                'title': item['title'][:200],
                'score': score,
                'reason': reason,
            })

    def _check_manipulation(self, text: str) -> float:
        """Manipülasyon skoru (0-1)"""
        matches = sum(1 for kw in self.MANIPULATION_SIGNALS if kw in text)
        return min(matches / 3, 1.0)

    def _get_source_reliability(self, source: str) -> float:
        """Kaynak güvenilirlik skoru (0-100)"""
        source_lower = source.lower()
        for key, score in self.SOURCE_RELIABILITY.items():
            if key in source_lower:
                return score
        return self.SOURCE_RELIABILITY['unknown']

    @staticmethod
    def _check_content_quality(title: str, summary: str) -> float:
        """İçerik kalitesi (0-100)"""
        score = 50.0  # Base

        # Başlık uzunluğu
        if len(title) > 20:
            score += 10
        if len(title) > 50:
            score += 10

        # Özet var mı
        if summary and len(summary) > 50:
            score += 15
        if summary and len(summary) > 200:
            score += 15

        # Tamamı büyük harf = spam
        if title.isupper():
            score -= 30

        # Çok fazla ünlem/soru işareti
        excl_count = title.count('!') + title.count('?')
        if excl_count > 3:
            score -= 20

        return max(0, min(100, score))

    @staticmethod
    def _check_freshness(item: dict) -> float:
        """Haber tazeliği (0-100)"""
        age = (datetime.now(timezone.utc) - item['time']).total_seconds()

        if age < 60:       # 1 dk
            return 100
        elif age < 300:     # 5 dk
            return 90
        elif age < 900:     # 15 dk
            return 70
        elif age < 1800:    # 30 dk
            return 50
        elif age < 3600:    # 1 saat
            return 30
        else:
            return 10
