"""
Crypto Trading konfigürasyon yönetimi
"""

import os


class CryptoTradingConfig:
    """Kripto trading modülü için tüm konfigürasyonlar"""

    # === Haber Kaynakları API Anahtarları ===
    CRYPTOPANIC_API_KEY = os.environ.get('CRYPTOPANIC_API_KEY', '')
    NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')
    GNEWS_API_KEY = os.environ.get('GNEWS_API_KEY', '')

    # === Binance API ===
    BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')
    BINANCE_TESTNET = os.environ.get('BINANCE_TESTNET', 'true').lower() == 'true'
    SIMULATION_MODE = os.environ.get('SIMULATION_MODE', 'true').lower() == 'true'

    # === LLM (MiroFish'in mevcut LLM config'ini kullanır) ===
    LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # === Trading Parametreleri ===
    # Desteklenen coin listesi
    TRACKED_COINS = os.environ.get(
        'TRACKED_COINS',
        'BTC,ETH,BNB,SOL,XRP,ADA,DOGE,AVAX,DOT,MATIC'
    ).split(',')

    # Minimum sentiment skoru (trading sinyali üretmek için)
    # Ön filtre eşiği (ağırlıklı ortalama). Asıl güvenlik: kaynak sayısı (2+ MODERATE, 3+ STRONG)
    MIN_SENTIMENT_SCORE = float(os.environ.get('MIN_SENTIMENT_SCORE', '0.15'))

    # Maksimum pozisyon büyüklüğü (USDT)
    MAX_POSITION_SIZE = float(os.environ.get('MAX_POSITION_SIZE', '100'))

    # Stop-loss yüzdesi
    STOP_LOSS_PCT = float(os.environ.get('STOP_LOSS_PCT', '3.0'))

    # Take-profit yüzdesi
    TAKE_PROFIT_PCT = float(os.environ.get('TAKE_PROFIT_PCT', '5.0'))

    # === Zamanlama ===
    # Haber tarama aralığı (saniye) — borsa duyuruları hızla fiyatı etkiler, kısa interval kritik
    NEWS_SCAN_INTERVAL = int(os.environ.get('NEWS_SCAN_INTERVAL', '5'))

    # Fiyat güncelleme aralığı (saniye)
    PRICE_UPDATE_INTERVAL = int(os.environ.get('PRICE_UPDATE_INTERVAL', '30'))

    # Sinyal değerlendirme aralığı (saniye)
    SIGNAL_EVAL_INTERVAL = int(os.environ.get('SIGNAL_EVAL_INTERVAL', '60'))

    # === RSS Feed URL'leri ===
    RSS_FEEDS = [
        'https://www.coindesk.com/arc/outboundfeeds/rss/',
        'https://cointelegraph.com/rss',
        'https://www.theblock.co/rss.xml',
        'https://decrypt.co/feed',
        'https://beincrypto.com/feed/',
    ]

    # === Telegram Bildirim ===
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

    # === Loglama ===
    LOG_LEVEL = os.environ.get('CRYPTO_LOG_LEVEL', 'INFO')
    LOG_DIR = os.path.join(os.path.dirname(__file__), '../../../logs/crypto_trading')

    # === Güvenlik Onayları ===
    # MAINNET açıksa kullanıcının açıkça onaylamasını zorunlu kıl
    ALLOW_MAINNET = os.environ.get('ALLOW_MAINNET', 'false').lower() == 'true'

    @classmethod
    def validate(cls):
        """Zorunlu konfigürasyonları kontrol et"""
        errors = []
        warnings = []

        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY gerekli - sentiment analizi için")

        if not cls.BINANCE_API_KEY or not cls.BINANCE_API_SECRET:
            warnings.append("BINANCE API anahtarları eksik - sadece sinyal modu aktif (trade execution kapalı)")

        if not cls.CRYPTOPANIC_API_KEY:
            warnings.append("CRYPTOPANIC_API_KEY eksik - CryptoPanic haberleri devre dışı")

        if not cls.NEWSAPI_KEY:
            warnings.append("NEWSAPI_KEY eksik - NewsAPI haberleri devre dışı")

        # MAINNET güvenlik kontrolü — gerçek para riski için açık onay gerekli
        mainnet_active = (
            not cls.BINANCE_TESTNET
            and not cls.SIMULATION_MODE
            and cls.BINANCE_API_KEY
            and cls.BINANCE_API_SECRET
        )
        if mainnet_active and not cls.ALLOW_MAINNET:
            errors.append(
                "MAINNET aktif (BINANCE_TESTNET=false, SIMULATION_MODE=false) "
                "fakat ALLOW_MAINNET=true değil. Gerçek parayla işlem için "
                "ALLOW_MAINNET=true env değişkenini açıkça ayarla."
            )
        elif mainnet_active and cls.ALLOW_MAINNET:
            warnings.append("MAINNET canlı işlem modu aktif — gerçek parayla işlem yapılıyor")

        # Semantik kontroller
        if cls.STOP_LOSS_PCT <= 0:
            errors.append(f"STOP_LOSS_PCT pozitif olmalı (mevcut: {cls.STOP_LOSS_PCT})")

        if cls.TAKE_PROFIT_PCT <= 0:
            errors.append(f"TAKE_PROFIT_PCT pozitif olmalı (mevcut: {cls.TAKE_PROFIT_PCT})")

        if cls.STOP_LOSS_PCT > 0 and cls.TAKE_PROFIT_PCT > 0:
            if cls.STOP_LOSS_PCT >= cls.TAKE_PROFIT_PCT:
                errors.append(
                    f"STOP_LOSS_PCT ({cls.STOP_LOSS_PCT}%) TAKE_PROFIT_PCT "
                    f"({cls.TAKE_PROFIT_PCT}%) değerinden küçük olmalı — "
                    f"aksi halde risk/ödül oranı pozitif değildir"
                )

        if cls.MAX_POSITION_SIZE <= 0:
            errors.append(f"MAX_POSITION_SIZE pozitif olmalı (mevcut: {cls.MAX_POSITION_SIZE})")

        if not (0.0 <= cls.MIN_SENTIMENT_SCORE <= 1.0):
            errors.append(
                f"MIN_SENTIMENT_SCORE 0.0-1.0 aralığında olmalı (mevcut: {cls.MIN_SENTIMENT_SCORE})"
            )

        for name, value in (
            ('NEWS_SCAN_INTERVAL', cls.NEWS_SCAN_INTERVAL),
            ('PRICE_UPDATE_INTERVAL', cls.PRICE_UPDATE_INTERVAL),
            ('SIGNAL_EVAL_INTERVAL', cls.SIGNAL_EVAL_INTERVAL),
        ):
            if value <= 0:
                errors.append(f"{name} pozitif olmalı (mevcut: {value})")

        if not cls.TRACKED_COINS or all(not c.strip() for c in cls.TRACKED_COINS):
            errors.append("TRACKED_COINS boş olamaz")

        return errors, warnings
