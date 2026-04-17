"""
Kripto Haber Toplayıcı (News Fetcher)
Birden fazla kaynaktan kripto haberlerini toplar ve normalize eder.

Kaynaklar:
- CryptoPanic API (kripto özel haber aggregator)
- CoinGecko News (trending + status updates)
- NewsAPI (genel haberler, kripto filtreli)
- GNews API (alternatif haber kaynağı)
- RSS Feeds (CoinDesk, CoinTelegraph, TheBlock, Decrypt, Bitcoin Magazine)
- Borsa duyuruları (Binance CMS, Upbit, Coinbase, OKX, Bybit) — en hızlı fiyat etkili sinyal
"""

import asyncio
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from .config import CryptoTradingConfig

logger = logging.getLogger('crypto_trading.news')


@dataclass
class NewsItem:
    """Normalize edilmiş haber öğesi"""
    id: str
    title: str
    body: str
    source: str
    url: str
    published_at: datetime
    coins: list[str] = field(default_factory=list)
    sentiment_hint: Optional[str] = None  # 'positive', 'negative', 'neutral' (kaynaktan gelen ipucu)
    importance: str = 'medium'  # 'high', 'medium', 'low'
    raw_data: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body[:500],
            'source': self.source,
            'url': self.url,
            'published_at': self.published_at.isoformat(),
            'coins': self.coins,
            'sentiment_hint': self.sentiment_hint,
            'importance': self.importance,
        }


def _generate_id(source: str, title: str) -> str:
    """Haber için unique ID üret"""
    raw = f"{source}:{title}".encode('utf-8')
    return hashlib.md5(raw).hexdigest()[:16]


COIN_ALIASES = {
    # Top coins
    'BTC': ['BITCOIN', 'BTC'],
    'ETH': ['ETHEREUM', 'ETH', 'ETHER'],
    'BNB': ['BINANCE COIN', 'BNB'],
    'SOL': ['SOLANA', 'SOL'],
    'XRP': ['RIPPLE', 'XRP'],
    'ADA': ['CARDANO', 'ADA'],
    'DOGE': ['DOGECOIN', 'DOGE'],
    'AVAX': ['AVALANCHE', 'AVAX'],
    'DOT': ['POLKADOT', 'DOT'],
    'POL': ['POLYGON', 'POL', 'MATIC'],
    # Layer 2 / Scaling
    'ARB': ['ARBITRUM', 'ARB'],
    'OP': ['OPTIMISM'],
    'SUI': ['SUI'],
    'SEI': ['SEI'],
    'STX': ['STACKS', 'STX'],
    'STRK': ['STARKNET', 'STRK'],
    'MANTA': ['MANTA'],
    'IMX': ['IMMUTABLE', 'IMX'],
    # DeFi
    'LINK': ['CHAINLINK', 'LINK'],
    'UNI': ['UNISWAP', 'UNI'],
    'AAVE': ['AAVE'],
    'MKR': ['MAKER', 'MKR'],
    'CRV': ['CURVE', 'CRV'],
    'LDO': ['LIDO', 'LDO'],
    'PENDLE': ['PENDLE'],
    'DYDX': ['DYDX'],
    'INJ': ['INJECTIVE', 'INJ'],
    'RUNE': ['THORCHAIN', 'RUNE'],
    'ONDO': ['ONDO'],
    'ENA': ['ETHENA', 'ENA'],
    # Layer 1
    'NEAR': ['NEAR PROTOCOL', 'NEAR'],
    'APT': ['APTOS', 'APT'],
    'ATOM': ['COSMOS', 'ATOM'],
    'ICP': ['INTERNET COMPUTER', 'ICP'],
    'FIL': ['FILECOIN', 'FIL'],
    'HBAR': ['HEDERA', 'HBAR'],
    'ALGO': ['ALGORAND', 'ALGO'],
    'TIA': ['CELESTIA', 'TIA'],
    'FET': ['FETCH.AI', 'FET', 'FETCH AI'],
    'RENDER': ['RENDER'],
    'TAO': ['BITTENSOR', 'TAO'],
    'AR': ['ARWEAVE'],
    'TON': ['TONCOIN', 'TON'],
    'TRX': ['TRON', 'TRX'],
    'LTC': ['LITECOIN', 'LTC'],
    'BCH': ['BITCOIN CASH', 'BCH'],
    'ETC': ['ETHEREUM CLASSIC', 'ETC'],
    'KAIA': ['KAIA'],
    'BERA': ['BERACHAIN', 'BERA'],
    # Meme
    'SHIB': ['SHIBA INU', 'SHIB', 'SHIBA'],
    'PEPE': ['PEPE'],
    'FLOKI': ['FLOKI'],
    'WIF': ['DOGWIFHAT', 'WIF'],
    'BONK': ['BONK'],
    'TRUMP': ['TRUMP'],
    'TURBO': ['TURBO'],
    'PNUT': ['PEANUT', 'PNUT'],
    'NEIRO': ['NEIRO'],
    'MEME': ['MEMECOIN', 'MEME'],
    # Gaming / Metaverse
    'AXS': ['AXIE', 'AXS'],
    'SAND': ['SANDBOX', 'SAND'],
    'MANA': ['DECENTRALAND', 'MANA'],
    'GALA': ['GALA'],
    'ENJ': ['ENJIN', 'ENJ'],
    'IMX': ['IMMUTABLE', 'IMX'],
    'PIXEL': ['PIXEL'],
    # AI
    'VIRTUAL': ['VIRTUAL'],
    'CGPT': ['CHAINGPT', 'CGPT'],
    'AIXBT': ['AIXBT'],
    # Diğer popüler
    'WLD': ['WORLDCOIN', 'WLD'],
    'JUP': ['JUPITER', 'JUP'],
    'PYTH': ['PYTH'],
    'W': ['WORMHOLE'],
    'EIGEN': ['EIGENLAYER', 'EIGEN'],
    'ENS': ['ENS', 'ETHEREUM NAME'],
    'GRT': ['THE GRAPH', 'GRT'],
    'SNX': ['SYNTHETIX', 'SNX'],
    'COMP': ['COMPOUND', 'COMP'],
    'SUSHI': ['SUSHISWAP', 'SUSHI'],
    'XLM': ['STELLAR', 'XLM'],
    'VET': ['VECHAIN', 'VET'],
    'THETA': ['THETA'],
    'JASMY': ['JASMY'],
    'CHZ': ['CHILIZ', 'CHZ'],
    'BLUR': ['BLUR'],
    'MOVE': ['MOVEMENT', 'MOVE'],
    'HYPER': ['HYPERLIQUID', 'HYPER'],
}

