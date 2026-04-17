"""
Trading Dashboard - Gerçek zamanlı web paneli
Flask-SocketIO ile canlı güncelleme.
"""

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template_string, request, abort
from flask_socketio import SocketIO

from .database import get_database

# Dashboard authentication token (env'den oku, yoksa None = auth yok)
DASHBOARD_TOKEN = os.environ.get('DASHBOARD_TOKEN', '')

logger = logging.getLogger('crypto_trading.dashboard')

# Dashboard HTML
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MiroFish Trading Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0a0e17;
            color: #e1e5eb;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%);
            padding: 20px 30px;
            border-bottom: 1px solid #1e2a3a;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 22px;
            background: linear-gradient(90deg, #00d4ff, #7b61ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header .status {
            display: flex; gap: 15px; align-items: center;
        }
        .status-dot {
            width: 10px; height: 10px; border-radius: 50%;
            display: inline-block; margin-right: 5px;
        }
        .status-dot.active { background: #00ff88; box-shadow: 0 0 8px #00ff88; }
        .status-dot.inactive { background: #ff4444; }
        .grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            padding: 20px 30px;
        }
        .card {
            background: #111827;
            border: 1px solid #1e2a3a;
            border-radius: 12px;
            padding: 20px;
        }
        .card h3 {
            font-size: 12px;
            text-transform: uppercase;
            color: #6b7280;
            margin-bottom: 8px;
            letter-spacing: 1px;
        }
        .card .value {
            font-size: 28px;
            font-weight: 700;
        }
        .card .sub { font-size: 12px; color: #6b7280; margin-top: 4px; }
        .green { color: #00ff88; }
        .red { color: #ff4444; }
        .blue { color: #00d4ff; }
        .yellow { color: #ffd700; }
        .purple { color: #7b61ff; }

        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 15px;
            padding: 0 30px 20px;
        }
        .panel {
            background: #111827;
            border: 1px solid #1e2a3a;
            border-radius: 12px;
            padding: 20px;
        }
        .panel h2 {
            font-size: 16px;
            margin-bottom: 15px;
            color: #00d4ff;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: left;
            font-size: 11px;
            text-transform: uppercase;
            color: #6b7280;
            padding: 8px 10px;
            border-bottom: 1px solid #1e2a3a;
        }
        td {
            padding: 10px;
            font-size: 13px;
            border-bottom: 1px solid #0d1117;
        }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-buy { background: rgba(0,255,136,0.15); color: #00ff88; }
        .badge-sell { background: rgba(255,68,68,0.15); color: #ff4444; }
        .badge-strong { background: rgba(0,212,255,0.15); color: #00d4ff; }
        .badge-moderate { background: rgba(255,215,0,0.15); color: #ffd700; }

        .agent-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
        }
        .agent-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 12px;
            background: #0d1117;
            border-radius: 6px;
            font-size: 12px;
        }
        .agent-item .name { color: #9ca3af; }
        .agent-item .cycles { color: #00d4ff; }

        .event-list { max-height: 400px; overflow-y: auto; }
        .event-item {
            padding: 8px 12px;
            border-left: 3px solid #1e2a3a;
            margin-bottom: 6px;
            font-size: 12px;
            background: #0d1117;
            border-radius: 0 6px 6px 0;
        }
        .event-item.signal { border-left-color: #00d4ff; }
        .event-item.trade { border-left-color: #00ff88; }
        .event-item.risk { border-left-color: #ff4444; }
        .event-item.info { border-left-color: #6b7280; }
        .event-time { color: #6b7280; font-size: 10px; }

        .risk-bar {
            width: 100%; height: 8px;
            background: #1e2a3a; border-radius: 4px;
            margin-top: 8px; overflow: hidden;
        }
        .risk-bar-fill {
            height: 100%; border-radius: 4px;
            transition: width 0.5s ease;
        }

        @media (max-width: 1200px) {
            .grid { grid-template-columns: repeat(2, 1fr); }
            .main-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>MiroFish Trading Dashboard</h1>
        <div class="status">
            <span><span class="status-dot" id="ws-status"></span> <span id="ws-text">Bağlanıyor...</span></span>
            <span style="color:#6b7280" id="clock"></span>
        </div>
    </div>

    <!-- KPI Cards -->
    <div class="grid">
        <div class="card">
            <h3>Toplam Trade</h3>
            <div class="value blue" id="total-trades">0</div>
            <div class="sub">Açık: <span id="open-trades">0</span></div>
        </div>
        <div class="card">
            <h3>Toplam P&L</h3>
            <div class="value" id="total-pnl">$0.00</div>
            <div class="sub">Win Rate: <span id="win-rate">0%</span></div>
        </div>
        <div class="card">
            <h3>Aktif Sinyal</h3>
            <div class="value purple" id="total-signals">0</div>
            <div class="sub">Backtest: <span id="backtest-accuracy">N/A</span></div>
        </div>
        <div class="card">
            <h3>Risk Durumu</h3>
            <div class="value" id="risk-status">Normal</div>
            <div class="risk-bar"><div class="risk-bar-fill" id="risk-bar" style="width:0%;background:#00ff88;"></div></div>
            <div class="sub">Günlük kayıp: <span id="daily-loss">$0</span> / $200</div>
        </div>
    </div>

    <!-- Main Content -->
    <div class="main-grid">
        <!-- Sol Panel: Sinyaller & Trade'ler -->
        <div>
            <div class="panel" style="margin-bottom:15px">
                <h2>Son Sinyaller</h2>
                <table>
                    <thead>
                        <tr><th>Coin</th><th>Yön</th><th>Güç</th><th>Skor</th><th>Fiyat</th><th>Kaynaklar</th></tr>
                    </thead>
                    <tbody id="signals-table"></tbody>
                </table>
            </div>
            <div class="panel">
                <h2>Son Trade'ler</h2>
                <table>
                    <thead>
                        <tr><th>Coin</th><th>Yön</th><th>Miktar</th><th>Fiyat</th><th>P&L</th><th>Durum</th></tr>
                    </thead>
                    <tbody id="trades-table"></tbody>
                </table>
            </div>
        </div>

        <!-- Sag Panel: Ajanlar & Events -->
        <div>
            <div class="panel" style="margin-bottom:15px">
                <h2>Ajanlar (<span id="agent-count">0</span>)</h2>
                <div class="agent-grid" id="agents-grid"></div>
            </div>
            <div class="panel">
                <h2>Canlı Olaylar</h2>
                <div class="event-list" id="events-list"></div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        const maxEvents = 50;

        socket.on('connect', () => {
            document.getElementById('ws-status').className = 'status-dot active';
            document.getElementById('ws-text').textContent = 'Bağlı';
        });
        socket.on('disconnect', () => {
            document.getElementById('ws-status').className = 'status-dot inactive';
            document.getElementById('ws-text').textContent = 'Bağlantı kesildi';
        });

        // Dashboard güncellemesi
        socket.on('dashboard_update', (data) => {
            // KPI
            document.getElementById('total-trades').textContent = data.total_trades || 0;
            document.getElementById('open-trades').textContent = data.open_trades || 0;

            const pnl = data.total_pnl || 0;
            const pnlEl = document.getElementById('total-pnl');
            pnlEl.textContent = '$' + pnl.toFixed(2);
            pnlEl.className = 'value ' + (pnl >= 0 ? 'green' : 'red');

            document.getElementById('win-rate').textContent = (data.win_rate || 0) + '%';
            document.getElementById('total-signals').textContent = data.total_signals || 0;
            document.getElementById('backtest-accuracy').textContent = (data.backtest_accuracy || 'N/A') + '%';

            // Risk
            const dailyLoss = data.daily_loss || 0;
            const maxLoss = data.max_daily_loss || 200;
            const riskPct = Math.min(100, (dailyLoss / maxLoss) * 100);
            document.getElementById('daily-loss').textContent = '$' + dailyLoss.toFixed(0);
            const riskBar = document.getElementById('risk-bar');
            riskBar.style.width = riskPct + '%';
            riskBar.style.background = riskPct > 80 ? '#ff4444' : riskPct > 50 ? '#ffd700' : '#00ff88';

            const riskStatus = document.getElementById('risk-status');
            if (data.risk_locked) {
                riskStatus.textContent = 'KİLİTLİ';
                riskStatus.className = 'value red';
            } else if (riskPct > 50) {
                riskStatus.textContent = 'Dikkat';
                riskStatus.className = 'value yellow';
            } else {
                riskStatus.textContent = 'Normal';
                riskStatus.className = 'value green';
            }
        });

        // Sinyaller
        socket.on('signals_update', (signals) => {
            const tbody = document.getElementById('signals-table');
            tbody.innerHTML = '';
            (signals || []).slice(0, 10).forEach(s => {
                const actionClass = s.action === 'BUY' ? 'badge-buy' : 'badge-sell';
                const strengthClass = s.strength === 'STRONG' ? 'badge-strong' : 'badge-moderate';
                tbody.innerHTML += `<tr>
                    <td><strong>${s.coin}</strong></td>
                    <td><span class="badge ${actionClass}">${s.action}</span></td>
                    <td><span class="badge ${strengthClass}">${s.strength}</span></td>
                    <td>${(s.sentiment_score || 0).toFixed(3)}</td>
                    <td>$${(s.entry_price || 0).toFixed(2)}</td>
                    <td style="font-size:10px;color:#6b7280">${s.sources || ''}</td>
                </tr>`;
            });
        });

        // Trade'ler
        socket.on('trades_update', (trades) => {
            const tbody = document.getElementById('trades-table');
            tbody.innerHTML = '';
            (trades || []).slice(0, 10).forEach(t => {
                const sideClass = t.side === 'BUY' ? 'badge-buy' : 'badge-sell';
                const pnl = t.pnl || 0;
                const pnlClass = pnl >= 0 ? 'green' : 'red';
                tbody.innerHTML += `<tr>
                    <td><strong>${t.coin}</strong></td>
                    <td><span class="badge ${sideClass}">${t.side}</span></td>
                    <td>${t.quantity || 0}</td>
                    <td>$${(t.price || 0).toFixed(2)}</td>
                    <td class="${pnlClass}">${pnl > 0 ? '+' : ''}${pnl.toFixed(2)}%</td>
                    <td style="font-size:11px">${t.status}</td>
                </tr>`;
            });
        });

        // Ajanlar
        socket.on('agents_update', (agents) => {
            const grid = document.getElementById('agents-grid');
            document.getElementById('agent-count').textContent = Object.keys(agents || {}).length;
            grid.innerHTML = '';
            Object.entries(agents || {}).forEach(([name, stats]) => {
                const running = stats.running ? '🟢' : '🔴';
                grid.innerHTML += `<div class="agent-item">
                    <span class="name">${running} ${name}</span>
                    <span class="cycles">${stats.cycles || 0} döngü</span>
                </div>`;
            });
        });

        // Canlı olaylar
        socket.on('new_event', (event) => {
            const list = document.getElementById('events-list');
            const typeMap = {
                'signal_generated': 'signal',
                'trade_executed': 'trade',
                'position_closed': 'risk',
                'risk_locked': 'risk',
                'risk_rejected': 'risk',
            };
            const cls = typeMap[event.type] || 'info';
            const time = event.time ? event.time.split('T')[1]?.split('.')[0] || '' : '';

            const div = document.createElement('div');
            div.className = 'event-item ' + cls;
            div.innerHTML = `<span class="event-time">${time}</span>
                <strong>[${event.from || ''}]</strong> ${event.type}
                ${event.coin ? ' - ' + event.coin : ''}
                ${event.action ? ' ' + event.action : ''}
                ${event.score ? ' score=' + event.score : ''}`;

            list.insertBefore(div, list.firstChild);
            while (list.children.length > maxEvents) list.removeChild(list.lastChild);
        });

        // Saat
        setInterval(() => {
            document.getElementById('clock').textContent = new Date().toLocaleTimeString('tr-TR');
        }, 1000);
    </script>
</body>
</html>
'''


def create_dashboard_app(orchestrator=None) -> tuple:
    """Dashboard Flask uygulaması oluştur"""
    app = Flask(__name__)
    # Secret key env'den; yoksa runtime'da kriptografik rastgele üret (sabit kodlamadan kaçın)
    secret_key = os.environ.get('DASHBOARD_SECRET_KEY') or secrets.token_hex(32)
    app.config['SECRET_KEY'] = secret_key
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    # Basit rate limit (IP bazlı): saniyede max N istek
    _rate_limit_window = float(os.environ.get('DASHBOARD_RATE_WINDOW', 1.0))
    _rate_limit_max = int(os.environ.get('DASHBOARD_RATE_MAX', 20))
    _rate_state: dict[str, list[float]] = {}
    _rate_lock = threading.Lock()

    def _check_rate_limit(ip: str) -> bool:
        now = time.time()
        with _rate_lock:
            bucket = _rate_state.setdefault(ip, [])
            # Pencere dışı istekleri at
            cutoff = now - _rate_limit_window
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= _rate_limit_max:
                return False
            bucket.append(now)
            return True

    def _check_auth():
        """Token auth kontrolü (DASHBOARD_TOKEN ayarlıysa)"""
        if DASHBOARD_TOKEN:
            token = request.args.get('token', '') or request.headers.get('X-Dashboard-Token', '')
            if token != DASHBOARD_TOKEN:
                abort(403)

    @app.before_request
    def before_request():
        ip = request.remote_addr or '?'
        if not _check_rate_limit(ip):
            abort(429)
        _check_auth()

    @app.route('/')
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route('/api/status')
    def api_status():
        if orchestrator:
            return json.dumps(orchestrator.get_status(), default=str)
        return json.dumps({'status': 'no orchestrator'})

    return app, socketio


class DashboardServer:
    """Dashboard sunucusu - ayrı thread'de çalışır"""

    def __init__(self, orchestrator=None, port: int = 5050):
        self.orchestrator = orchestrator
        self.port = port
        self.app, self.socketio = create_dashboard_app(orchestrator)
        self._thread = None
        self._running = False

    def start(self):
        """Dashboard'u arka plan thread'inde başlat"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        # Güncelleme thread'i
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()

        logger.info(f"Dashboard başlatıldı: http://localhost:{self.port}")

    def _run(self):
        self.socketio.run(self.app, host='127.0.0.1', port=self.port,
                         allow_unsafe_werkzeug=True, log_output=False)

    def _update_loop(self):
        """Periyodik olarak dashboard'a veri gönder.

        Tekrarlayan hata olursa exponential backoff uygular (log flood'u engeller).
        """
        time.sleep(3)  # Başlangıç bekleme
        consecutive_errors = 0
        base_interval = 3.0
        while self._running:
            try:
                if self.orchestrator:
                    status = self.orchestrator.get_status()

                    # KPI verileri
                    db_summary = status.get('db_summary', {})
                    risk = status.get('positions', {})
                    self.socketio.emit('dashboard_update', {
                        'total_trades': db_summary.get('total_trades', 0),
                        'open_trades': risk.get('open_positions', 0),
                        'total_pnl': db_summary.get('total_pnl', 0),
                        'win_rate': db_summary.get('win_rate', 0),
                        'total_signals': db_summary.get('total_signals', 0),
                        'backtest_accuracy': status.get('backtest', {}).get('accuracy', 0),
                        'daily_loss': risk.get('daily_loss', 0),
                        'max_daily_loss': risk.get('max_daily_loss', 200),
                        'risk_locked': risk.get('risk_locked', False),
                    })

                    # Sinyaller
                    self.socketio.emit('signals_update', status.get('signals', []))

                    # Trade'ler
                    orders = status.get('orders', [])
                    self.socketio.emit('trades_update', orders)

                    # Ajanlar
                    self.socketio.emit('agents_update', status.get('agents', {}))

                    # Son olaylar
                    events = status.get('recent_events', [])
                    for event in events[-5:]:
                        self.socketio.emit('new_event', event)

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                # Exponential backoff (max 60 sn)
                backoff = min(60.0, base_interval * (2 ** consecutive_errors))
                if consecutive_errors <= 3 or consecutive_errors % 10 == 0:
                    logger.error(
                        f"Dashboard güncelleme hatası (#{consecutive_errors}, "
                        f"{backoff:.0f}s backoff): {e}"
                    )
                time.sleep(backoff)
                continue

            time.sleep(base_interval)  # 3 saniyede bir güncelle

    def stop(self):
        """Dashboard'u kapat. Flask dev server için graceful shutdown yok — flag + join."""
        self._running = False
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=5.0)
        # socketio thread daemon olarak çalışıyor; process çıkışında otomatik kapanır
        logger.info("Dashboard durduruldu")
