"""
Social Media Agent - Reddit kripto sentiment analizi
Reddit API ücretsiz (public JSON endpoint).
Ek maliyet yok.
"""

import httpx
import re
from datetime import datetime, timezone

from .base_agent import BaseAgent


class SocialMediaAgent(BaseAgent):
    """
    Görev: Reddit'ten kripto sentiment'i topla
    Girdi: Reddit public JSON API (ücretsiz)
    Çıktı: Sosyal sentiment → Strategist, Alert

    Kaynaklar:
    - r/CryptoCurrency
    - r/Bitcoin
    - r/ethereum
    - r/solana
    - r/altcoin
    """

    SUBREDDITS = [
        'CryptoCurrency',
        'Bitcoin',
        'ethereum',
        'solana',
        'altcoin',
    ]

    # Basit keyword-based sentiment
    BULLISH_KEYWORDS = {
        'moon', 'bullish', 'pump', 'buy', 'long', 'breakout', 'rally',
        'surge', 'all time high', 'ath', 'undervalued', 'accumulate',
        'hodl', 'diamond hands', 'to the moon', 'massive', 'huge',
        'explode', 'launch', 'rocket', 'adoption', 'institutional',
        'upgrade', 'partnership', 'approval', 'etf approved',
    }

    BEARISH_KEYWORDS = {
        'crash', 'bearish', 'dump', 'sell', 'short', 'correction',
        'bubble', 'scam', 'rugpull', 'rug pull', 'overvalued', 'fear',
        'panic', 'liquidation', 'rekt', 'dead', 'plunge', 'tank',
        'ban', 'regulation', 'hack', 'exploit', 'vulnerability',
        'sec lawsuit', 'investigation', 'ponzi',
    }

    # Coin mentions
    COIN_PATTERNS = {
        'BTC': r'\b(BTC|Bitcoin)\b',
        'ETH': r'\b(ETH|Ethereum)\b',
        'SOL': r'\b(SOL|Solana)\b',
        'XRP': r'\b(XRP|Ripple)\b',
        'ADA': r'\b(ADA|Cardano)\b',
        'DOGE': r'\b(DOGE|Dogecoin)\b',
        'AVAX': r'\b(AVAX|Avalanche)\b',
        'DOT': r'\b(DOT|Polkadot)\b',
        'LINK': r'\b(LINK|Chainlink)\b',
        'UNI': r'\b(UNI|Uniswap)\b',
        'MATIC': r'\b(MATIC|Polygon)\b',
        'NEAR': r'\b(NEAR Protocol|NEAR)\b',
        'SUI': r'\b(SUI)\b',
        'INJ': r'\b(INJ|Injective)\b',
        'FET': r'\b(FET|Fetch\.ai)\b',
    }

    def __init__(self, interval: float = 180.0):  # 3 dakikada bir
        super().__init__('Sosyal Medya Izleyici', interval=interval)
        self._seen_posts: set[str] = set()
        self._coin_sentiment: dict[str, list[float]] = {}

    async def run_cycle(self):
        await self.receive_all()

        all_posts = []
        for subreddit in self.SUBREDDITS:
            posts = await self._fetch_subreddit(subreddit)
            all_posts.extend(posts)

        if not all_posts:
            return

        # Post'ları analiz et
        coin_signals: dict[str, dict] = {}

        for post in all_posts:
            post_id = post.get('id', '')
            if post_id in self._seen_posts:
                continue
            self._seen_posts.add(post_id)

            title = post.get('title', '').lower()
            selftext = post.get('selftext', '').lower()
            text = f"{title} {selftext}"
            score = post.get('score', 0)  # Reddit upvotes
            num_comments = post.get('num_comments', 0)

            # Hangi coinlerden bahsediyor?
            mentioned_coins = []
            for coin, pattern in self.COIN_PATTERNS.items():
                if re.search(pattern, f"{post.get('title', '')} {post.get('selftext', '')}", re.IGNORECASE):
                    mentioned_coins.append(coin)

            if not mentioned_coins:
                continue

            # Sentiment hesapla
            bullish_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw in text)
            bearish_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw in text)

            total = bullish_count + bearish_count
            if total == 0:
                continue

            sentiment = (bullish_count - bearish_count) / total

            # Reddit score ile ağırlıklandır
            weight = min(score / 100, 3.0) if score > 0 else 0.5
            if num_comments > 50:
                weight *= 1.5

            weighted_sentiment = sentiment * weight

            for coin in mentioned_coins:
                if coin not in coin_signals:
                    coin_signals[coin] = {
                        'scores': [],
                        'post_count': 0,
                        'total_upvotes': 0,
                        'total_comments': 0,
                    }
                coin_signals[coin]['scores'].append(weighted_sentiment)
                coin_signals[coin]['post_count'] += 1
                coin_signals[coin]['total_upvotes'] += score
                coin_signals[coin]['total_comments'] += num_comments

        # Fazla eski post ID biriktirmesin
        if len(self._seen_posts) > 5000:
            self._seen_posts = set(list(self._seen_posts)[-2500:])

        # Sinyalleri oluştur
        signals = []
        for coin, data in coin_signals.items():
            if not data['scores']:
                continue

            avg_sentiment = sum(data['scores']) / len(data['scores'])

            # Coin sentiment geçmişi
            if coin not in self._coin_sentiment:
                self._coin_sentiment[coin] = []
            self._coin_sentiment[coin].append(avg_sentiment)
            if len(self._coin_sentiment[coin]) > 50:
                self._coin_sentiment[coin] = self._coin_sentiment[coin][-50:]

            # Yeterince güçlü sinyal mi?
            if abs(avg_sentiment) < 0.3:
                continue

            signal_score = avg_sentiment * 0.15  # Max 0.15 ağırlık

            signals.append({
                'coin': coin,
                'social_sentiment': round(avg_sentiment, 3),
                'post_count': data['post_count'],
                'total_upvotes': data['total_upvotes'],
                'total_comments': data['total_comments'],
                'signal_score': round(signal_score, 3),
                'reason': f'Reddit sentiment: {avg_sentiment:+.2f} ({data["post_count"]} post, {data["total_upvotes"]} upvote)',
                'source': 'social_media',
            })

        if signals:
            await self.send('strategist', {
                'type': 'social_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'social_media_update',
                'count': len(signals),
                'total_posts': len(all_posts),
            })

            for s in signals[:3]:
                direction = "BULLISH" if s['signal_score'] > 0 else "BEARISH"
                self.logger.info(
                    f"REDDIT | {s['coin']} {direction} "
                    f"sentiment={s['social_sentiment']:.2f} posts={s['post_count']}"
                )

    async def _fetch_subreddit(self, subreddit: str) -> list[dict]:
        """Reddit subreddit'ten son postları çek"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f'https://www.reddit.com/r/{subreddit}/hot.json',
                    params={'limit': 25},
                    headers={
                        'User-Agent': 'MiroFish-CryptoTrading/1.0',
                    }
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                posts = []
                for child in data.get('data', {}).get('children', []):
                    post = child.get('data', {})
                    posts.append({
                        'id': post.get('id', ''),
                        'title': post.get('title', ''),
                        'selftext': post.get('selftext', '')[:500],
                        'score': post.get('score', 0),
                        'num_comments': post.get('num_comments', 0),
                        'subreddit': subreddit,
                        'created_utc': post.get('created_utc', 0),
                    })
                return posts
        except Exception:
            return []