# Binance'deki tüm USDT pair'leri (440+) - cache'lenir
_binance_symbols_cache: set[str] = set()


async def _load_binance_symbols():
    """Binance'den tüm aktif USDT pair sembollerini çek"""
    global _binance_symbols_cache
    if _binance_symbols_cache:
        return _binance_symbols_cache
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get('https://api.binance.com/api/v3/exchangeInfo', timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for s in data['symbols']:
                if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                    _binance_symbols_cache.add(s['baseAsset'])
        logger.info(f"Binance: {len(_binance_symbols_cache)} aktif USDT pair yüklendi")
    except Exception as e:
        logger.warning(f"Binance sembol listesi yüklenemedi: {e}")
    return _binance_symbols_cache


def _detect_coins(text: str, tracked: list[str] = None) -> list[str]:
    """Metinden coin sembollerini tespit et - Binance'deki tüm coinleri tanır"""
    text_upper = text.upper()
    found = set()

    # 1. Alias sözlüğünden tanı (isim bazlı: "Bitcoin", "Ethereum" vb.)
    for symbol, aliases in COIN_ALIASES.items():
        for alias in aliases:
            if alias in text_upper:
                found.add(symbol)
                break

    # 2. Binance cache'den doğrudan sembol eşleştir
    # False positive önleme: yaygın İngilizce kelimelerle çakışan semboller
    ambiguous_symbols = {
        'A', 'B', 'C', 'D', 'F', 'G', 'S', 'T', 'U', 'W',          # tek harf
        'AI', 'AR', 'AT', 'BB', 'ID', 'IO', 'ME', 'OP', 'OR',       # 2 harf
        'QI', 'SC', 'FF', 'LA', 'YB',
        'ACE', 'ACH', 'ACT', 'AMP', 'ARK', 'ATA', 'AVA', 'BAR',     # 3+ harf yaygın kelimeler
        'BAT', 'BEL', 'COS', 'COW', 'ERA', 'EUR', 'FUN', 'GAS',
        'GUN', 'GNO', 'GNS', 'HIGH', 'HIVE', 'HOME', 'HOT', 'IQ',
        'JOE', 'LAZIO', 'MAGIC', 'MASK', 'MAV', 'MET', 'MINA',
        'MLN', 'NEAR', 'NOT', 'OG', 'ONE', 'OPEN', 'OXT', 'POND',
        'PORTO', 'PSG', 'PUMP', 'QUICK', 'RARE', 'RAD', 'RED',
        'REQ', 'RIF', 'ROSE', 'SAND', 'SANTOS', 'SIGN', 'SKY',
        'SPELL', 'STEEM', 'STO', 'SUN', 'SUPER', 'SYS', 'THE',
        'TRU', 'TURBO', 'TURTLE', 'WIN', 'WOO', 'FORM', 'FARM',
        'COMP', 'DASH', 'EDEN', 'EPIC', 'FLUX', 'FRONT', 'HOLO',
        'IRIS', 'LOOM', 'PERP', 'REEF', 'VITE', 'WING', 'ALT',
        'ONG', 'ONT', 'SCR', 'PIXEL', 'DENT', 'CATI', 'INIT', 'FLOW',
        'SENT', 'TREE', 'BANK', 'ALLO', 'CITY', 'NIGHT', 'PROVE', 'PROM',
        'ASTR', 'PARTI', 'LAYER', 'SIREN', 'ASTER', 'RESOLV',
    }
    for symbol in _binance_symbols_cache:
        if symbol in ambiguous_symbols:
            continue
        if len(symbol) >= 4 and symbol in text_upper:
            found.add(symbol)

    return list(found)


class CryptoPanicFetcher:
    """CryptoPanic API - en iyi kripto haber aggregator"""

    BASE_URL = 'https://cryptopanic.com/api/free/v1/posts/'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        if not CryptoTradingConfig.CRYPTOPANIC_API_KEY:
            return []

        items = []
        try:
            params = {
                'auth_token': CryptoTradingConfig.CRYPTOPANIC_API_KEY,
                'filter': 'important',
                'kind': 'news',
                'public': 'true',
            }
            resp = await client.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for post in data.get('results', [])[:30]:
                title = post.get('title', '')
                coins = [c['code'] for c in post.get('currencies', [])]
                votes = post.get('votes', {})
                hint = None
                if votes:
                    pos = votes.get('positive', 0) + votes.get('important', 0)
                    neg = votes.get('negative', 0) + votes.get('toxic', 0)
                    if pos > neg:
                        hint = 'positive'
                    elif neg > pos:
                        hint = 'negative'

                pub_str = post.get('published_at', '')
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(timezone.utc)

                items.append(NewsItem(
                    id=_generate_id('cryptopanic', title),
                    title=title,
                    body=post.get('body', title),
                    source='CryptoPanic',
                    url=post.get('url', ''),
                    published_at=pub_dt,
                    coins=coins or _detect_coins(title),
                    sentiment_hint=hint,
                    importance='high' if post.get('kind') == 'news' else 'medium',
                    raw_data=post,
                ))
            logger.info(f"CryptoPanic: {len(items)} haber toplandı")
        except Exception as e:
            logger.error(f"CryptoPanic fetch hatası: {e}")

        return items


class BinanceAnnouncementFetcher:
    """
    Binance resmi duyuru CMS API'si.
    Bazı coğrafyalarda ana endpoint kısıtlı — fallback URL ile bypass.
    """

    # Catalog ID → kategori etiketi (Binance CMS API'sinden doğrulandı)
    # 48: New Cryptocurrency Listing | 128: Crypto Airdrop
    # 161: Delisting | 49: Latest Binance News
    CATALOGS = {
        48: 'new_listing',
        161: 'delisting',
        128: 'airdrop',
        49: 'latest_news',
    }

    PRIMARY_URL = 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query'
    FALLBACK_URL = 'https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query'

    _HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.binance.com/en/support/announcement',
        'Origin': 'https://www.binance.com',
        'lang': 'en',
        'clienttype': 'web',
    }

    async def _fetch_from_endpoint(
        self, client: httpx.AsyncClient, url: str, catalog_id: int
    ) -> list[dict]:
        params = {
            'type': 1,
            'catalogId': catalog_id,
            'pageNo': 1,
            'pageSize': 10,
        }
        response = await client.get(url, params=params, headers=self._HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        return (data.get('data') or {}).get('articles') or []

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []
        for catalog_id, category in self.CATALOGS.items():
            articles = []
            try:
                articles = await self._fetch_from_endpoint(client, self.PRIMARY_URL, catalog_id)
                if not articles:
                    logger.debug(f"Binance ana endpoint boş ({category}), fallback deneniyor")
                    articles = await self._fetch_from_endpoint(
                        client, self.FALLBACK_URL, catalog_id
                    )
            except Exception as e:
                logger.warning(f"Binance CMS fetch hatası ({category}): {e}")
                continue

            importance = 'high' if category in ('new_listing', 'delisting', 'airdrop') else 'medium'
            sentiment_hint = (
                'positive' if category in ('new_listing', 'airdrop')
                else 'negative' if category == 'delisting'
                else None
            )

            for article in articles:
                title = article.get('title', '')
                if not title:
                    continue

                release_ts = article.get('releaseDate', 0)
                try:
                    published_at = (
                        datetime.fromtimestamp(release_ts / 1000, tz=timezone.utc)
                        if release_ts else datetime.now(timezone.utc)
                    )
                except (ValueError, OSError, TypeError):
                    published_at = datetime.now(timezone.utc)

                article_code = article.get('code', '')

                items.append(NewsItem(
                    id=_generate_id('binance_cms', article_code or title),
                    title=f"[Binance {category.upper()}] {title}",
                    body=article.get('body', '') or title,
                    source=f'Binance/{category}',
                    url=(
                        f'https://www.binance.com/en/support/announcement/{article_code}'
                        if article_code else ''
                    ),
                    published_at=published_at,
                    coins=_detect_coins(title),
                    importance=importance,
                    sentiment_hint=sentiment_hint,
                ))

        if items:
            logger.info(f"Binance CMS: {len(items)} duyuru toplandı")
        else:
            logger.warning(
                "Binance CMS her iki endpoint'ten de veri dönmedi — "
                "muhtemelen coğrafi kısıtlama. VPS (Tokyo/Singapur) öneriliyor."
            )
        return items


class UpbitAnnouncementFetcher:
    """Upbit (Kore) listing duyuruları - ücretsiz, çok hızlı fiyat etkisi yapar"""

    BASE_URL = 'https://api-manager.upbit.com/api/v1/announcements'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []
        try:
            params = {'os': 'web', 'page': 1, 'per_page': 20, 'category': 'trade'}
            resp = await client.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            notices = (data.get('data') or {}).get('notices') or data.get('notices') or []

            for notice in notices:
                title = notice.get('title', '')
                notice_id = notice.get('id', '')
                listed_at = notice.get('listed_at', '') or notice.get('first_listed_at', '')
                try:
                    pub_dt = datetime.fromisoformat(listed_at.replace('Z', '+00:00')) if listed_at else datetime.now(timezone.utc)
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(timezone.utc)

                coins = _detect_coins(title)
                title_lower = title.lower()
                is_listing = '디지털 자산' in title or '거래지원' in title or 'listing' in title_lower or 'new' in title_lower
                hint = 'positive' if is_listing else None
                importance = 'high' if coins else 'medium'

                items.append(NewsItem(
                    id=_generate_id('upbit_ann', title),
                    title=f"[Upbit] {title}",
                    body=title,
                    source='Upbit Announcements',
                    url=f"https://upbit.com/service_center/notice?id={notice_id}" if notice_id else '',
                    published_at=pub_dt,
                    coins=coins,
                    sentiment_hint=hint,
                    importance=importance,
                ))
            logger.info(f"Upbit: {len(items)} duyuru toplandı")
        except Exception as e:
            logger.warning(f"Upbit Announcement fetch hatası: {e}")

        return items


class CoinbaseAnnouncementFetcher:
    """Coinbase blog RSS — Cloudflare korumalı, birden fazla mirror dener"""

    SOURCES = [
        ('blog_rss', 'https://www.coinbase.com/blog/rss.xml'),
        ('nitter', 'https://nitter.net/coinbase/rss'),
    ]

    _HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) '
            'Version/17.0 Safari/605.1.15'
        ),
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    _LISTING_KEYWORDS = ('is now available', 'listing', 'launching', 'now live', 'added', 'now supports')

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items: list[NewsItem] = []

        for source_name, url in self.SOURCES:
            try:
                response = await client.get(
                    url, headers=self._HEADERS, timeout=15, follow_redirects=True
                )
                response.raise_for_status()
                root = ET.fromstring(response.text)

                for item in root.iter('item'):
                    title = (item.findtext('title') or '').strip()
                    if not title:
                        continue
                    link = (item.findtext('link') or '').strip()
                    description = (item.findtext('description') or '').strip()
                    pub_date_str = item.findtext('pubDate') or ''

                    try:
                        published_at = parsedate_to_datetime(pub_date_str)
                        if published_at.tzinfo is None:
                            published_at = published_at.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        published_at = datetime.now(timezone.utc)

                    clean_desc = re.sub(r'<[^>]+>', '', description)
                    title_lower = title.lower()
                    is_listing = any(kw in title_lower for kw in self._LISTING_KEYWORDS)

                    items.append(NewsItem(
                        id=_generate_id(f'coinbase_{source_name}', title),
                        title=f"[Coinbase] {title}",
                        body=clean_desc[:500],
                        source=f'Coinbase/{source_name}',
                        url=link,
                        published_at=published_at,
                        coins=_detect_coins(f"{title} {clean_desc}"),
                        importance='high' if is_listing else 'medium',
                        sentiment_hint='positive' if is_listing else None,
                    ))

                if items:
                    logger.info(f"Coinbase/{source_name}: {len(items)} haber toplandı")
                    break
            except Exception as e:
                logger.warning(f"Coinbase {source_name} fetch hatası: {e}")
                continue

        if not items:
            logger.warning("Coinbase: hiçbir kaynaktan veri dönmedi")
        return items


