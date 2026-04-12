"""
SQLite Database Layer - Kalıcı veri depolama
Trade'ler, sinyaller, olaylar ve performans verileri.
"""

import sqlite3
import json
import os
import threading
from datetime import datetime, timezone
from contextlib import contextmanager


class TradingDatabase:
    """Thread-safe SQLite veritabanı"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # backend/data/ klasörü
            backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
            db_dir = os.path.join(backend_dir, 'data')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, 'trading.db')

        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self):
        """Tabloları oluştur"""
        with self._cursor() as c:
            # Sinyaller
            c.execute('''CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                coin TEXT NOT NULL,
                action TEXT NOT NULL,
                strength TEXT NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                position_size_usdt REAL,
                sentiment_score REAL,
                confidence REAL,
                reasons TEXT,
                sources TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # Trade'ler
            c.execute('''CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT,
                coin TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL,
                price REAL,
                size_usdt REAL,
                status TEXT DEFAULT 'SIMULATED',
                pnl REAL DEFAULT 0,
                pnl_pct REAL DEFAULT 0,
                closed_at TEXT,
                close_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            )''')

            # Olaylar (event log)
            c.execute('''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT,
                data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # Ajan istatistikleri
            c.execute('''CREATE TABLE IF NOT EXISTS agent_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                cycles INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                snapshot TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # Fiyat geçmişi (sampling)
            c.execute('''CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                price REAL,
                change_1h REAL,
                change_24h REAL,
                volume REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # Backtest sonuçları
            c.execute('''CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT,
                coin TEXT,
                action TEXT,
                entry_price REAL,
                verify_price REAL,
                price_change_pct REAL,
                correct INTEGER,
                source_scores TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT
            )''')

            # Portföy snapshot'ları
            c.execute('''CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_trades INTEGER,
                total_invested REAL,
                total_pnl REAL,
                win_rate REAL,
                open_positions INTEGER,
                snapshot TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # İndeksler
            c.execute('CREATE INDEX IF NOT EXISTS idx_signals_coin ON signals(coin)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_trades_coin ON trades(coin)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_price_coin ON price_history(coin)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_price_created ON price_history(created_at)')

    # ══════��════════ SIGNAL OPERATIONS ═══════════════

    def save_signal(self, signal: dict):
        with self._cursor() as c:
            c.execute('''INSERT OR REPLACE INTO signals
                (id, coin, action, strength, entry_price, stop_loss, take_profit,
                 position_size_usdt, sentiment_score, confidence, reasons, sources, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (signal.get('id'), signal.get('coin'), signal.get('action'),
                 signal.get('strength'), signal.get('entry_price'),
                 signal.get('stop_loss'), signal.get('take_profit'),
                 signal.get('position_size_usdt'), signal.get('sentiment_score'),
                 signal.get('confidence'),
                 json.dumps(signal.get('reasons', []), ensure_ascii=False),
                 signal.get('sources', ''),
                 datetime.now(timezone.utc).isoformat()))

    def get_signals(self, limit: int = 50, coin: str = None) -> list[dict]:
        with self._cursor() as c:
            if coin:
                c.execute('SELECT * FROM signals WHERE coin=? ORDER BY created_at DESC LIMIT ?',
                         (coin, limit))
            else:
                c.execute('SELECT * FROM signals ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in c.fetchall()]

    # ═══════════════ TRADE OPERATIONS ═══════════════

    def save_trade(self, trade: dict):
        with self._cursor() as c:
            c.execute('''INSERT INTO trades
                (signal_id, coin, side, quantity, price, size_usdt, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (trade.get('signal_id'), trade.get('coin'), trade.get('side'),
                 trade.get('quantity'), trade.get('price'), trade.get('size_usdt'),
                 trade.get('status', 'SIMULATED'),
                 datetime.now(timezone.utc).isoformat()))
            return c.lastrowid

    def close_trade(self, trade_id: int, pnl: float, pnl_pct: float, reason: str):
        with self._cursor() as c:
            c.execute('''UPDATE trades SET pnl=?, pnl_pct=?, close_reason=?,
                closed_at=? WHERE id=?''',
                (pnl, pnl_pct, reason, datetime.now(timezone.utc).isoformat(), trade_id))

    def get_trades(self, limit: int = 50, coin: str = None) -> list[dict]:
        with self._cursor() as c:
            if coin:
                c.execute('SELECT * FROM trades WHERE coin=? ORDER BY created_at DESC LIMIT ?',
                         (coin, limit))
            else:
                c.execute('SELECT * FROM trades ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in c.fetchall()]

    def get_open_trades(self) -> list[dict]:
        with self._cursor() as c:
            c.execute('SELECT * FROM trades WHERE closed_at IS NULL ORDER BY created_at DESC')
            return [dict(row) for row in c.fetchall()]

    # ═══════════════ EVENT OPERATIONS ═══════════════

    def save_event(self, event_type: str, source: str, data: dict):
        with self._cursor() as c:
            c.execute('INSERT INTO events (event_type, source, data, created_at) VALUES (?, ?, ?, ?)',
                (event_type, source,
                 json.dumps(data, ensure_ascii=False, default=str),
                 datetime.now(timezone.utc).isoformat()))

    def get_events(self, limit: int = 100, event_type: str = None) -> list[dict]:
        with self._cursor() as c:
            if event_type:
                c.execute('SELECT * FROM events WHERE event_type=? ORDER BY created_at DESC LIMIT ?',
                         (event_type, limit))
            else:
                c.execute('SELECT * FROM events ORDER BY created_at DESC LIMIT ?', (limit,))
            rows = c.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get('data'):
                    try:
                        d['data'] = json.loads(d['data'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results

    # ═══════════════ PRICE OPERATIONS ═══════════════

    def save_prices(self, prices: dict):
        """Fiyat snapshot kaydet (sampling - her kayıtta tüm coinleri kaydetmez)"""
        with self._cursor() as c:
            now = datetime.now(timezone.utc).isoformat()
            for coin, data in prices.items():
                if hasattr(data, 'price'):
                    c.execute('''INSERT INTO price_history
                        (coin, price, change_1h, change_24h, volume, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                        (coin, data.price, data.change_1h, data.change_24h,
                         data.volume, now))

    def get_price_history(self, coin: str, limit: int = 100) -> list[dict]:
        with self._cursor() as c:
            c.execute('''SELECT * FROM price_history WHERE coin=?
                ORDER BY created_at DESC LIMIT ?''', (coin, limit))
            return [dict(row) for row in c.fetchall()]

    # ═══════════════ BACKTEST OPERATIONS ═══════════════

    def save_backtest_result(self, result: dict):
        with self._cursor() as c:
            c.execute('''INSERT INTO backtest_results
                (signal_id, coin, action, entry_price, verify_price,
                 price_change_pct, correct, source_scores, created_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (result.get('signal_id'), result.get('coin'), result.get('action'),
                 result.get('entry_price'), result.get('verify_price'),
                 result.get('price_change_pct'), 1 if result.get('correct') else 0,
                 json.dumps(result.get('source_scores', {})),
                 result.get('created_at', datetime.now(timezone.utc).isoformat()),
                 result.get('verified_at')))

    def get_backtest_accuracy(self) -> dict:
        with self._cursor() as c:
            c.execute('SELECT COUNT(*) as total, SUM(correct) as correct FROM backtest_results')
            row = c.fetchone()
            total = row['total'] or 0
            correct = row['correct'] or 0
            return {
                'total': total,
                'correct': correct,
                'accuracy': round(correct / total * 100, 1) if total > 0 else 0,
            }

    # ═══════════════ PORTFOLIO OPERATIONS ═══════════════

    def save_portfolio_snapshot(self, snapshot: dict):
        with self._cursor() as c:
            c.execute('''INSERT INTO portfolio_snapshots
                (total_trades, total_invested, total_pnl, win_rate,
                 open_positions, snapshot, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (snapshot.get('total_trades', 0),
                 snapshot.get('total_invested', 0),
                 snapshot.get('total_pnl', 0),
                 snapshot.get('win_rate', 0),
                 snapshot.get('open_positions', 0),
                 json.dumps(snapshot, ensure_ascii=False, default=str),
                 datetime.now(timezone.utc).isoformat()))

    def get_portfolio_history(self, limit: int = 100) -> list[dict]:
        with self._cursor() as c:
            c.execute('SELECT * FROM portfolio_snapshots ORDER BY created_at DESC LIMIT ?',
                     (limit,))
            return [dict(row) for row in c.fetchall()]

    # ═══════════════ STATS ═══════════════

    def save_agent_stats(self, agent_name: str, cycles: int, errors: int, snapshot: dict = None):
        with self._cursor() as c:
            c.execute('''INSERT INTO agent_stats
                (agent_name, cycles, errors, snapshot, created_at)
                VALUES (?, ?, ?, ?, ?)''',
                (agent_name, cycles, errors,
                 json.dumps(snapshot, ensure_ascii=False, default=str) if snapshot else None,
                 datetime.now(timezone.utc).isoformat()))

    def get_dashboard_summary(self) -> dict:
        """Dashboard için özet veri"""
        with self._cursor() as c:
            # Son trade'ler
            c.execute('SELECT COUNT(*) as cnt FROM trades')
            total_trades = c.fetchone()['cnt']

            c.execute('SELECT COUNT(*) as cnt FROM trades WHERE closed_at IS NULL')
            open_trades = c.fetchone()['cnt']

            c.execute('SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE pnl != 0')
            total_pnl = c.fetchone()['total']

            c.execute('SELECT COUNT(*) as cnt FROM trades WHERE pnl > 0')
            wins = c.fetchone()['cnt']

            c.execute('SELECT COUNT(*) as cnt FROM trades WHERE pnl < 0')
            losses = c.fetchone()['cnt']

            # Son sinyaller
            c.execute('SELECT COUNT(*) as cnt FROM signals')
            total_signals = c.fetchone()['cnt']

            # Backtest doğruluğu
            accuracy = self.get_backtest_accuracy()

            return {
                'total_trades': total_trades,
                'open_trades': open_trades,
                'total_pnl': round(total_pnl, 2),
                'wins': wins,
                'losses': losses,
                'win_rate': round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
                'total_signals': total_signals,
                'backtest_accuracy': accuracy['accuracy'],
            }


# Global singleton
_db_instance = None


def get_database() -> TradingDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = TradingDatabase()
    return _db_instance
