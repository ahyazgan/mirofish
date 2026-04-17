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
from .telegram_listener_agent import TelegramListenerAgent
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

        # === VERİ TOPLAMA AJANLARI (11) ===
        self.news_scout = NewsScoutAgent(interval=CryptoTradingConfig.NEWS_SCAN_INTERVAL)
        self.telegram_listener = TelegramListenerAgent(interval=10.0)
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
            self.news_scout, self.telegram_listener, self.social_media, self.whale_tracker,
            self.funding_rate, self.defi_monitor, self.macro_tracker, self.onchain,
            self.event_calendar, self.regulation, self.exchange_listing,
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
        # Daha önce DB'ye yazılmış id'leri hatırla (tekrar INSERT engellemek için).
        # Uzun süreli çalışmada set büyümesin diye MAX_SAVED_IDS ile budanır.
        self._saved_signal_ids: set[str] = set()
        self._saved_order_keys: set[str] = set()
        self._order_key_to_trade_id: dict[str, int] = {}
        # Ajan cycle snapshot'ı (watchdog için)
        self._prev_cycle_counts: dict[str, int] = {}
        self._stale_agent_reports: dict[str, int] = {}

        self._setup_channels()

    # DB'ye yazılmış id set'lerinin büyümesi için tavan — aşılırsa eski id'ler
    # unutulur. DB'de UNIQUE kısıt olduğu için yeniden insert denemesi zararsız.
    MAX_SAVED_IDS = 10000
    # Bir ajan kaç döngü ilerlememişse "zombi" sayılacak (interval katları)
    ZOMBIE_CYCLE_MULTIPLIER = 5

    def _setup_channels(self):
        """Ajanlar arası mesaj kuyruklarını bağla"""

        # ══════════════════════════════════════════════════════════
        # VERİ TOPLAMA → HABER İŞLEME & ANALİZ
        # ══════════════════════════════════════════════════════════

        # News Scout → News Dedup (önce tekrar filtresi)
        self.news_scout.connect('news_dedup', self.news_dedup)
        self.news_scout.connect('alert', self.alert)

        # Telegram Listener → News Dedup (push modda breaking news)
        self.telegram_listener.connect('news_dedup', self.news_dedup)
        self.telegram_listener.connect('alert', self.alert)

        # News Dedup → Sentiment + News Impact + News Verify
        self.news_dedup.connect('sentiment', self.sentiment)
        self.news_dedup.connect('news_impact', self.news_impact)
        self.news_dedup.connect('news_verify', self.news_verify)

        # News Impact → Strategist + Alert
        self.news_impact.connect('strategist', self.strategist)
        self.news_impact.connect('alert', self.alert)

        # News Verify → Strategist + Alert
        self.news_verify.connect('strategist', self.strategist)
        self.news_verify.connect('alert', self.alert)

        # Social Media → Strategist + Alert
        self.social_media.connect('strategist', self.strategist)
        self.social_media.connect('alert', self.alert)

        # Whale Tracker → Strategist + Alert
        self.whale_tracker.connect('strategist', self.strategist)
        self.whale_tracker.connect('alert', self.alert)

        # Funding Rate → Strategist + Alert + Funding Cost
        self.funding_rate.connect('strategist', self.strategist)
        self.funding_rate.connect('alert', self.alert)
        self.funding_rate.connect('funding_cost', self.funding_cost)

        # OnChain → Strategist + Alert
        self.onchain.connect('strategist', self.strategist)
        self.onchain.connect('alert', self.alert)

        # Event Calendar → Strategist + Risk Manager + Alert
        self.event_calendar.connect('strategist', self.strategist)
        self.event_calendar.connect('risk_manager', self.risk_manager)
        self.event_calendar.connect('alert', self.alert)

        # Regulation → Strategist + Alert
        self.regulation.connect('strategist', self.strategist)
        self.regulation.connect('alert', self.alert)

        # Exchange Listing → Strategist + Alert
        self.exchange_listing.connect('strategist', self.strategist)
        self.exchange_listing.connect('alert', self.alert)

        # ══════════════════════════════════════════════════════════
        # ANALİZ → SİNYAL
        # ══════════════════════════════════════════════════════════

        self.sentiment.connect('strategist', self.strategist)
        self.sentiment.connect('alert', self.alert)

        self.technical.connect('strategist', self.strategist)
        self.technical.connect('alert', self.alert)

        self.orderbook.connect('strategist', self.strategist)
        self.orderbook.connect('slippage', self.slippage)
        self.orderbook.connect('alert', self.alert)

        self.liquidation.connect('strategist', self.strategist)
        self.liquidation.connect('alert', self.alert)

        self.correlation.connect('strategist', self.strategist)
        self.correlation.connect('alert', self.alert)

        self.volatility.connect('strategist', self.strategist)
        self.volatility.connect('smart_stop', self.smart_stop)
        self.volatility.connect('alert', self.alert)

        self.market_regime.connect('strategist', self.strategist)
        self.market_regime.connect('alert', self.alert)

        # DeFi & Macro → Strategist + Alert
        self.defi_monitor.connect('strategist', self.strategist)
        self.defi_monitor.connect('alert', self.alert)

        self.macro_tracker.connect('strategist', self.strategist)
        self.macro_tracker.connect('alert', self.alert)

        # ══════════════════════════════════════════════════════════
        # FİYAT → HERKESE
        # ══════════════════════════════════════════════════════════

        self.price_tracker.connect('strategist', self.strategist)
        self.price_tracker.connect('risk_manager', self.risk_manager)
        self.price_tracker.connect('portfolio', self.portfolio)
        self.price_tracker.connect('technical', self.technical)
        self.price_tracker.connect('correlation', self.correlation)
        self.price_tracker.connect('whale_tracker', self.whale_tracker)
        self.price_tracker.connect('backtest', self.backtest)
        self.price_tracker.connect('volatility', self.volatility)
        self.price_tracker.connect('market_regime', self.market_regime)
        self.price_tracker.connect('flash_crash', self.flash_crash)
        self.price_tracker.connect('smart_stop', self.smart_stop)
        self.price_tracker.connect('alert', self.alert)

        # ══════════════════════════════════════════════════════════
        # SİNYAL & EXECUTION AKIŞI
        # ══════════════════════════════════════════════════════════

        # Strategist → Conflict Resolver (sinyaller önce çakışma çözücüden geçer)
        self.strategist.connect('conflict_resolver', self.conflict_resolver)
        self.strategist.connect('backtest', self.backtest)
        self.strategist.connect('alert', self.alert)

        # Conflict Resolver → Executor
        self.conflict_resolver.connect('executor', self.executor)

        # Executor → Position Speed, Slippage, Risk, Portfolio, Alert, Daily Report
        self.executor.connect('position_speed', self.position_speed)
        self.executor.connect('slippage', self.slippage)
        self.executor.connect('risk_manager', self.risk_manager)
        self.executor.connect('portfolio', self.portfolio)
        self.executor.connect('daily_report', self.daily_report)
        self.executor.connect('alert', self.alert)

        # Position Speed → Executor (parçalı emirler)
        self.position_speed.connect('executor', self.executor)

        # Slippage → Executor (slippage kontrolü)
        self.slippage.connect('executor', self.executor)

        # Smart Stop → Risk Manager + Executor
        self.smart_stop.connect('risk_manager', self.risk_manager)
        self.smart_stop.connect('executor', self.executor)

        # Gradual Profit → Executor
        self.gradual_profit.connect('executor', self.executor)
        self.gradual_profit.connect('alert', self.alert)

        # Funding Cost → Strategist + Risk Manager + Alert
        self.funding_cost.connect('strategist', self.strategist)
        self.funding_cost.connect('risk_manager', self.risk_manager)
        self.funding_cost.connect('alert', self.alert)

        # Risk Manager → Executor + Alert + Conflict Resolver
        self.risk_manager.connect('executor', self.executor)
        self.risk_manager.connect('conflict_resolver', self.conflict_resolver)
        self.risk_manager.connect('alert', self.alert)

        # Portfolio → Alert + Drawdown + Balance Verify + Funding Cost + Daily Report
        self.portfolio.connect('alert', self.alert)
        self.portfolio.connect('drawdown', self.drawdown)
        self.portfolio.connect('balance_verify', self.balance_verify)
        self.portfolio.connect('funding_cost', self.funding_cost)
        self.portfolio.connect('daily_report', self.daily_report)

        # ══════════════════════════════════════════════════════════
        # GÜVENLİK AKIŞI
        # ══════════════════════════════════════════════════════════

        # Flash Crash → Kill Switch + Executor + Alert
        self.flash_crash.connect('kill_switch', self.kill_switch)
        self.flash_crash.connect('executor', self.executor)
        self.flash_crash.connect('smart_stop', self.smart_stop)
        self.flash_crash.connect('alert', self.alert)

        # Drawdown → Kill Switch + Risk Manager + Executor + Alert
        self.drawdown.connect('kill_switch', self.kill_switch)
        self.drawdown.connect('risk_manager', self.risk_manager)
        self.drawdown.connect('executor', self.executor)
        self.drawdown.connect('alert', self.alert)

        # API Health → Kill Switch + Alert
        self.api_health.connect('kill_switch', self.kill_switch)
        self.api_health.connect('alert', self.alert)

        # Balance Verify → Kill Switch + Alert
        self.balance_verify.connect('kill_switch', self.kill_switch)
        self.balance_verify.connect('alert', self.alert)

        # Kill Switch → Executor + Risk Manager + Conflict Resolver + Alert
        self.kill_switch.connect('executor', self.executor)
        self.kill_switch.connect('risk_manager', self.risk_manager)
        self.kill_switch.connect('conflict_resolver', self.conflict_resolver)
        self.kill_switch.connect('alert', self.alert)

        # ══════════════════════════════════════════════════════════
        # RAPORLAMA
        # ══════════════════════════════════════════════════════════

        self.backtest.connect('alert', self.alert)
        self.backtest.connect('strategist', self.strategist)

        # Daily Report → Telegram + Alert
        self.daily_report.connect('telegram', self.telegram)
        self.daily_report.connect('alert', self.alert)

        # Alert → Telegram (önemli olaylar)
        self.alert.connect('telegram', self.telegram)

        # Telegram → Kill Switch + Executor (komut dinleme)
        self.telegram.connect('kill_switch', self.kill_switch)
        self.telegram.connect('executor', self.executor)

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
                self.news_scout, self.telegram_listener, self.social_media, self.whale_tracker,
                self.funding_rate, self.defi_monitor, self.macro_tracker, self.onchain,
                self.event_calendar, self.regulation, self.exchange_listing,
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
        tasks.append(asyncio.create_task(self._sl_tp_watch_loop()))

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
        """Periyodik olarak verileri DB'ye kaydet.

        Her bölüm kendi try/except'i ile korunur — tek kayıt hatası diğerlerini
        iptal etmesin. DB çağrıları senkron SQLite fsync içerdiği için
        asyncio.to_thread ile worker thread'e alınır; event loop WS/mesaj
        akışında takılmaz.
        """
        while self._running:
            # Ajan istatistikleri — tüm batch'i tek to_thread ile gönder
            try:
                snapshots = [
                    (a.name, a.stats['cycles'], a.stats['errors'], a.stats)
                    for a in self._agents
                ]
                await asyncio.to_thread(self._write_agent_stats_batch, snapshots)
            except Exception as e:
                logger.error(f"DB sync [agent_stats] hatası: {e}")

            # Fiyatlar (sampling)
            try:
                if self.price_tracker._prev_prices:
                    prices = {
                        coin: pd
                        for coin, pd in list(self.price_tracker._prev_prices.items())[:10]
                        if hasattr(pd, 'price')
                    }
                    if prices:
                        await asyncio.to_thread(self.db.save_prices, prices)
            except Exception as e:
                logger.error(f"DB sync [prices] hatası: {e}")

            # Portfolio snapshot
            try:
                snapshot = {
                    **self.portfolio.portfolio_stats,
                    'open_positions': len(self.risk_manager.positions),
                    'risk_stats': self.risk_manager.risk_stats,
                }
                await asyncio.to_thread(self.db.save_portfolio_snapshot, snapshot)
            except Exception as e:
                logger.error(f"DB sync [portfolio] hatası: {e}")

            # Sinyaller — zaten yazılanları atla (batch)
            try:
                new_signals = [
                    s for s in self.strategist.signal_history
                    if s.get('id') and s['id'] not in self._saved_signal_ids
                ]
                if new_signals:
                    await asyncio.to_thread(self._write_signals_batch, new_signals)
            except Exception as e:
                logger.error(f"DB sync [signals] hatası: {e}")

            # Trade'ler — tüm geçmişi tara (limit=None). Yeni olanları batch yaz.
            try:
                new_orders = []
                for order in self.executor.executor.get_order_history(limit=None):
                    key = f"{order.get('order_id')}:{order.get('signal_id')}"
                    if key not in self._saved_order_keys:
                        new_orders.append((key, order))
                if new_orders:
                    await asyncio.to_thread(self._write_trades_batch, new_orders)
            except Exception as e:
                logger.error(f"DB sync [trades] hatası: {e}")

            # Set kapasitelerini sınırla (uzun çalışmada memory leak olmasın)
            self._prune_saved_ids()

            # Zombi-agent kontrolü
            self._check_zombie_agents()

            await asyncio.sleep(60)

    def _write_agent_stats_batch(self, snapshots):
        """Thread'de çalışan batch writer — event loop'u tıkamaz."""
        for name, cycles, errors, stats in snapshots:
            try:
                self.db.save_agent_stats(name, cycles, errors, stats)
            except Exception as e:
                logger.error(f"save_agent_stats [{name}] hatası: {e}")

    def _write_signals_batch(self, signals):
        for sig in signals:
            try:
                self.db.save_signal(sig)
                self._saved_signal_ids.add(sig['id'])
            except Exception as e:
                logger.error(f"save_signal [{sig.get('id')}] hatası: {e}")

    def _write_trades_batch(self, keyed_orders):
        for key, order in keyed_orders:
            try:
                trade_id = self.db.save_trade(order)
                self._saved_order_keys.add(key)
                if trade_id:
                    self._order_key_to_trade_id[key] = trade_id
            except Exception as e:
                logger.error(f"save_trade [{key}] hatası: {e}")

    def _prune_saved_ids(self):
        """Büyüyen set/dict'leri MAX_SAVED_IDS'a indir. DB UNIQUE kısıtı olduğu
        için unutulmuş id için yeniden INSERT denemesi sadece WARN üretir."""
        if len(self._saved_signal_ids) > self.MAX_SAVED_IDS:
            # Set'ten keyfi bir alt küme al — hangi id'lerin kalacağı önemsiz
            # (DB authoritative). Yarısını tut.
            keep = self.MAX_SAVED_IDS // 2
            self._saved_signal_ids = set(list(self._saved_signal_ids)[-keep:])
        if len(self._saved_order_keys) > self.MAX_SAVED_IDS:
            keep = self.MAX_SAVED_IDS // 2
            dropped = set(list(self._saved_order_keys)[:-keep])
            self._saved_order_keys -= dropped
            for k in dropped:
                self._order_key_to_trade_id.pop(k, None)

    def _check_zombie_agents(self):
        """Bir ajanın döngü sayısı son sync'ten beri artmamışsa zombi say."""
        for agent in self._agents:
            current = agent.stats['cycles']
            prev = self._prev_cycle_counts.get(agent.name)
            self._prev_cycle_counts[agent.name] = current

            if prev is None:
                continue

            # Hiç cycle geçmemiş AND beklenen süre dolmuş AND ajan çalışıyor
            expected_cycles_per_sync = max(1, int(60 / max(agent.interval, 1)))
            if current == prev and agent.is_running:
                self._stale_agent_reports[agent.name] = self._stale_agent_reports.get(agent.name, 0) + 1
                threshold = self.ZOMBIE_CYCLE_MULTIPLIER
                # 60sn/interval < threshold ise ajan normalde yavaş, atla
                if expected_cycles_per_sync >= 1 and self._stale_agent_reports[agent.name] >= threshold:
                    logger.warning(
                        f"ZOMBI AJAN | {agent.name} son {threshold} sync'te hiç cycle "
                        f"ilerletmedi (errors={agent.stats['errors']}, interval={agent.interval}s)"
                    )
                    self._stale_agent_reports[agent.name] = 0
            else:
                self._stale_agent_reports.pop(agent.name, None)

    async def _sl_tp_watch_loop(self):
        """Simülasyon pozisyonlarını hızlı aralıkla SL/TP için tara.

        DB sync her 60sn — o kadar beklersek fiyat SL'i çoktan geçmiş olur.
        Bu döngü 3 saniyede bir kontrol eder ve kapanan pozisyonlar için
        DB.close_trade() çağırır.
        """
        if not CryptoTradingConfig.SIMULATION_MODE:
            return

        while self._running:
            try:
                prev_prices = self.price_tracker._prev_prices
                if prev_prices:
                    closed = self.executor.executor.evaluate_simulated_positions(prev_prices)
                    for c in closed:
                        o = c['order']
                        key = f"{o.order_id}:{o.signal_id}"
                        trade_id = self._order_key_to_trade_id.get(key)
                        if trade_id is None:
                            # Trade henüz DB'ye yazılmamış olabilir — önce yaz, sonra kapat
                            trade_id = await asyncio.to_thread(self.db.save_trade, o.to_dict())
                            self._saved_order_keys.add(key)
                            if trade_id:
                                self._order_key_to_trade_id[key] = trade_id
                        if trade_id:
                            await asyncio.to_thread(
                                self.db.close_trade,
                                trade_id=trade_id,
                                pnl=c['pnl'],
                                pnl_pct=c['pnl_pct'],
                                reason=c['reason'],
                            )
                        # Risk manager'a pozisyon kapandı bildir
                        await self.executor.send('risk_manager', {
                            'type': 'position_closed',
                            'coin': o.coin,
                            'reason': c['reason'],
                            'pnl': c['pnl'],
                        })
                        await self.executor.send('portfolio', {
                            'type': 'position_closed',
                            'coin': o.coin,
                            'reason': c['reason'],
                            'pnl': c['pnl'],
                        })
                        await self.executor.send('conflict_resolver', {
                            'type': 'position_closed',
                            'coin': o.coin,
                        })
            except Exception as e:
                logger.error(f"SL/TP watch hatası: {e}")

            await asyncio.sleep(3)

    async def stop(self):
        """Tüm ajanları durdur"""
        logger.info("Orchestrator durduruluyor...")
        self._running = False

        # WebSocket kapat
        try:
            await self.websocket.stop()
        except Exception as e:
            logger.warning(f"WebSocket kapatma hatası: {e}")

        # Ajanları durdur
        for agent in self._agents:
            try:
                await agent.stop()
            except Exception as e:
                logger.warning(f"Ajan kapatma hatası [{agent.name}]: {e}")

        # Executor'ın httpx client'ını kapat (connection leak olmasın)
        try:
            await self.executor.executor.close()
        except Exception as e:
            logger.warning(f"Executor HTTP client kapatma hatası: {e}")

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