class OKXAnnouncementFetcher:
    """OKX listing duyuruları - public API"""

    BASE_URL = 'https://www.okx.com/api/v5/support/announcements'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []
        try:
            resp = await client.get(self.BASE_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            anns = []
            for block in data.get('data', []) or []:
                anns.extend(block.get('details', []) or [])

            for ann in anns[:25]:
                title = ann.get('title', '')
                url = ann.get('url', '')
                ts = ann.get('pTime', '') or ann.get('releaseDate', '') or ann.get('p_time', '')
                try:
                    pub_dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc) if ts else datetime.now(timezone.utc)
                except (ValueError, OSError, TypeError):
                    pub_dt = datetime.now(timezone.utc)

                coins = _detect_coins(title)
                title_lower = title.lower()
                is_listing = 'listing' in title_lower or 'list' in title_lower or 'launching' in title_lower
                hint = 'positive' if is_listing else None

                items.append(NewsItem(
                    id=_generate_id('okx_ann', title),
                    title=f"[OKX] {title}",
                    body=title,
                    source='OKX Announcements',
                    url=url,
                    published_at=pub_dt,
                    coins=coins,
                    sentiment_hint=hint,
                    importance='high' if (coins and is_listing) else 'medium',
                ))
            logger.info(f"OKX: {len(items)} duyuru toplandı")
        except Exception as e:
            logger.warning(f"OKX Announcement fetch hatası: {e}")

        return items


