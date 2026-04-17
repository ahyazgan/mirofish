"""
Paper trading performans analizi.

backend/data/trading.db içinden son N gün trade verilerini okur, win rate,
profit factor, max drawdown gibi kritik metrikleri hesaplar. Opsiyonel
olarak haber kaynağı kırılımı üretir (signals.sources üzerinden).

Kullanım:
    python scripts/analyze_performance.py
    python scripts/analyze_performance.py --days 14
    python scripts/analyze_performance.py --source-breakdown
    python scripts/analyze_performance.py --days 30 --source-breakdown
"""

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / 'data' / 'trading.db'


def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(f'--db ile verilen yol bulunamadi: {p}')
    if DEFAULT_DB.exists():
        return DEFAULT_DB
    # Tarihi / alternatif konumlar
    for cand in (
        BACKEND_DIR / 'app' / 'services' / 'crypto_trading' / 'trading.db',
        BACKEND_DIR / 'trading.db',
    ):
        if cand.exists():
            return cand
    raise FileNotFoundError(
        f'trading.db bulunamadi. Beklenen: {DEFAULT_DB}. '
        f'Bot henuz hic calismamis olabilir.'
    )


def compute_max_drawdown(pnls: list[float]) -> float:
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    return max_dd


def fmt_money(x: float) -> str:
    return f'${x:+.2f}'


def print_header(title: str):
    print()
    print('=' * 62)
    print(f'  {title}')
    print('=' * 62)


