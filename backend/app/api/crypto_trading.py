"""
Crypto Trading API Endpoint'leri
"""

import asyncio
import logging

from flask import Blueprint, jsonify, request

from ..services.crypto_trading.config import CryptoTradingConfig
from ..services.crypto_trading.news_fetcher import NewsAggregator
from ..services.crypto_trading.price_service import PriceService
from ..services.crypto_trading.scheduler import (
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from ..services.crypto_trading.sentiment_analyzer import SentimentAnalyzer
from ..services.crypto_trading.signal_engine import SignalEngine

logger = logging.getLogger('crypto_trading.api')

crypto_bp = Blueprint('crypto_trading', __name__, url_prefix='/api/crypto')


def _run_async(coro):
    """Async fonksiyonu Flask senkron context'inde çalıştır"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=60)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# === Durum ve Kontrol ===

@crypto_bp.route('/status', methods=['GET'])
def get_status():
    """Sistem durumu"""
    scheduler = get_scheduler()
    errors, warnings = CryptoTradingConfig.validate()
    return jsonify({
        'ok': True,
        'scheduler': scheduler.stats,
        'config_errors': errors,
        'config_warnings': warnings,
        'tracked_coins': CryptoTradingConfig.TRACKED_COINS,
        'mode': 'TESTNET' if CryptoTradingConfig.BINANCE_TESTNET else 'MAINNET',
    })


@crypto_bp.route('/start', methods=['POST'])
def start_trading():
    """Scheduler'ı başlat"""
    auto_execute = request.json.get('auto_execute', True) if request.json else True
    scheduler = get_scheduler()
    scheduler.auto_execute = auto_execute
    result = _run_async(start_scheduler())
    return jsonify({'ok': True, **result})


@crypto_bp.route('/stop', methods=['POST'])
def stop_trading():
    """Scheduler'ı durdur"""
    result = _run_async(stop_scheduler())
    return jsonify({'ok': True, **result})


@crypto_bp.route('/full-status', methods=['GET'])
def get_full_status():
    """Detaylı durum raporu"""
    scheduler = get_scheduler()
    return jsonify({'ok': True, **scheduler.get_full_status()})


# === Haberler ===

@crypto_bp.route('/news', methods=['GET'])
def get_news():
    """Güncel kripto haberlerini getir"""
    coin = request.args.get('coin', None)
    aggregator = NewsAggregator()

    if coin:
        items = _run_async(aggregator.fetch_by_coin(coin.upper()))
    else:
        items = _run_async(aggregator.fetch_all(force=True))

    return jsonify({
        'ok': True,
        'count': len(items),
        'news': [n.to_dict() for n in items[:50]],
    })


# === Fiyatlar ===

@crypto_bp.route('/prices', methods=['GET'])
def get_prices():
    """Güncel fiyatları getir"""
    service = PriceService()
    prices = _run_async(service.get_prices(force=True))
    return jsonify({
        'ok': True,
        'prices': {k: v.to_dict() for k, v in prices.items()},
    })


@crypto_bp.route('/prices/<symbol>', methods=['GET'])
def get_price(symbol):
    """Tek coin fiyatı"""
    service = PriceService()
    price = _run_async(service.get_price(symbol.upper()))
    if price:
        return jsonify({'ok': True, 'price': price.to_dict()})
    return jsonify({'ok': False, 'error': f'{symbol} fiyatı bulunamadı'}), 404


# === Sentiment Analizi ===

@crypto_bp.route('/analyze', methods=['POST'])
def analyze_news():
    """Manuel haber analizi"""
    data = request.json
    if not data or 'title' not in data:
        return jsonify({'ok': False, 'error': 'title alanı gerekli'}), 400

    from ..services.crypto_trading.news_fetcher import NewsItem
    from datetime import datetime, timezone

    news = NewsItem(
        id='manual',
        title=data['title'],
        body=data.get('body', data['title']),
        source='Manual',
        url='',
        published_at=datetime.now(timezone.utc),
        coins=data.get('coins', []),
    )

    analyzer = SentimentAnalyzer()
    target_coin = data.get('coin', None)
    results = analyzer.analyze(news, target_coin=target_coin)

    return jsonify({
        'ok': True,
        'results': [r.to_dict() for r in results],
    })


# === Sinyaller ===

@crypto_bp.route('/signals', methods=['GET'])
def get_signals():
    """Sinyal geçmişi"""
    scheduler = get_scheduler()
    limit = request.args.get('limit', 50, type=int)
    return jsonify({
        'ok': True,
        'signals': scheduler.signal_engine.get_signal_history(limit),
    })


@crypto_bp.route('/signals/generate', methods=['POST'])
def generate_signals():
    """Manuel sinyal üretimi"""
    engine = SignalEngine()
    signals = _run_async(engine.generate_signals())
    return jsonify({
        'ok': True,
        'count': len(signals),
        'signals': [s.to_dict() for s in signals],
    })


@crypto_bp.route('/signals/pending', methods=['GET'])
def get_pending_signals():
    """Bekleyen sinyaller"""
    scheduler = get_scheduler()
    return jsonify({
        'ok': True,
        'pending': scheduler.get_pending_signals(),
    })


@crypto_bp.route('/signals/<signal_id>/execute', methods=['POST'])
def execute_signal(signal_id):
    """Bekleyen sinyali execute et"""
    scheduler = get_scheduler()
    _run_async(scheduler.execute_pending(signal_id))
    return jsonify({'ok': True, 'message': f'Sinyal {signal_id} execute edildi'})


# === Trade / Emirler ===

@crypto_bp.route('/orders', methods=['GET'])
def get_orders():
    """Emir geçmişi"""
    scheduler = get_scheduler()
    limit = request.args.get('limit', 50, type=int)
    return jsonify({
        'ok': True,
        'orders': scheduler.trade_executor.get_order_history(limit),
    })


@crypto_bp.route('/positions', methods=['GET'])
def get_positions():
    """Aktif pozisyonlar"""
    scheduler = get_scheduler()
    return jsonify({
        'ok': True,
        'positions': scheduler.trade_executor.get_active_positions(),
    })


@crypto_bp.route('/balance', methods=['GET'])
def get_balance():
    """Binance hesap bakiyesi"""
    scheduler = get_scheduler()
    balance = _run_async(scheduler.trade_executor.get_account_balance())
    return jsonify({'ok': True, **balance})


# === Konfigürasyon ===

@crypto_bp.route('/config', methods=['GET'])
def get_config():
    """Mevcut konfigürasyon (API key'ler maskelenmiş)"""
    def mask(key: str) -> str:
        if not key:
            return '(yapılandırılmamış)'
        return key[:4] + '***' + key[-4:] if len(key) > 8 else '***'

    return jsonify({
        'ok': True,
        'config': {
            'tracked_coins': CryptoTradingConfig.TRACKED_COINS,
            'min_sentiment_score': CryptoTradingConfig.MIN_SENTIMENT_SCORE,
            'max_position_size': CryptoTradingConfig.MAX_POSITION_SIZE,
            'stop_loss_pct': CryptoTradingConfig.STOP_LOSS_PCT,
            'take_profit_pct': CryptoTradingConfig.TAKE_PROFIT_PCT,
            'news_scan_interval': CryptoTradingConfig.NEWS_SCAN_INTERVAL,
            'binance_testnet': CryptoTradingConfig.BINANCE_TESTNET,
            'api_keys': {
                'binance': mask(CryptoTradingConfig.BINANCE_API_KEY),
                'cryptopanic': mask(CryptoTradingConfig.CRYPTOPANIC_API_KEY),
                'newsapi': mask(CryptoTradingConfig.NEWSAPI_KEY),
                'gnews': mask(CryptoTradingConfig.GNEWS_API_KEY),
                'llm': mask(CryptoTradingConfig.LLM_API_KEY),
            },
            'rss_feeds': CryptoTradingConfig.RSS_FEEDS,
        },
    })