class BybitAnnouncementFetcher:
    """Bybit listing duyuruları - public API"""

    BASE_URL = 'https://api.bybit.com/v5/announcements/index'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []
        try:
            params = {'locale': 'en-US', 'type': 'new_crypto', 'limit': 20}
            resp = await client.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            anns = ((data.get('result') or {}).get('list')) or []

            for ann in anns:
                title = ann.get('title', '')
                url = ann.get('url', '')
                ts = ann.get('dateTimestamp', 0) or ann.get('publishTime', 0)
                try:
                    pub_dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc) if ts else datetime.now(timezone.utc)
                except (ValueError, OSError, TypeError):
                    pub_dt = datetime.now(timezone.utc)

                coins = _detect_coins(title)

                items.append(NewsItem(
                    id=_generate_id('bybit_ann', title),
                    title=f"[Bybit] {title}",
                    body=title,
                    source='Bybit Announcements',
                    url=url,
                    published_at=pub_dt,
                    coins=coins,
                    sentiment_hint='positive',
                    importance='high' if coins else 'medium',
                ))
            logger.info(f"Bybit: {len(items)} duyuru toplandı")
        except Exception as e:
            logger.warning(f"Bybit Announcement fetch hatası: {e}")

        return items


class CoinGeckoNewsFetcher:
    """CoinGecko trending ve status güncellemeleri"""

    TRENDING_URL = 'https://api.coingecko.com/api/v3/search/trending'
    STATUS_URL = 'https://api.coingecko.com/api/v3/status_updates'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []
        try:
            # Trending coins
            resp = await client.get(self.TRENDING_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for coin_data in data.get('coins', [])[:10]:
                coin = coin_data.get('item', {})
                title = f"Trending: {coin.get('name', '')} ({coin.get('symbol', '')}) - Rank #{coin.get('market_cap_rank', 'N/A')}"
                symbol = coin.get('symbol', '').upper()

                items.append(NewsItem(
                    id=_generate_id('coingecko_trending', title),
                    title=title,
                    body=f"{coin.get('name')} is trending on CoinGecko. Price BTC: {coin.get('price_btc', 'N/A')}",
                    source='CoinGecko Trending',
                    url=f"https://www.coingecko.com/en/coins/{coin.get('id', '')}",
                    published_at=datetime.now(timezone.utc),
                    coins=[symbol] if symbol else [],
                    sentiment_hint='positive',
                    importance='medium',
                ))
            logger.info(f"CoinGecko Trending: {len(items)} coin toplandı")
        except Exception as e:
            logger.error(f"CoinGecko fetch hatası: {e}")

        return items


class NewsAPIFetcher:
    """NewsAPI.org - genel haberler kripto filtreli"""

    BASE_URL = 'https://newsapi.org/v2/everything'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        if not CryptoTradingConfig.NEWSAPI_KEY:
            return []

        items = []
        try:
            params = {
                'q': 'cryptocurrency OR bitcoin OR ethereum OR crypto market',
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 30,
                'apiKey': CryptoTradingConfig.NEWSAPI_KEY,
            }
            resp = await client.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for article in data.get('articles', []):
                title = article.get('title', '')
                desc = article.get('description', '') or ''
                content = article.get('content', '') or ''
                full_text = f"{title} {desc} {content}"

                pub_str = article.get('publishedAt', '')
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(timezone.utc)

                items.append(NewsItem(
                    id=_generate_id('newsapi', title),
                    title=title,
                    body=desc or content[:500],
                    source=f"NewsAPI/{article.get('source', {}).get('name', 'Unknown')}",
                    url=article.get('url', ''),
                    published_at=pub_dt,
                    coins=_detect_coins(full_text),
                    importance='medium',
                ))
            logger.info(f"NewsAPI: {len(items)} haber toplandı")
        except Exception as e:
            logger.error(f"NewsAPI fetch hatası: {e}")

        return items


class GNewsFetcher:
    """GNews API - alternatif haber kaynağı"""

    BASE_URL = 'https://gnews.io/api/v4/search'

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        if not CryptoTradingConfig.GNEWS_API_KEY:
            return []

        items = []
        try:
            params = {
                'q': 'cryptocurrency bitcoin ethereum',
                'lang': 'en',
                'max': 20,
                'token': CryptoTradingConfig.GNEWS_API_KEY,
            }
            resp = await client.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for article in data.get('articles', []):
                title = article.get('title', '')
                desc = article.get('description', '') or ''
                full_text = f"{title} {desc}"

                pub_str = article.get('publishedAt', '')
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(timezone.utc)

                items.append(NewsItem(
                    id=_generate_id('gnews', title),
                    title=title,
                    body=desc,
                    source=f"GNews/{article.get('source', {}).get('name', 'Unknown')}",
                    url=article.get('url', ''),
                    published_at=pub_dt,
                    coins=_detect_coins(full_text),
                    importance='medium',
                ))
            logger.info(f"GNews: {len(items)} haber toplandı")
        except Exception as e:
            logger.error(f"GNews fetch hatası: {e}")

        return items


class RSSFetcher:
    """RSS Feed okuyucu - CoinDesk, CoinTelegraph, TheBlock, Decrypt, Bitcoin Magazine"""

    async def fetch(self, client: httpx.AsyncClient) -> list[NewsItem]:
        items = []

        for feed_url in CryptoTradingConfig.RSS_FEEDS:
            try:
                resp = await client.get(feed_url, timeout=15, follow_redirects=True)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)

                # RSS 2.0 format
                channel = root.find('channel')
                if channel is None:
                    # Atom format
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    entries = root.findall('atom:entry', ns)
                    source_name = root.findtext('atom:title', 'Unknown', ns)
                    for entry in entries[:10]:
                        title = entry.findtext('atom:title', '', ns)
                        summary = entry.findtext('atom:summary', '', ns)
                        link_el = entry.find('atom:link', ns)
                        link = link_el.get('href', '') if link_el is not None else ''
                        pub_str = entry.findtext('atom:published', '', ns) or entry.findtext('atom:updated', '', ns)
                        try:
                            pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
                        except (ValueError, AttributeError):
                            pub_dt = datetime.now(timezone.utc)

                        items.append(NewsItem(
                            id=_generate_id(f'rss_{source_name}', title),
                            title=title,
                            body=summary[:500],
                            source=f"RSS/{source_name}",
                            url=link,
                            published_at=pub_dt,
                            coins=_detect_coins(f"{title} {summary}"),
                            importance='medium',
                        ))
                    continue

                source_name = channel.findtext('title', 'Unknown')
                for item in channel.findall('item')[:10]:
                    title = item.findtext('title', '')
                    desc = item.findtext('description', '')
                    link = item.findtext('link', '')
                    pub_str = item.findtext('pubDate', '')

                    try:
                        pub_dt = parsedate_to_datetime(pub_str).replace(tzinfo=timezone.utc) if pub_str else datetime.now(timezone.utc)
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)

                    clean_desc = re.sub(r'<[^>]+>', '', desc or '')

                    items.append(NewsItem(
                        id=_generate_id(f'rss_{source_name}', title),
                        title=title,
                        body=clean_desc[:500],
                        source=f"RSS/{source_name}",
                        url=link,
                        published_at=pub_dt,
                        coins=_detect_coins(f"{title} {clean_desc}"),
                        importance='medium',
                    ))

                logger.info(f"RSS/{source_name}: haberler toplandı")
            except Exception as e:
                logger.warning(f"RSS fetch hatası ({feed_url}): {e}")

        return items


