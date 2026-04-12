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
    print("=" * 64)
    print("  MiroFish Multi-Agent Crypto Trading System")
    print("  40 AJAN ULTRA PRO | WebSocket | DB | Telegram | Dashboard")
    print("=" * 64)
    print()
    print("  [Veri Toplama - 10 Ajan]")
    print("    1.  Haber Kesfedici         - 4 haber kaynagi tarama")
    print("    2.  Sosyal Medya Izleyici   - Reddit sentiment analizi")
    print("    3.  Balina Takipcisi        - Buyuk transfer tespiti")
    print("    4.  Fonlama Orani Izleyici  - Futures fonlama orani")
    print("    5.  DeFi Izleyici           - TVL & DEX hacim takibi")
    print("    6.  Makro Izleyici          - DXY/Altin/S&P500 takibi")
    print("    7.  On-Chain Analizci       - BTC/ETH tx & hash rate")
    print("    8.  Olay Takvimi Takipcisi  - FOMC/CPI/token unlock")
    print("    9.  Regulasyon Takipcisi    - SEC/CFTC haber takibi")
    print("    10. Borsa Listeleme Takipcisi- Yeni listeleme tespiti")
    print("  [Haber Isleme - 3 Ajan]")
    print("    11. Haber Tekrar Filtresi   - Jaccard dedup filtresi")
    print("    12. Haber Etki Siniflandirici- CRITICAL/HIGH/MED/LOW")
    print("    13. Haber Dogrulayici       - Kaynak guvenilirlik skoru")
    print("  [Analiz - 7 Ajan]")
    print("    14. Duygu Analizcisi        - LLM ile haber analizi")
    print("    15. Teknik Analizci         - RSI/MACD/Bollinger/EMA")
    print("    16. Emir Defteri Analizcisi - Alim/satim duvarlari")
    print("    17. Likidasyon Izleyici     - Likidasyon & OI izleme")
    print("    18. Korelasyon Analizcisi   - BTC dominans & Fear/Greed")
    print("    19. Volatilite Tarayici     - ATR/Bollinger squeeze")
    print("    20. Piyasa Rejimi           - Trend/Range/Volatil tespit")
    print("  [Sinyal & Execution - 11 Ajan]")
    print("    21. Fiyat Takipcisi         - Gercek zamanli fiyat")
    print("    22. Sinyal Stratejisti      - 19 kaynak sinyal uretimi")
    print("    23. Cakisma Cozucu          - Celiskili sinyal yonetimi")
    print("    24. Emir Yoneticisi         - Emir yonetimi")
    print("    25. Risk Yoneticisi         - SL/TP/Kelly/gunluk limit")
    print("    26. Portfoy Takipcisi       - Portfoy & P&L takibi")
    print("    27. Pozisyon Hiz Yoneticisi - Kademeli giris stratejisi")
    print("    28. Akilli Stop Ayarlayici  - ATR/trailing/breakeven SL")
    print("    29. Kademeli Kar Alici      - TP1/TP2/TP3 profit taking")
    print("    30. Slippage Hesaplayici    - Emir oncesi slippage tahmin")
    print("    31. Fonlama Maliyet Hesap.  - Futures maliyet kontrolu")
    print("  [Guvenlik - 5 Ajan]")
    print("    32. Kill Switch             - Acil durdurma mekanizmasi")
    print("    33. Flash Crash Koruyucu    - Ani dusus tespiti")
    print("    34. Drawdown Yoneticisi     - Gunluk/toplam DD limiti")
    print("    35. API Saglik Monitoru     - Latency & rate limit izleme")
    print("    36. Bakiye Dogrulayici      - Beklenen vs gercek bakiye")
    print("  [Raporlama - 4 Ajan]")
    print("    37. Alarm Merkezi           - Loglama & bildirim")
    print("    38. Sinyal Dogrulayici      - Backtest & kalibrasyon")
    print("    39. Telegram Bildirici      - Mobil bildirimler")
    print("    40. Gunluk Rapor Ureticisi  - Performans raporu")
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

    # Kill Switch
    ks = status.get('kill_switch', {})
    print(f"\n  Kill Switch:")
    print(f"    Aktif: {ks.get('activated', False)}")
    print(f"    Toplam aktivasyon: {ks.get('total_activations', 0)}")
    if ks.get('reason'):
        print(f"    Son sebep: {ks.get('reason')}")

    # Drawdown
    dd = status.get('drawdown', {})
    print(f"\n  Drawdown:")
    print(f"    Gunluk: %{dd.get('current_daily_dd', 0)}")
    print(f"    Toplam: %{dd.get('current_total_dd', 0)}")
    print(f"    Max gunluk: %{dd.get('max_daily_dd', 0)}")
    print(f"    Max toplam: %{dd.get('max_total_dd', 0)}")
    print(f"    Kayip serisi: {dd.get('losing_streak', 0)}")

    # API Health
    api = status.get('api_health', {})
    print(f"\n  API Saglik:")
    print(f"    Genel: {api.get('overall', 'N/A')}")
    endpoints = api.get('endpoints', {})
    for name, data in endpoints.items():
        print(f"    {name}: {data.get('status', '?')} ({data.get('latency_ms', 0):.0f}ms)")

    # Daily Report
    dr = status.get('daily_report', {})
    print(f"\n  Gunluk Rapor:")
    print(f"    Son rapor: {dr.get('last_report', 'N/A')}")
    print(f"    Toplam rapor: {dr.get('total_reports', 0)}")
    print(f"    Bugunun PnL: ${dr.get('today_pnl', 0)}")

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

    print("=" * 64)


if __name__ == '__main__':
    asyncio.run(main())
