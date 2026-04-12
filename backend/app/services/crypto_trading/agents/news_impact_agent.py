"""
Haber Etki Sınıflandırıcı - Haberin potansiyel piyasa etkisini sınıflandırır.
Keyword bazlı sınıflandırma. Tamamen yerel - ek maliyet yok.
"""

import re
from datetime import datetime, timezone

from .base_agent import BaseAgent


class NewsImpactAgent(BaseAgent):
    """
    Görev: Haberin piyasa etkisini sınıflandır, öncelik belirle
    Girdi: Haber Tekrar Filtresi'nden benzersiz haberler
    Çıktı: Sınıflandırılmış haberler → Strategist (öncelikli), Alert

    Sınıflar:
    - CRITICAL: ETF onayı, ban, hack, borsa çöküşü → Anında aksiyon
    - HIGH: Listeleme, ortaklık, büyük yatırım → Hızlı aksiyon
    - MEDIUM: Güncelleme, roadmap, rapor → Normal aksiyon
    - LOW: Yorum, tahmin, analiz → İzle
    - NOISE: Spam, reklam, alakasız → Atla
    """

    # Anahtar kelime → etki seviyesi mapping
    CRITICAL_KEYWORDS = {
        # Düzenleyici
        'etf approved', 'etf rejected', 'etf onay', 'etf red',
        'ban crypto', 'kripto yasak', 'crypto ban',
        'sec lawsuit', 'sec dava', 'sec charges',
        # Güvenlik
        'hack', 'exploit', 'stolen', 'breach', 'saldırı',
        'exchange down', 'borsa çöktü', 'insolvent', 'iflas',
        'bankrupt', 'collapsed', 'ponzi',
        # Büyük hareket
        'emergency', 'acil', 'flash crash', 'black swan',
        'halving', 'hard fork',
    }

    HIGH_KEYWORDS = {
        # Listeleme
        'listing', 'listeleme', 'listed on', 'delist', 'delisting',
        'coinbase listing', 'binance listing',
        # Büyük yatırım
        'institutional', 'kurumsal', 'billion', 'milyar',
        'blackrock', 'fidelity', 'grayscale', 'microstrategy',
        'tesla', 'acquisition', 'satın alma',
        # Ortaklık
        'partnership', 'ortaklık', 'collaboration', 'integration',
        # Piyasa yapısı
        'short squeeze', 'liquidation cascade', 'margin call',
        'all time high', 'ath', 'record high',
    }

    MEDIUM_KEYWORDS = {
        # Teknik
        'upgrade', 'güncelleme', 'mainnet', 'testnet',
        'roadmap', 'milestone', 'launch', 'release',
        'airdrop', 'staking', 'yield',
        # Piyasa
        'rally', 'surge', 'pump', 'dump', 'correction',
        'bullish', 'bearish', 'breakout', 'breakdown',
        'support', 'resistance', 'destek', 'direnç',
        # Genel
        'regulation', 'düzenleme', 'compliance',
        'whale', 'balina', 'large transfer',
    }

    LOW_KEYWORDS = {
        'prediction', 'tahmin', 'forecast', 'opinion',
        'analyst says', 'analist', 'could', 'might', 'may',
        'report', 'rapor', 'survey', 'anket',
        'interview', 'röportaj', 'comment', 'yorum',
    }

    NOISE_KEYWORDS = {
        'sponsored', 'reklam', 'advertisement', 'promoted',
        'giveaway', 'çekiliş', 'free crypto', 'airdrop hunter',
        'click here', 'sign up', 'referral',
    }

    # Etki seviyesine göre beklenen fiyat hareketi
    IMPACT_ESTIMATES = {
        'CRITICAL': {'min_pct': 5.0, 'max_pct': 50.0, 'speed': 'instant'},
        'HIGH': {'min_pct': 2.0, 'max_pct': 20.0, 'speed': 'fast'},
        'MEDIUM': {'min_pct': 0.5, 'max_pct': 5.0, 'speed': 'normal'},
        'LOW': {'min_pct': 0.0, 'max_pct': 1.0, 'speed': 'slow'},
        'NOISE': {'min_pct': 0.0, 'max_pct': 0.0, 'speed': 'none'},
    }

    def __init__(self, interval: float = 3.0):
        super().__init__('Haber Etki Siniflandirici', interval=interval)
        self._classification_stats: dict[str, int] = {
            'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'NOISE': 0,
        }

    @property
    def impact_stats(self) -> dict:
        return self._classification_stats.copy()

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') != 'new_news':
                continue

            news_objects = msg.get('news_objects', [])
            if not news_objects:
                continue

            for news in news_objects:
                title = getattr(news, 'title', '') or ''
                summary = getattr(news, 'summary', '') or ''
                source = getattr(news, 'source', '') or ''
                coins = getattr(news, 'coins', []) or []

                classification = self._classify(title, summary)
                impact_class = classification['class']
                self._classification_stats[impact_class] += 1

                # NOISE atla
                if impact_class == 'NOISE':
                    continue

                # LOW sadece logla
                if impact_class == 'LOW':
                    self.logger.debug(f"LOW | {title[:60]}")
                    continue

                # MEDIUM ve üstü → Strategist'e sinyal olarak gönder
                impact_data = self.IMPACT_ESTIMATES[impact_class]

                await self.send('strategist', {
                    'type': 'news_impact_signal',
                    'coins': coins,
                    'impact_class': impact_class,
                    'confidence': classification['confidence'],
                    'matched_keywords': classification['keywords'],
                    'expected_move_pct': impact_data['min_pct'],
                    'speed': impact_data['speed'],
                    'title': title[:200],
                    'source': source,
                })

                # CRITICAL ve HIGH → Alert'e de gönder
                if impact_class in ('CRITICAL', 'HIGH'):
                    await self.send('alert', {
                        'type': 'high_impact_news',
                        'impact_class': impact_class,
                        'title': title[:200],
                        'coins': coins,
                        'confidence': classification['confidence'],
                    })

                    self.logger.info(
                        f"{impact_class} | {title[:80]} "
                        f"coins={','.join(coins[:3])} conf={classification['confidence']:.0%}"
                    )

    def _classify(self, title: str, summary: str) -> dict:
        """Haberi sınıflandır"""
        text = f"{title} {summary}".lower()

        # Her seviye için eşleşen keyword sayısını hesapla
        critical_matches = self._count_matches(text, self.CRITICAL_KEYWORDS)
        high_matches = self._count_matches(text, self.HIGH_KEYWORDS)
        medium_matches = self._count_matches(text, self.MEDIUM_KEYWORDS)
        low_matches = self._count_matches(text, self.LOW_KEYWORDS)
        noise_matches = self._count_matches(text, self.NOISE_KEYWORDS)

        # Noise kontrolü önce
        if noise_matches['count'] > 0:
            return {'class': 'NOISE', 'confidence': 0.9, 'keywords': noise_matches['keywords']}

        # En yüksek eşleşme kazanır
        levels = [
            ('CRITICAL', critical_matches),
            ('HIGH', high_matches),
            ('MEDIUM', medium_matches),
            ('LOW', low_matches),
        ]

        best_class = 'LOW'
        best_count = 0
        best_keywords = []

        for level_name, matches in levels:
            if matches['count'] > best_count:
                best_class = level_name
                best_count = matches['count']
                best_keywords = matches['keywords']
            elif matches['count'] == best_count and matches['count'] > 0:
                # Eşitlikte üst seviye kazanır
                level_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
                if level_order.index(level_name) < level_order.index(best_class):
                    best_class = level_name
                    best_keywords = matches['keywords']

        # Confidence: eşleşen keyword sayısına göre
        confidence = min(0.5 + best_count * 0.15, 0.95)

        return {
            'class': best_class,
            'confidence': round(confidence, 2),
            'keywords': best_keywords[:5],
        }

    @staticmethod
    def _count_matches(text: str, keywords: set) -> dict:
        """Metin içinde kaç keyword eşleşiyor"""
        matched = []
        for kw in keywords:
            if kw in text:
                matched.append(kw)
        return {'count': len(matched), 'keywords': matched}