class NewsAggregator:
    """Tüm haber kaynaklarını birleştiren ana aggregator"""

    def __init__(self):
        self.fetchers = [
            CryptoPanicFetcher(),
            CoinGeckoNewsFetcher(),
            NewsAPIFetcher(),
            GNewsFetcher(),
            RSSFetcher(),
            BinanceAnnouncementFetcher(),
            UpbitAnnouncementFetcher(),
            CoinbaseAnnouncementFetcher(),
            OKXAnnouncementFetcher(),
            BybitAnnouncementFetcher(),
        ]
        self._seen_ids: set[str] = set()
        self._cache: list[NewsItem] = []
        self._last_fetch: float = 0

    async def fetch_all(self, force: bool = False) -> list[NewsItem]:
        """Tüm kaynaklardan haberleri topla, deduplicate et, zamana göre sırala"""
        # Binance sembol listesini yükle (ilk seferde)
        await _load_binance_symbols()

        now = time.time()
        if not force and (now - self._last_fetch) < CryptoTradingConfig.NEWS_SCAN_INTERVAL:
            return self._cache

        async with httpx.AsyncClient(
            headers={'User-Agent': 'MiroFish-CryptoTrading/1.0'},
            follow_redirects=True,
        ) as client:
            tasks = [fetcher.fetch(client) for fetcher in self.fetchers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Fetcher hatası: {result}")
                continue
            all_items.extend(result)

        # Deduplicate
        unique_items = []
        for item in all_items:
            if item.id not in self._seen_ids:
                self._seen_ids.add(item.id)
                unique_items.append(item)

        # Zamana göre sırala (en yeni önce)
        unique_items.sort(key=lambda x: x.published_at, reverse=True)

        self._cache = unique_items
        self._last_fetch = now
        logger.info(f"Toplam {len(unique_items)} benzersiz haber toplandı")

        return unique_items

    async def fetch_by_coin(self, coin: str) -> list[NewsItem]:
        """Belirli bir coin için haberleri filtrele"""
        all_news = await self.fetch_all()
        return [n for n in all_news if coin.upper() in [c.upper() for c in n.coins]]

    def clear_cache(self):
        """Cache'i temizle"""
        self._seen_ids.clear()
        self._cache.clear()
        self._last_fetch = 0
