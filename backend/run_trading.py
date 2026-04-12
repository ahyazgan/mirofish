"""
MiroFish Crypto Trading - Multi-Agent System
21 ajan paralel çalışarak profesyonel trading yapar.
+ WebSocket anlık fiyat + SQLite DB + Telegram + Web Dashboard
"""

import asyncio
import logging
import os
import sys

if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'), override=True)

from app.services.crypto_trading.config import CryptoTradingConfig
from app.services.crypto_trading.agents.orchestrator import AgentOrchestrator
from app.services.crypto_trading.dashboard import DashboardServer

# Loglama
os.makedirs('logs/crypto_trading', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/crypto_trading/trading.log', encoding='utf-8'),
    ]
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)

DURATION_SECONDS = 3600  # 1 saat


async def main():
    errors, warnings = CryptoTradingConfig.validate()
    if errors:
        print(f"HATA: {errors}")
        return

    for w in warnings:
        print(f"UYARI: {w}")

    print()
    print("=" * 60)
    print("  MiroFish Multi-Agent Crypto Trading System")
    print("  21 AJAN PRO | WebSocket | DB | Telegram | Dashboard")
    print("=" * 60)
    print()
    print("  [Veri Toplama]")
    print("    1.  Haber Kesfedici       - 4 haber kaynagi tarama")
    print("    2.  Sosyal Medya Izleyici - Reddit sentiment analizi")
    print("    3.  Balina Takipcisi      - Buyuk transfer tespiti")
    print("    4.  Fonlama Orani Izleyici- Futures fonlama orani")
    print("    5.  DeFi Izleyici         - TVL & DEX hacim takibi")
    print("    6.  Makro Izleyici        - DXY/Altin/S&P500 takibi")
    print("  [Analiz]")
    print("    7.  Duygu Analizcisi      - LLM ile haber analizi")
    print("    8.  Teknik Analizci       - RSI/MACD/Bollinger/EMA")
    print("    9.  Emir Defteri Analizcisi- Alim/satim duvarlari")
    print("    10. Likidasyon Izleyici   - Likidasyon & OI izleme")
    print("    11. Korelasyon Analizcisi - BTC dominans & Fear/Greed")
    print("    12. Volatilite Tarayici   - ATR/Bollinger squeeze")
    print("    13. Piyasa Rejimi         - Trend/Range/Volatil tespit")
    print("  [Sinyal & Execution]")
    print("    14. Fiyat Takipcisi       - Gercek zamanli fiyat")
    print("    15. Sinyal Stratejisti    - 12 kaynak sinyal uretimi")
    print("    16. Emir Yoneticisi       - Emir yonetimi")
    print("    17. Risk Yoneticisi       - SL/TP/Kelly/gunluk limit")
    print("    18. Portfoy Takipcisi     - Portfoy & P&L takibi")
    print("  [Raporlama]")
    print("    19. Alarm Merkezi         - Loglama & bildirim")
    print("    20. Sinyal Dogrulayici    - Backtest & kalibrasyon")
    print("    21. Telegram Bildirici    - Mobil bildirimler")
    print()
    print("  [Altyapi]")
    print("    + Binance WebSocket  - Anlik fiyat akisi")
    print("    + SQLite Database    - Kalici veri depolama")
    print("    + Web Dashboard      - http://localhost:5050")
    print()
    print(f"  Pozisyon: {CryptoTradingConfig.MAX_POSITION_SIZE} USDT")
    print(f"  Stop-Loss: %{CryptoTradingConfig.STOP_LOSS_PCT}")
    print(f"  Take-Profit: %{CryptoTradingConfig.TAKE_PROFIT_PCT}")
    print(f"  Max pozisyon: 10 | Günlük kayıp limiti: $200")
    print(f"  Mod: SIMULASYON (gercek para harcanmaz)")
    print(f"  Sure: {DURATION_SECONDS // 60} dakika")
    print("=" * 60)
    print()

    orchestrator = AgentOrchestrator()

    # Dashboard başlat
    dashboard = DashboardServer(orchestrator=orchestrator, port=5050)
    dashboard.start()
    print("  Dashboard: http://localhost:5050")
    print()

    try:
        await orchestrator.start(duration=DURATION_SECONDS)
    except KeyboardInterrupt:
        print("\nKullanici tarafindan durduruldu")
        await orchestrator.stop()
    except Exception as e:
        print(f"Hata: {e}")
        import traceback
        traceback.print_exc()
        await orchestrator.stop()

    # Sonuc raporu
    status = orchestrator.get_status()
    dashboard.stop()

    print()
    print("=" * 60)
    print("  SONUC RAPORU")
    print("=" * 60)

    # Ajan istatistikleri
    print("\n  Ajan Istatistikleri:")
    for name, stats in status.get('agents', {}).items():
        print(f"    {name}: {stats['cycles']} dongu, {stats['errors']} hata")

    # Sinyaller
    signals = status.get('signals', [])
    print(f"\n  Toplam Sinyal: {len(signals)}")
    for s in signals[-10:]:
        print(f"    {s['coin']} {s['action']} ({s['strength']}) "
              f"score={s['sentiment_score']} entry=${s['entry_price']}")

    # Emirler
    orders = status.get('orders', [])
    print(f"\n  Toplam Trade: {len(orders)}")
    for o in orders[-10:]:
        print(f"    {o['coin']} {o['side']} qty={o['quantity']} "
              f"price=${o['price']} status={o['status']}")

    # Portföy
    portfolio = status.get('portfolio', {})
    print(f"\n  Portfoy:")
    print(f"    Toplam trade: {portfolio.get('total_trades', 0)}")
    print(f"    Toplam yatirim: ${portfolio.get('total_invested', 0)}")
    print(f"    Win rate: %{portfolio.get('win_rate', 0)}")

    # Pozisyonlar
    positions = status.get('positions', {})
    print(f"\n  Acik Pozisyon: {positions.get('open_positions', 0)}")
    print(f"  Toplam PnL: ${positions.get('total_pnl', 0)}")
    print(f"  Max Drawdown: ${positions.get('max_drawdown', 0)}")
    print(f"  Kelly Fraction: {positions.get('kelly_fraction', 0)}")
    print(f"  Gunluk Kayip: ${positions.get('daily_loss', 0)} / $200")

    # Backtest
    backtest = status.get('backtest', {})
    print(f"\n  Backtest:")
    print(f"    Dogrulanan sinyal: {backtest.get('total_verified', 0)}")
    print(f"    Dogruluk orani: %{backtest.get('accuracy', 0)}")
    print(f"    Dogru: {backtest.get('correct', 0)} / Yanlis: {backtest.get('wrong', 0)}")
    source_stats = backtest.get('source_stats', {})
    if source_stats:
        print(f"    Kaynak Performansi:")
        for src, stats in source_stats.items():
            print(f"      {src}: %{stats.get('accuracy', 0)} ({stats.get('total', 0)} sinyal)")

    # Piyasa Rejimi
    regime = status.get('market_regime', {})
    print(f"\n  Piyasa Rejimi:")
    print(f"    Genel: {regime.get('market_regime', 'N/A')}")
    regimes = regime.get('regimes', {})
    for coin, r in list(regimes.items())[:5]:
        print(f"    {coin}: {r}")

    # Makro
    macro = status.get('macro', {})
    indicators = macro.get('indicators', {})
    if indicators:
        print(f"\n  Makro Gostergeler:")
        for name, data in indicators.items():
            if data:
                print(f"    {name}: {data.get('value', 'N/A')}")

    # Telegram
    tg = status.get('telegram', {})
    print(f"\n  Telegram:")
    print(f"    Gonderilen: {tg.get('sent_count', 0)} mesaj")
    print(f"    Aktif: {tg.get('enabled', False)}")

    # DB özeti
    db_summary = status.get('db_summary', {})
    print(f"\n  Veritabani:")
    print(f"    Kayitli trade: {db_summary.get('total_trades', 0)}")
    print(f"    Kayitli sinyal: {db_summary.get('total_signals', 0)}")

    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