def analyze(days: int, source_breakdown: bool, db_path: Path):
    print(f'Database       : {db_path}')
    print(f'Analiz periyodu: Son {days} gün (UTC)')
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Kapanmış trade'ler (pnl hesaplanmış)
    c.execute(
        '''SELECT t.*, s.sources AS signal_sources, s.sentiment_score AS sig_score,
                  s.strength AS sig_strength, s.action AS sig_action
           FROM trades t LEFT JOIN signals s ON t.signal_id = s.id
           WHERE t.created_at >= ?
           ORDER BY t.created_at''',
        (since,),
    )
    all_trades = [dict(r) for r in c.fetchall()]
    closed = [t for t in all_trades if t.get('closed_at')]
    open_ = [t for t in all_trades if not t.get('closed_at')]

    if not all_trades:
        print(f'\nSon {days} günde hic trade yok — bot daha yeni veya hic sinyal ureememis.')
        # Yine de sinyal özeti ver
        c.execute('SELECT COUNT(*) AS n FROM signals WHERE created_at >= ?', (since,))
        sig_count = c.fetchone()['n']
        print(f'Kayitli sinyal sayisi    : {sig_count}')
        conn.close()
        return

    print_header(f'GENEL ({len(all_trades)} trade | kapali: {len(closed)} | acik: {len(open_)})')

    pnls = [float(t['pnl']) for t in closed if t.get('pnl') is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    if not pnls:
        print('Henuz kapanmis trade yok — PnL hesaplanamaz.')
        print(f'Acik pozisyonlar: {len(open_)}')
        conn.close()
        return

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    profit_factor = abs(sum(wins) / sum(losses)) if losses else float('inf')
    rr = abs(avg_win / avg_loss) if avg_loss else float('inf')
    max_dd = compute_max_drawdown(pnls)

    print(f'Toplam PnL       : {fmt_money(total_pnl)}')
    print(f'Win rate         : {win_rate:5.1f}%  ({len(wins)}W / {len(losses)}L)')
    print(f'Ort kazanc       : {fmt_money(avg_win)}')
    print(f'Ort kayip        : {fmt_money(avg_loss)}')
    print(f'Risk/Reward      : {rr:.2f}')
    print(f'Profit factor    : {profit_factor:.2f}')
    print(f'Max drawdown     : ${max_dd:.2f}')

    print_header('DEGERLENDIRME')
    if win_rate >= 55 and profit_factor >= 1.5:
        print('[OK] Strateji potansiyel olarak karli.')
        print('     Kucuk gercek parayla test edilebilir (sonra).')
    elif win_rate >= 45 and profit_factor >= 1.2:
        print('[!] Strateji sinirda. Tuning gerekli.')
        print('    Filtreleri sikilastir, sinyal kalitesini artir.')
    else:
        print('[X] Strateji henuz hazir degil.')
        print('    Canli para kullanma. Stratejiyi revize et.')

    # Close-reason kırılımı
    reasons: dict[str, list[float]] = defaultdict(list)
    for t in closed:
        if t.get('pnl') is not None:
            reasons[t.get('close_reason') or 'unknown'].append(float(t['pnl']))
    if reasons:
        print_header('KAPANIS NEDENI')
        print(f"{'Neden':<20} {'Sayi':>6} {'Win%':>7} {'Top PnL':>12}")
        print('-' * 62)
        for reason, ps in sorted(reasons.items(), key=lambda x: -sum(x[1])):
            w = sum(1 for p in ps if p > 0)
            wr = w / len(ps) * 100 if ps else 0
            print(f'{reason:<20} {len(ps):>6} {wr:>6.1f}% {sum(ps):>+12.2f}')

    # Coin breakdown
    by_coin: dict[str, list[float]] = defaultdict(list)
    for t in closed:
        if t.get('pnl') is not None:
            by_coin[t.get('coin') or 'UNKNOWN'].append(float(t['pnl']))
    if by_coin:
        print_header('COIN KIRILIMI')
        print(f"{'Coin':<10} {'Sayi':>6} {'Win%':>7} {'Top PnL':>12}")
        print('-' * 62)
        for coin, ps in sorted(by_coin.items(), key=lambda x: -sum(x[1])):
            w = sum(1 for p in ps if p > 0)
            wr = w / len(ps) * 100 if ps else 0
            print(f'{coin:<10} {len(ps):>6} {wr:>6.1f}% {sum(ps):>+12.2f}')

    # Haber kaynağı kırılımı — signals.sources üzerinden (JSON veya CSV olabilir)
    if source_breakdown:
        print_header('HABER KAYNAGI PERFORMANSI (sinyale gore)')
        by_source: dict[str, list[float]] = defaultdict(list)
        for t in closed:
            if t.get('pnl') is None:
                continue
            raw = t.get('signal_sources') or ''
            sources = _parse_sources(raw)
            if not sources:
                sources = ['(bilinmiyor)']
            # Her kaynak bu trade'in PnL'ini "paylasir" — basit katkı atfı
            share = float(t['pnl']) / len(sources)
            for src in sources:
                by_source[src].append(share)

        if not by_source:
            print('Kaynak verisi yok (signals.sources bos).')
        else:
            print(f"{'Kaynak':<34} {'Sayi':>5} {'Win%':>7} {'Top PnL':>12}")
            print('-' * 62)
            for src, ps in sorted(by_source.items(), key=lambda x: -sum(x[1])):
                w = sum(1 for p in ps if p > 0)
                wr = w / len(ps) * 100 if ps else 0
                print(f'{src:<34} {len(ps):>5} {wr:>6.1f}% {sum(ps):>+12.2f}')

    conn.close()


def _parse_sources(raw: str) -> list[str]:
    """signals.sources hem JSON list hem virgullu string olabilir."""
    if not raw:
        return []
    s = raw.strip()
    if s.startswith('['):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x) for x in data if x]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in s.split(',') if p.strip()]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MiroFish paper trading analizi')
    parser.add_argument('--days', type=int, default=7, help='Analiz periyodu (gun)')
    parser.add_argument('--source-breakdown', action='store_true', help='Haber kaynagi kirilimi')
    parser.add_argument('--db', type=str, default=None, help='Alternatif DB yolu')
    args = parser.parse_args()

    try:
        db = resolve_db_path(args.db)
    except FileNotFoundError as e:
        print(f'HATA: {e}')
        raise SystemExit(1)

    analyze(days=args.days, source_breakdown=args.source_breakdown, db_path=db)
