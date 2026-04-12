"""
Agent Orchestrator - Tüm ajanları yönetir
21 ajanı paralel başlatır, aralarındaki iletişimi kurar.
WebSocket, Database ve Telegram entegrasyonu.
"""

import asyncio
import logging
from datetime import datetime, timezone

from .alert_agent import AlertAgent
from .backtest_agent import BacktestAgent
from .correlation_agent import CorrelationAgent
from .defi_monitor_agent import DefiMonitorAgent
from .funding_rate_agent import FundingRateAgent
from .liquidation_agent import LiquidationAgent
from .macro_tracker_agent import MacroTrackerAgent
from .market_regime_agent import MarketRegimeAgent
from .news_scout import NewsScoutAgent
from .orderbook_agent import OrderBookAgent
from .portfolio_tracker import PortfolioTrackerAgent
from .price_tracker import PriceTrackerAgent
from .risk_manager import RiskManagerAgent
from .sentiment_agent import SentimentAgent
from .signal_strategist import SignalStrategistAgent
from .social_media_agent import SocialMediaAgent
from .technical_analysis_agent import TechnicalAnalysisAgent
from .telegram_agent import TelegramAgent
from .trade_executor_agent import TradeExecutorAgent
from .volatility_agent import VolatilityAgent
from .whale_tracker_agent import WhaleTrackerAgent
from ..config import CryptoTradingConfig
from ..database import get_database
from ..websocket_stream import BinanceWebSocket

logger = logging.getLogger('crypto_trading.orchestrator')


