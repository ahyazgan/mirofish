"""
Agent Orchestrator - Tüm ajanları yönetir
40 ajanı paralel başlatır, aralarındaki iletişimi kurar.
WebSocket, Database ve Telegram entegrasyonu.
"""

import asyncio
import logging
from datetime import datetime, timezone

# === VERİ TOPLAMA AJANLARI ===
from .news_scout import NewsScoutAgent
from .social_media_agent import SocialMediaAgent
from .whale_tracker_agent import WhaleTrackerAgent
from .funding_rate_agent import FundingRateAgent
from .defi_monitor_agent import DefiMonitorAgent
from .macro_tracker_agent import MacroTrackerAgent
from .onchain_agent import OnChainAgent
from .event_calendar_agent import EventCalendarAgent
from .regulation_agent import RegulationAgent
from .exchange_listing_agent import ExchangeListingAgent

# === HABER İŞLEME AJANLARI ===
from .news_dedup_agent import NewsDedupAgent
from .news_impact_agent import NewsImpactAgent
from .news_verify_agent import NewsVerifyAgent

# === ANALİZ AJANLARI ===
from .sentiment_agent import SentimentAgent
from .technical_analysis_agent import TechnicalAnalysisAgent
from .orderbook_agent import OrderBookAgent
from .liquidation_agent import LiquidationAgent
from .correlation_agent import CorrelationAgent
from .volatility_agent import VolatilityAgent
from .market_regime_agent import MarketRegimeAgent

# === SİNYAL & EXECUTION AJANLARI ===
from .price_tracker import PriceTrackerAgent
from .signal_strategist import SignalStrategistAgent
from .conflict_resolver_agent import ConflictResolverAgent
from .trade_executor_agent import TradeExecutorAgent
from .risk_manager import RiskManagerAgent
from .portfolio_tracker import PortfolioTrackerAgent
from .position_speed_agent import PositionSpeedAgent
from .smart_stop_agent import SmartStopAgent
from .gradual_profit_agent import GradualProfitAgent
from .slippage_agent import SlippageAgent
from .funding_cost_agent import FundingCostAgent

# === GÜVENLİK AJANLARI ===
from .kill_switch_agent import KillSwitchAgent
from .flash_crash_agent import FlashCrashAgent
from .drawdown_agent import DrawdownAgent
from .api_health_agent import ApiHealthAgent
from .balance_verify_agent import BalanceVerifyAgent

# === RAPORLAMA AJANLARI ===
from .alert_agent import AlertAgent
from .backtest_agent import BacktestAgent
from .telegram_agent import TelegramAgent
from .daily_report_agent import DailyReportAgent

from ..config import CryptoTradingConfig
from ..database import get_database
from ..websocket_stream import BinanceWebSocket

logger = logging.getLogger('crypto_trading.orchestrator')


