"""
Regülasyon Takipcisi - SEC, CFTC, AB MiCA kararlarını izler.
RSS feed ve haber API'leri ile düzenleyici gelişmeleri takip eder.
Ücretsiz - ek maliyet yok.
"""

import httpx
import re
from datetime import datetime, timezone

from .base_agent import BaseAgent


class RegulationAgent(BaseAgent):
    """
    Görev: Düzenleyici kurumların kripto ile ilgili kararlarını izle
    Girdi: SEC, CFTC RSS/haber akışları, CryptoPanic regülasyon filtresi
    Çıktı: Regülasyon sinyalleri → Strategist, Alert (yüksek öncelik)

    Mantık:
    - ETF onayı/reddi → Çok büyük fiyat hareketi
    - Kripto yasağı → Sert düşüş
    - Yeni düzenleme → Belirsizlik, genelde bearish
    - Olumlu düzenleme (açıklık) → Bullish
    """

    # Regülasyon haber kaynakları
    CRYPTOPANIC_REG_URL = 'https://cryptopanic.com/api/free/v1/posts/'
    SEC_RSS_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=&dateb=&owner=include&count=20&search_text=bitcoin&action=getcompany'

    # Olumlu regülasyon kelimeleri
    POSITIVE_KEYWORDS = {
        'approved', 'approval', 'onay', 'cleared', 'green light',
        'framework', 'clarity', 'guideline', 'supportive',
        'adoption', 'legal tender', 'yasal',
        'etf approved', 'license granted', 'regulated exchange',
    }

    # Olumsuz regülasyon kelimeleri
    NEGATIVE_KEYWORDS = {
        'ban', 'banned', 'yasak', 'yasakladı', 'prohibited',
        'crackdown', 'enforcement', 'lawsuit', 'dava', 'sued',
        'fine', 'penalty', 'ceza', 'sanction',
        'rejected', 'denied', 'reddedildi', 'red',
        'investigation', 'soruşturma', 'probe',
        'warning', 'uyarı', 'fraud', 'dolandırıcılık',
        'shutdown', 'kapatma', 'cease and desist',
    }

    # Düzenleyici kurumlar (yüksek etki)
    HIGH_IMPACT_ENTITIES = {
        'sec', 'cftc', 'fed', 'federal reserve',
        'treasury', 'doj', 'department of justice',
        'eu', 'european', 'mica', 'esma',
        'china', 'pboc', 'çin',
        'japan', 'fsa', 'japonya',
        'uk', 'fca', 'ingiltere',
        'turkey', 'spk', 'türkiye', 'bddk', 'tcmb',
    }

    def __init__(self, interval: float = 300.0):  # 5 dakikada bir
        super().__init__('Regulasyon Takipcisi', interval=interval)
        self._seen_ids: set[str] = set()
        self._reg_events: list[dict] = []

    @property
    def regulation_stats(self) -> dict:
        return {
            'total_events': len(self._reg_events),
            'recent': self._reg_events[-5:],
        }

    async def run_cycle(self):
        await self.receive_all()

        signals = []

        # CryptoPanic'ten regülasyon haberleri
        reg_news = await self._fetch_regulation_news()
        for news in reg_news:
            signal = self._analyze_regulation(news)
            if signal:
                signals.append(signal)
                self._reg_events.append(signal)

        # Son 200 olay tut
        if len(self._reg_events) > 200:
            self._reg_events = self._reg_events[-200:]

        if signals:
            await self.send('strategist', {
                'type': 'regulation_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'regulation_alert',
                'count': len(signals),
                'events': [{'title': s.get('title', ''), 'impact': s.get('impact', '')} for s in signals],
            })

            for s in signals[:3]:
                self.logger.info(
                    f"REGULASYON | [{s.get('impact', '?')}] {s.get('title', '')[:60]} "
                    f"score={s['signal_score']}"
                )

    async def _fetch_regulation_news(self) -> list[dict]:
        """Regülasyon haberlerini çek"""
        news = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # CryptoPanic filter=regulation
                resp = await client.get(
                    self.CRYPTOPANIC_REG_URL,
                    params={
                        'auth_token': 'free',
                        'filter': 'important',
                        'kind': 'news',
                    }
                )
                if resp.status_code != 200:
                    return news

                data = resp.json()
                for item in data.get('results', []):
                    post_id = str(item.get('id', ''))
                    if post_id in self._seen_ids:
                        continue
                    self._seen_ids.add(post_id)

                    title = item.get('title', '')
                    # Regülasyon ile ilgili mi kontrol et
                    text_lower = title.lower()
                    is_regulation = any(
                        kw in text_lower for kw in
                        list(self.POSITIVE_KEYWORDS)[:10] +
                        list(self.NEGATIVE_KEYWORDS)[:10] +
                        list(self.HIGH_IMPACT_ENTITIES)[:10]
                    )

                    if is_regulation:
                        coins = []
                        currencies = item.get('currencies', [])
                        if currencies:
                            coins = [c.get('code', '') for c in currencies if c.get('code')]

                        news.append({
                            'id': post_id,
                            'title': title,
                            'source': item.get('source', {}).get('title', 'unknown'),
                            'coins': coins or ['MARKET'],
                            'url': item.get('url', ''),
                            'created_at': item.get('created_at', ''),
                        })

        except Exception as e:
            self.logger.debug(f"Regulation news fetch hatası: {e}")

        # Seen ID cleanup
        if len(self._seen_ids) > 5000:
            self._seen_ids = set(list(self._seen_ids)[-2500:])

        return news[:10]

    def _analyze_regulation(self, news: dict) -> dict | None:
        """Regülasyon haberini analiz et"""
        title = news.get('title', '').lower()
        coins = news.get('coins', ['MARKET'])

        # Sentiment analizi
        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in title)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in title)

        if positive_count == 0 and negative_count == 0:
            return None

        # Yüksek etkili kurum mu?
        is_high_impact = any(entity in title for entity in self.HIGH_IMPACT_ENTITIES)

        # Skor hesapla
        base_score = (positive_count - negative_count) * 0.2
        if is_high_impact:
            base_score *= 2  # Yüksek etkili kurum = 2x etki

        # Impact seviyesi
        if is_high_impact and abs(base_score) >= 0.3:
            impact = 'CRITICAL'
        elif abs(base_score) >= 0.2:
            impact = 'HIGH'
        else:
            impact = 'MEDIUM'

        signal_score = max(-1.0, min(1.0, base_score))

        return {
            'coins': coins,
            'coin': coins[0] if coins else 'MARKET',
            'title': news.get('title', ''),
            'source': news.get('source', ''),
            'impact': impact,
            'sentiment': 'positive' if signal_score > 0 else 'negative',
            'signal_score': round(signal_score, 3),
            'applies_to': 'all' if 'MARKET' in coins else coins[0],
            'reason': f"Regülasyon: {news.get('title', '')[:80]}",
            'source_type': 'regulation',
            'time': datetime.now(timezone.utc).isoformat(),
        }