class AgentOrchestrator:
    """
    21 ajanı paralel çalıştırır ve aralarındaki iletişimi yönetir.
    + Binance WebSocket anlık fiyat akışı
    + SQLite veritabanı kalıcılığı
    + Telegram bildirimleri

    Mimari Katmanlar:
    ═══════════════════ VERİ TOPLAMA ═══════════════════
      News Scout | Social Media | Whale Tracker | Funding Rate | DeFi Monitor | Macro Tracker
    ═══════════════════ ANALİZ ═════════════════════════
      Sentiment | Technical | Order Book | Liquidation | Correlation | Volatility | Market Regime
    ═══════════════════ SİNYAL & EXECUTION ═════════════
      Price Tracker + WebSocket | Strategist | Executor | Risk | Portfolio
    ═══════════════════ RAPORLAMA ══════════════════════
      Alert Agent | Backtest Agent | Telegram Agent
    """

    def __init__(self):
        # Database
        self.db = get_database()

        # WebSocket
        self.websocket = BinanceWebSocket()

        # === VERİ TOPLAMA AJANLARI ===
        self.news_scout = NewsScoutAgent(interval=CryptoTradingConfig.NEWS_SCAN_INTERVAL)
        self.social_media = SocialMediaAgent(interval=180.0)
        self.whale_tracker = WhaleTrackerAgent(interval=120.0)
        self.funding_rate = FundingRateAgent(interval=300.0)
        self.defi_monitor = DefiMonitorAgent(interval=600.0)
        self.macro_tracker = MacroTrackerAgent(interval=300.0)

        # === ANALİZ AJANLARI ===
        self.sentiment = SentimentAgent(interval=5.0)
        self.technical = TechnicalAnalysisAgent(interval=60.0)
        self.orderbook = OrderBookAgent(interval=60.0)
        self.liquidation = LiquidationAgent(interval=60.0)
        self.correlation = CorrelationAgent(interval=300.0)
        self.volatility = VolatilityAgent(interval=60.0)
        self.market_regime = MarketRegimeAgent(interval=120.0)

        # === SİNYAL & EXECUTION AJANLARI ===
        self.price_tracker = PriceTrackerAgent(interval=CryptoTradingConfig.PRICE_UPDATE_INTERVAL)
        self.strategist = SignalStrategistAgent(interval=5.0)
        self.executor = TradeExecutorAgent(interval=2.0)
        self.risk_manager = RiskManagerAgent(interval=10.0)
        self.portfolio = PortfolioTrackerAgent(interval=30.0)

        # === RAPORLAMA AJANLARI ===
        self.alert = AlertAgent(interval=3.0)
        self.backtest = BacktestAgent(interval=60.0)
        self.telegram = TelegramAgent(interval=5.0)

        self._agents = [
            self.news_scout, self.social_media, self.whale_tracker, self.funding_rate,
            self.defi_monitor, self.macro_tracker,
            self.sentiment, self.technical, self.orderbook, self.liquidation, self.correlation,
            self.volatility, self.market_regime,
            self.price_tracker, self.strategist, self.executor, self.risk_manager, self.portfolio,
            self.alert, self.backtest, self.telegram,
        ]

        self._running = False
        self._started_at = None

        self._setup_channels()

    def _setup_channels(self):
        """Ajanlar arası mesaj kuyruklarını bağla"""
        # ═══ VERİ TOPLAMA → ANALİZ ═══
        self.news_scout.connect('sentiment', self.sentiment._inbox)
        self.news_scout.connect('alert', self.alert._inbox)

        self.social_media.connect('strategist', self.strategist._inbox)
        self.social_media.connect('alert', self.alert._inbox)

        self.whale_tracker.connect('strategist', self.strategist._inbox)
        self.whale_tracker.connect('alert', self.alert._inbox)

        self.funding_rate.connect('strategist', self.strategist._inbox)
        self.funding_rate.connect('alert', self.alert._inbox)

        # ═══ ANALİZ → SİNYAL ═══
        self.sentiment.connect('strategist', self.strategist._inbox)
        self.sentiment.connect('alert', self.alert._inbox)

        self.technical.connect('strategist', self.strategist._inbox)
        self.technical.connect('alert', self.alert._inbox)

        self.orderbook.connect('strategist', self.strategist._inbox)
        self.orderbook.connect('alert', self.alert._inbox)

        self.liquidation.connect('strategist', self.strategist._inbox)
        self.liquidation.connect('alert', self.alert._inbox)

        self.correlation.connect('strategist', self.strategist._inbox)
        self.correlation.connect('alert', self.alert._inbox)

        self.volatility.connect('strategist', self.strategist._inbox)
        self.volatility.connect('alert', self.alert._inbox)

        self.market_regime.connect('strategist', self.strategist._inbox)
        self.market_regime.connect('alert', self.alert._inbox)

        # ═══ VERİ TOPLAMA → SİNYAL ═══
        self.defi_monitor.connect('strategist', self.strategist._inbox)
        self.defi_monitor.connect('alert', self.alert._inbox)

        self.macro_tracker.connect('strategist', self.strategist._inbox)
        self.macro_tracker.connect('alert', self.alert._inbox)

        # ═══ FİYAT → HERKESE ═══
        self.price_tracker.connect('strategist', self.strategist._inbox)
        self.price_tracker.connect('risk_manager', self.risk_manager._inbox)
        self.price_tracker.connect('portfolio', self.portfolio._inbox)
        self.price_tracker.connect('technical', self.technical._inbox)
        self.price_tracker.connect('correlation', self.correlation._inbox)
        self.price_tracker.connect('whale_tracker', self.whale_tracker._inbox)
        self.price_tracker.connect('backtest', self.backtest._inbox)
        self.price_tracker.connect('volatility', self.volatility._inbox)
        self.price_tracker.connect('market_regime', self.market_regime._inbox)
        self.price_tracker.connect('alert', self.alert._inbox)

        # ═══ SİNYAL → EXECUTION ═══
        self.strategist.connect('executor', self.executor._inbox)
        self.strategist.connect('backtest', self.backtest._inbox)
        self.strategist.connect('alert', self.alert._inbox)

        self.executor.connect('risk_manager', self.risk_manager._inbox)
        self.executor.connect('portfolio', self.portfolio._inbox)
        self.executor.connect('alert', self.alert._inbox)

        self.risk_manager.connect('executor', self.executor._inbox)
        self.risk_manager.connect('alert', self.alert._inbox)

        self.portfolio.connect('alert', self.alert._inbox)

        # ═══ RAPORLAMA ═══
        self.backtest.connect('alert', self.alert._inbox)
        self.backtest.connect('strategist', self.strategist._inbox)

        # Alert → Telegram (önemli olaylar)
        self.alert.connect('telegram', self.telegram._inbox)

    async def start(self, duration: int = None):
        """Tüm ajanları paralel başlat"""
        errors, warnings = CryptoTradingConfig.validate()
        if errors:
            logger.error(f"Config hataları: {errors}")
            return

        for w in warnings:
            logger.warning(w)

        self._running = True
        self._started_at = datetime.now(timezone.utc)

        logger.info("=" * 60)
        logger.info("  MiroFish Multi-Agent Trading System")
        logger.info("  21 AJAN PRO EDITION + WebSocket + DB + Telegram")
        logger.info("=" * 60)
        logger.info(f"  Ajanlar: {len(self._agents)}")

        categories = {
            'Veri Toplama': [self.news_scout, self.social_media, self.whale_tracker, self.funding_rate, self.defi_monitor, self.macro_tracker],
            'Analiz': [self.sentiment, self.technical, self.orderbook, self.liquidation, self.correlation, self.volatility, self.market_regime],
            'Sinyal & Execution': [self.price_tracker, self.strategist, self.executor, self.risk_manager, self.portfolio],
            'Raporlama': [self.alert, self.backtest, self.telegram],
        }
        for cat_name, cat_agents in categories.items():
            logger.info(f"  [{cat_name}]")
            for agent in cat_agents:
                logger.info(f"    - {agent.name} (interval={agent.interval}s)")

        logger.info(f"  Mod: {'TESTNET' if CryptoTradingConfig.BINANCE_TESTNET else 'MAINNET'}")
        logger.info(f"  Pozisyon: {CryptoTradingConfig.MAX_POSITION_SIZE} USDT")
        logger.info(f"  SL: %{CryptoTradingConfig.STOP_LOSS_PCT} / TP: %{CryptoTradingConfig.TAKE_PROFIT_PCT}")
        logger.info(f"  WebSocket: Aktif (anlık fiyat)")
        logger.info(f"  Veritabanı: SQLite ({self.db.db_path})")
        logger.info(f"  Telegram: {'Aktif' if self.telegram._enabled else 'Demo mod'}")
        if duration:
            logger.info(f"  Sure: {duration} saniye ({duration//60} dakika)")
        else:
            logger.info(f"  Sure: 7/24 (durdurana kadar)")
        logger.info("=" * 60)

        # DB'ye başlangıç kaydı
        self.db.save_event('system_start', 'orchestrator', {
            'agent_count': len(self._agents),
            'mode': 'TESTNET' if CryptoTradingConfig.BINANCE_TESTNET else 'MAINNET',
            'duration': duration,
        })

        # Tüm ajanları + WebSocket paralel başlat
        tasks = [asyncio.create_task(agent.start()) for agent in self._agents]
        tasks.append(asyncio.create_task(self._run_websocket()))
        tasks.append(asyncio.create_task(self._db_sync_loop()))

        if duration:
            await asyncio.sleep(duration)
            await self.stop()
        else:
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                await self.stop()

    async def _run_websocket(self):
        """WebSocket stream'i başlat ve fiyat güncellemelerini dağıt"""
        try:
            await self.websocket.start()
        except Exception as e:
            logger.warning(f"WebSocket hatası (REST API fallback aktif): {e}")

    async def _db_sync_loop(self):
        """Periyodik olarak verileri DB'ye kaydet"""
        while self._running:
            try:
                # Ajan istatistiklerini kaydet
                for agent in self._agents:
                    self.db.save_agent_stats(
                        agent.name,
                        agent.stats['cycles'],
                        agent.stats['errors'],
                        agent.stats,
                    )

                # Fiyatları kaydet (sampling)
                if self.price_tracker._prev_prices:
                    prices = {}
                    for coin, price_data in list(self.price_tracker._prev_prices.items())[:10]:
                        if hasattr(price_data, 'price'):
                            prices[coin] = price_data
                    if prices:
                        self.db.save_prices(prices)

                # Portfolio snapshot
                self.db.save_portfolio_snapshot({
                    **self.portfolio.portfolio_stats,
                    'open_positions': len(self.risk_manager.positions),
                    'risk_stats': self.risk_manager.risk_stats,
                })

            except Exception as e:
                logger.error(f"DB sync hatası: {e}")

            await asyncio.sleep(60)  # Her dakika

    async def stop(self):
        """Tüm ajanları durdur"""
        logger.info("Orchestrator durduruluyor...")
        self._running = False

        # WebSocket kapat
        await self.websocket.stop()

        # Ajanları durdur
        for agent in self._agents:
            await agent.stop()

        # DB'ye kapanış kaydı
        self.db.save_event('system_stop', 'orchestrator', {
            'started_at': self._started_at.isoformat() if self._started_at else None,
            'summary': self.get_status(),
        })

        logger.info("Tüm ajanlar durduruldu")

    def get_status(self) -> dict:
        """Tam sistem durumu"""
        return {
            'running': self._running,
            'started_at': self._started_at.isoformat() if self._started_at else None,
            'agent_count': len(self._agents),
            'agents': {agent.name: agent.stats for agent in self._agents},
            'signals': self.strategist.signal_history[-20:],
            'orders': self.executor.executor.get_order_history(20),
            'positions': self.risk_manager.risk_stats,
            'portfolio': self.portfolio.portfolio_stats,
            'backtest': self.backtest.backtest_stats,
            'market_regime': self.market_regime.regime_stats,
            'macro': self.macro_tracker.macro_stats,
            'telegram': self.telegram.telegram_stats,
            'recent_events': self.alert.events[-20:],
            'db_summary': self.db.get_dashboard_summary(),
        }