class AgentOrchestrator:
    """
    40 ajanı paralel çalıştırır ve aralarındaki iletişimi yönetir.
    + Binance WebSocket anlık fiyat akışı
    + SQLite veritabanı kalıcılığı
    + Telegram bildirimleri

    Mimari Katmanlar:
    ═══════════════════ VERİ TOPLAMA ═══════════════════════
      News Scout | Social Media | Whale Tracker | Funding Rate
      DeFi Monitor | Macro Tracker | OnChain | Event Calendar
      Regulation | Exchange Listing
    ═══════════════════ HABER İŞLEME ══════════════════════
      News Dedup | News Impact | News Verify
    ═══════════════════ ANALİZ ═════════════════════════════
      Sentiment | Technical | Order Book | Liquidation
      Correlation | Volatility | Market Regime
    ═══════════════════ SİNYAL & EXECUTION ═════════════════
      Price Tracker + WebSocket | Strategist | Conflict Resolver
      Executor | Risk | Portfolio | Position Speed
      Smart Stop | Gradual Profit | Slippage | Funding Cost
    ═══════════════════ GÜVENLİK ══════════════════════════
      Kill Switch | Flash Crash | Drawdown | API Health | Balance Verify
    ═══════════════════ RAPORLAMA ══════════════════════════
      Alert Agent | Backtest Agent | Telegram Agent | Daily Report
    """

    def __init__(self):
        # Database
        self.db = get_database()

        # WebSocket
        self.websocket = BinanceWebSocket()

        # === VERİ TOPLAMA AJANLARI (10) ===
        self.news_scout = NewsScoutAgent(interval=CryptoTradingConfig.NEWS_SCAN_INTERVAL)
        self.social_media = SocialMediaAgent(interval=180.0)
        self.whale_tracker = WhaleTrackerAgent(interval=120.0)
        self.funding_rate = FundingRateAgent(interval=300.0)
        self.defi_monitor = DefiMonitorAgent(interval=600.0)
        self.macro_tracker = MacroTrackerAgent(interval=300.0)
        self.onchain = OnChainAgent(interval=600.0)
        self.event_calendar = EventCalendarAgent(interval=1800.0)
        self.regulation = RegulationAgent(interval=300.0)
        self.exchange_listing = ExchangeListingAgent(interval=300.0)

        # === HABER İŞLEME AJANLARI (3) ===
        self.news_dedup = NewsDedupAgent(interval=5.0)
        self.news_impact = NewsImpactAgent(interval=5.0)
        self.news_verify = NewsVerifyAgent(interval=5.0)

        # === ANALİZ AJANLARI (7) ===
        self.sentiment = SentimentAgent(interval=5.0)
        self.technical = TechnicalAnalysisAgent(interval=60.0)
        self.orderbook = OrderBookAgent(interval=60.0)
        self.liquidation = LiquidationAgent(interval=60.0)
        self.correlation = CorrelationAgent(interval=300.0)
        self.volatility = VolatilityAgent(interval=60.0)
        self.market_regime = MarketRegimeAgent(interval=120.0)

        # === SİNYAL & EXECUTION AJANLARI (11) ===
        self.price_tracker = PriceTrackerAgent(interval=CryptoTradingConfig.PRICE_UPDATE_INTERVAL)
        self.strategist = SignalStrategistAgent(interval=5.0)
        self.conflict_resolver = ConflictResolverAgent(interval=3.0)
        self.executor = TradeExecutorAgent(interval=2.0)
        self.risk_manager = RiskManagerAgent(interval=10.0)
        self.portfolio = PortfolioTrackerAgent(interval=30.0)
        self.position_speed = PositionSpeedAgent(interval=3.0)
        self.smart_stop = SmartStopAgent(interval=5.0)
        self.gradual_profit = GradualProfitAgent(interval=5.0)
        self.slippage = SlippageAgent(interval=5.0)
        self.funding_cost = FundingCostAgent(interval=30.0)

        # === GÜVENLİK AJANLARI (5) ===
        self.kill_switch = KillSwitchAgent(interval=2.0)
        self.flash_crash = FlashCrashAgent(interval=5.0)
        self.drawdown = DrawdownAgent(interval=10.0)
        self.api_health = ApiHealthAgent(interval=10.0)
        self.balance_verify = BalanceVerifyAgent(interval=300.0)

        # === RAPORLAMA AJANLARI (4) ===
        self.alert = AlertAgent(interval=3.0)
        self.backtest = BacktestAgent(interval=60.0)
        self.telegram = TelegramAgent(interval=5.0)
        self.daily_report = DailyReportAgent(interval=60.0)

        self._agents = [
            # Veri Toplama
            self.news_scout, self.social_media, self.whale_tracker, self.funding_rate,
            self.defi_monitor, self.macro_tracker, self.onchain, self.event_calendar,
            self.regulation, self.exchange_listing,
            # Haber İşleme
            self.news_dedup, self.news_impact, self.news_verify,
            # Analiz
            self.sentiment, self.technical, self.orderbook, self.liquidation,
            self.correlation, self.volatility, self.market_regime,
            # Sinyal & Execution
            self.price_tracker, self.strategist, self.conflict_resolver, self.executor,
            self.risk_manager, self.portfolio, self.position_speed, self.smart_stop,
            self.gradual_profit, self.slippage, self.funding_cost,
            # Güvenlik
            self.kill_switch, self.flash_crash, self.drawdown, self.api_health,
            self.balance_verify,
            # Raporlama
            self.alert, self.backtest, self.telegram, self.daily_report,
        ]

        self._running = False
        self._started_at = None

        self._setup_channels()

    def _setup_channels(self):
        """Ajanlar arası mesaj kuyruklarını bağla"""

        # ══════════════════════════════════════════════════════════
        # VERİ TOPLAMA → HABER İŞLEME & ANALİZ
        # ══════════════════════════════════════════════════════════

        # News Scout → News Dedup (önce tekrar filtresi)
        self.news_scout.connect('news_dedup', self.news_dedup._inbox)
        self.news_scout.connect('alert', self.alert._inbox)

        # News Dedup → Sentiment + News Impact + News Verify
        self.news_dedup.connect('sentiment', self.sentiment._inbox)
        self.news_dedup.connect('news_impact', self.news_impact._inbox)
        self.news_dedup.connect('news_verify', self.news_verify._inbox)

        # News Impact → Strategist + Alert
        self.news_impact.connect('strategist', self.strategist._inbox)
        self.news_impact.connect('alert', self.alert._inbox)

        # News Verify → Strategist + Alert
        self.news_verify.connect('strategist', self.strategist._inbox)
        self.news_verify.connect('alert', self.alert._inbox)

        # Social Media → Strategist + Alert
        self.social_media.connect('strategist', self.strategist._inbox)
        self.social_media.connect('alert', self.alert._inbox)

        # Whale Tracker → Strategist + Alert
        self.whale_tracker.connect('strategist', self.strategist._inbox)
        self.whale_tracker.connect('alert', self.alert._inbox)

        # Funding Rate → Strategist + Alert + Funding Cost
        self.funding_rate.connect('strategist', self.strategist._inbox)
        self.funding_rate.connect('alert', self.alert._inbox)
        self.funding_rate.connect('funding_cost', self.funding_cost._inbox)

        # OnChain → Strategist + Alert
        self.onchain.connect('strategist', self.strategist._inbox)
        self.onchain.connect('alert', self.alert._inbox)

        # Event Calendar → Strategist + Risk Manager + Alert
        self.event_calendar.connect('strategist', self.strategist._inbox)
        self.event_calendar.connect('risk_manager', self.risk_manager._inbox)
        self.event_calendar.connect('alert', self.alert._inbox)

        # Regulation → Strategist + Alert
        self.regulation.connect('strategist', self.strategist._inbox)
        self.regulation.connect('alert', self.alert._inbox)

        # Exchange Listing → Strategist + Alert
        self.exchange_listing.connect('strategist', self.strategist._inbox)
        self.exchange_listing.connect('alert', self.alert._inbox)

        # ══════════════════════════════════════════════════════════
        # ANALİZ → SİNYAL
        # ══════════════════════════════════════════════════════════

        self.sentiment.connect('strategist', self.strategist._inbox)
        self.sentiment.connect('alert', self.alert._inbox)

        self.technical.connect('strategist', self.strategist._inbox)
        self.technical.connect('alert', self.alert._inbox)

        self.orderbook.connect('strategist', self.strategist._inbox)
        self.orderbook.connect('slippage', self.slippage._inbox)
        self.orderbook.connect('alert', self.alert._inbox)

        self.liquidation.connect('strategist', self.strategist._inbox)
        self.liquidation.connect('alert', self.alert._inbox)

        self.correlation.connect('strategist', self.strategist._inbox)
        self.correlation.connect('alert', self.alert._inbox)

        self.volatility.connect('strategist', self.strategist._inbox)
        self.volatility.connect('smart_stop', self.smart_stop._inbox)
        self.volatility.connect('alert', self.alert._inbox)

        self.market_regime.connect('strategist', self.strategist._inbox)
        self.market_regime.connect('alert', self.alert._inbox)

        # DeFi & Macro → Strategist + Alert
        self.defi_monitor.connect('strategist', self.strategist._inbox)
        self.defi_monitor.connect('alert', self.alert._inbox)

        self.macro_tracker.connect('strategist', self.strategist._inbox)
        self.macro_tracker.connect('alert', self.alert._inbox)

        # ══════════════════════════════════════════════════════════
        # FİYAT → HERKESE
        # ══════════════════════════════════════════════════════════

        self.price_tracker.connect('strategist', self.strategist._inbox)
        self.price_tracker.connect('risk_manager', self.risk_manager._inbox)
        self.price_tracker.connect('portfolio', self.portfolio._inbox)
        self.price_tracker.connect('technical', self.technical._inbox)
        self.price_tracker.connect('correlation', self.correlation._inbox)
        self.price_tracker.connect('whale_tracker', self.whale_tracker._inbox)
        self.price_tracker.connect('backtest', self.backtest._inbox)
        self.price_tracker.connect('volatility', self.volatility._inbox)
        self.price_tracker.connect('market_regime', self.market_regime._inbox)
        self.price_tracker.connect('flash_crash', self.flash_crash._inbox)
        self.price_tracker.connect('smart_stop', self.smart_stop._inbox)
        self.price_tracker.connect('alert', self.alert._inbox)

        # ══════════════════════════════════════════════════════════
        # SİNYAL & EXECUTION AKIŞI
        # ══════════════════════════════════════════════════════════

        # Strategist → Conflict Resolver (sinyaller önce çakışma çözücüden geçer)
        self.strategist.connect('conflict_resolver', self.conflict_resolver._inbox)
        self.strategist.connect('backtest', self.backtest._inbox)
        self.strategist.connect('alert', self.alert._inbox)

        # Conflict Resolver → Executor
        self.conflict_resolver.connect('executor', self.executor._inbox)

        # Executor → Position Speed, Slippage, Risk, Portfolio, Alert, Daily Report
        self.executor.connect('position_speed', self.position_speed._inbox)
        self.executor.connect('slippage', self.slippage._inbox)
        self.executor.connect('risk_manager', self.risk_manager._inbox)
        self.executor.connect('portfolio', self.portfolio._inbox)
        self.executor.connect('daily_report', self.daily_report._inbox)
        self.executor.connect('alert', self.alert._inbox)

        # Position Speed → Executor (parçalı emirler)
        self.position_speed.connect('executor', self.executor._inbox)

        # Slippage → Executor (slippage kontrolü)
        self.slippage.connect('executor', self.executor._inbox)

        # Smart Stop → Risk Manager + Executor
        self.smart_stop.connect('risk_manager', self.risk_manager._inbox)
        self.smart_stop.connect('executor', self.executor._inbox)

        # Gradual Profit → Executor
        self.gradual_profit.connect('executor', self.executor._inbox)
        self.gradual_profit.connect('alert', self.alert._inbox)

        # Funding Cost → Strategist + Risk Manager + Alert
        self.funding_cost.connect('strategist', self.strategist._inbox)
        self.funding_cost.connect('risk_manager', self.risk_manager._inbox)
        self.funding_cost.connect('alert', self.alert._inbox)

        # Risk Manager → Executor + Alert + Conflict Resolver
        self.risk_manager.connect('executor', self.executor._inbox)
        self.risk_manager.connect('conflict_resolver', self.conflict_resolver._inbox)
        self.risk_manager.connect('alert', self.alert._inbox)

        # Portfolio → Alert + Drawdown + Balance Verify + Funding Cost + Daily Report
        self.portfolio.connect('alert', self.alert._inbox)
        self.portfolio.connect('drawdown', self.drawdown._inbox)
        self.portfolio.connect('balance_verify', self.balance_verify._inbox)
        self.portfolio.connect('funding_cost', self.funding_cost._inbox)
        self.portfolio.connect('daily_report', self.daily_report._inbox)

        # ══════════════════════════════════════════════════════════
        # GÜVENLİK AKIŞI
        # ══════════════════════════════════════════════════════════

        # Flash Crash → Kill Switch + Executor + Alert
        self.flash_crash.connect('kill_switch', self.kill_switch._inbox)
        self.flash_crash.connect('executor', self.executor._inbox)
        self.flash_crash.connect('smart_stop', self.smart_stop._inbox)
        self.flash_crash.connect('alert', self.alert._inbox)

        # Drawdown → Kill Switch + Risk Manager + Executor + Alert
        self.drawdown.connect('kill_switch', self.kill_switch._inbox)
        self.drawdown.connect('risk_manager', self.risk_manager._inbox)
        self.drawdown.connect('executor', self.executor._inbox)
        self.drawdown.connect('alert', self.alert._inbox)

        # API Health → Kill Switch + Alert
        self.api_health.connect('kill_switch', self.kill_switch._inbox)
        self.api_health.connect('alert', self.alert._inbox)

        # Balance Verify → Kill Switch + Alert
        self.balance_verify.connect('kill_switch', self.kill_switch._inbox)
        self.balance_verify.connect('alert', self.alert._inbox)

        # Kill Switch → Executor + Risk Manager + Conflict Resolver + Alert
        self.kill_switch.connect('executor', self.executor._inbox)
        self.kill_switch.connect('risk_manager', self.risk_manager._inbox)
        self.kill_switch.connect('conflict_resolver', self.conflict_resolver._inbox)
        self.kill_switch.connect('alert', self.alert._inbox)

        # ══════════════════════════════════════════════════════════
        # RAPORLAMA
        # ══════════════════════════════════════════════════════════

        self.backtest.connect('alert', self.alert._inbox)
        self.backtest.connect('strategist', self.strategist._inbox)

        # Daily Report → Telegram + Alert
        self.daily_report.connect('telegram', self.telegram._inbox)
        self.daily_report.connect('alert', self.alert._inbox)

        # Alert → Telegram (önemli olaylar)
        self.alert.connect('telegram', self.telegram._inbox)

        # Telegram → Kill Switch + Executor (komut dinleme)
        self.telegram.connect('kill_switch', self.kill_switch._inbox)
        self.telegram.connect('executor', self.executor._inbox)

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
        logger.info("  40 AJAN ULTRA PRO | WebSocket | DB | Telegram")
        logger.info("=" * 60)
        logger.info(f"  Ajanlar: {len(self._agents)}")

        categories = {
            'Veri Toplama': [
                self.news_scout, self.social_media, self.whale_tracker, self.funding_rate,
                self.defi_monitor, self.macro_tracker, self.onchain, self.event_calendar,
                self.regulation, self.exchange_listing,
            ],
            'Haber Isleme': [self.news_dedup, self.news_impact, self.news_verify],
            'Analiz': [
                self.sentiment, self.technical, self.orderbook, self.liquidation,
                self.correlation, self.volatility, self.market_regime,
            ],
            'Sinyal & Execution': [
                self.price_tracker, self.strategist, self.conflict_resolver, self.executor,
                self.risk_manager, self.portfolio, self.position_speed, self.smart_stop,
                self.gradual_profit, self.slippage, self.funding_cost,
            ],
            'Guvenlik': [
                self.kill_switch, self.flash_crash, self.drawdown, self.api_health,
                self.balance_verify,
            ],
            'Raporlama': [self.alert, self.backtest, self.telegram, self.daily_report],
        }
        for cat_name, cat_agents in categories.items():
            logger.info(f"  [{cat_name}] ({len(cat_agents)} ajan)")
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
            'kill_switch': self.kill_switch.kill_switch_stats,
            'drawdown': self.drawdown.drawdown_stats,
            'api_health': self.api_health.health_stats,
            'daily_report': self.daily_report.report_stats,
            'recent_events': self.alert.events[-20:],
            'db_summary': self.db.get_dashboard_summary(),
        }
