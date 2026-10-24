"""기준봉(단기) 스캐너 - GitHub Actions용

규칙
1. 60일선이 120일선 아래로 내려간 첫 날 = 역배열 시작일 (1일째)
2. 시작일부터 60일(달력일) 동안, 역배열이 유지되는 구간에서
3. 그 봉이 양봉(종가 > 시가)이고, 종가가 직전 60거래일(자기 포함) 모든 봉(음봉 포함)의 종가보다 높으면 기준봉 (크기·거래량은 안 봄)
4. 한 역배열 구간에서는 처음 뜬 기준봉이 고정. 오늘 봉이 그 첫 기준봉이면 신호

실행하면
- docs/data/latest.json   오늘 신호
- docs/data/history.json  지난 신호 기록
- docs/data/charts/*.json 종목별 차트 데이터
를 갱신하고, 새 신호는 텔레그램으로 알려준다.

환경변수
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  텔레그램 알림 (없으면 알림만 건너뜀)
SITE_URL                              알림 메시지 끝에 붙일 사이트 주소
FORCE=1                               휴장일/장 마감 전에도 강제 실행
DRY_RUN=1                             텔레그램 전송과 기록 저장 없이 결과만 확인
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import FinanceDataReader as fdr

ROOT = os.environ.get('SCAN_ROOT') or os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, 'docs', 'data')
CHART_DIR = os.path.join(DATA_DIR, 'charts')
LATEST_JSON = os.path.join(DATA_DIR, 'latest.json')
HISTORY_JSON = os.path.join(DATA_DIR, 'history.json')
UNIVERSE_CSV = os.path.join(ROOT, 'data', 'universe.csv')
INDEX_JSON = os.path.join(DATA_DIR, 'index.json')
INDEX_SYMBOLS = {'KOSPI': 'KS11', 'KOSDAQ': 'KQ11'}   # 사이트에서 같이 보여줄 지수
INDEX_BARS = 330

KST = ZoneInfo('Asia/Seoul')
MA_SHORT, MA_LONG = 60, 120
WINDOW_DAYS = 60          # (사용 안 함) 예전 방식: 역배열 60일 제한. 지금은 정배열로 돌아설 때까지 무제한
HIGH_BARS = 60            # 기준봉 종가 비교 기간 (거래일 봉 수, 자기 포함)
LOOKBACK_DAYS = 800       # 달력일 기준 조회 기간
CHART_BARS = 170          # 사이트 차트에 쓸 봉 수
MIN_MARCAP = 50_000_000_000   # 시총 500억 이상
MIN_AMOUNT = 1_000_000_000    # 당일 거래대금 10억 이상
MAX_WORKERS = 8
MAX_ERROR_RATIO = 0.2     # 조회 실패가 이 비율을 넘으면 결과를 저장하지 않고 실패 처리


# --------------------------------------------------------------------------- 판별 로직
def prepare(df):
    df = df.dropna(subset=['Open', 'Close']).copy()
    df['ma60'] = df['Close'].rolling(MA_SHORT).mean()
    df['ma120'] = df['Close'].rolling(MA_LONG).mean()
    # 전날까지 60선 >= 120선, 오늘 60선 < 120선 -> 120선이 60선 위로 역전
    df['cross'] = (df['ma60'].shift(1) >= df['ma120'].shift(1)) & (df['ma60'] < df['ma120'])
    df['inv'] = df['ma60'] < df['ma120']
    # 기준봉 후보: 양봉이면서 종가가 직전 (HIGH_BARS-1)봉의 모든 종가(음봉 포함)보다 높은 봉
    bull = df['Close'] > df['Open']
    prev_max = df['Close'].shift(1).rolling(HIGH_BARS - 1, min_periods=1).max()
    df['cand'] = bull & (prev_max.isna() | (df['Close'] > prev_max))
    return df


def check_at(df, i, window_days=None):
    """i번째 봉이 '기준봉 신고(갱신)'이면 dict, 아니면 None"""
    crosses = np.flatnonzero(df['cross'].values[:i + 1])
    if len(crosses) == 0:
        return None
    c = int(crosses[-1])                                  # 가장 최근 역전일
    day_no = (df.index[i] - df.index[c]).days + 1         # 역전일이 1일째
    if window_days is not None and day_no > window_days:
        return None                                       # 60일 지남 -> 그 구간 기준봉은 확정
    if not df['inv'].values[c:i].all():
        return None                                       # 중간에 정배열로 돌아섰으면 구간 끝
    cand = df['cand'].values
    if not cand[i]:
        return None
    if cand[c:i].any():
        return None                                       # 이 구간에서 이미 기준봉이 떴으면 처음 것이 고정
    row = df.iloc[i]
    prev_close = float(df['Close'].iloc[i - 1])
    change = round((float(row['Close']) / prev_close - 1) * 100, 2) if prev_close else 0.0
    cross_date = df.index[c].date()
    return {
        'signal_date': df.index[i].date().isoformat(),
        'cross_date': cross_date.isoformat(),
        'window_end': '',                                  # 기간 제한 없음: 정배열로 돌아서기 전까지 유효(빈 값=진행 중)
        'day_no': int(day_no),
        'bar_no': int(i - c + 1),
        'close': float(row['Close']),
        'change_pct': change,
        'volume': int(row['Volume']),
    }


def make_chart(df):
    tail = df.iloc[-CHART_BARS:]

    def col(name, nd=2):
        return [None if pd.isna(x) else round(float(x), nd) for x in tail[name]]

    return {
        't': [d.date().isoformat() for d in tail.index],
        'o': col('Open'), 'h': col('High'), 'l': col('Low'), 'c': col('Close'),
        'v': [int(x) if not pd.isna(x) else 0 for x in tail['Volume']],
        'ma60': col('ma60'), 'ma120': col('ma120'),
    }


# --------------------------------------------------------------------------- 데이터
def reference_date():
    """삼성전자 최신 봉 날짜 = 가장 최근 거래일"""
    start = (datetime.now(KST) - timedelta(days=14)).strftime('%Y-%m-%d')
    df = fdr.DataReader('005930', start)
    return df.index[-1].date()


def get_universe(apply_amount=True):
    try:
        lst = fdr.StockListing('KRX')
        code_col = 'Code' if 'Code' in lst.columns else 'Symbol'
        lst = lst.rename(columns={code_col: 'Code'})
        lst = lst[lst['Market'].astype(str).str.startswith('KOS')]                       # KOSPI, KOSDAQ
        lst = lst[~lst['Name'].str.contains(r'스팩|제\d+호|ETN|ETF', regex=True, na=False)]
        lst = lst[~lst['Name'].str.contains(r'우$|우B$|우\(전환\)$', regex=True, na=False)]  # 우선주
        if 'Dept' in lst.columns:
            lst = lst[~lst['Dept'].astype(str).str.contains('관리|SPAC', na=False)]
        if 'Marcap' in lst.columns:
            lst = lst[lst['Marcap'] >= MIN_MARCAP]
        if apply_amount and 'Amount' in lst.columns:
            lst = lst[lst['Amount'] >= MIN_AMOUNT]
        uni = lst[['Code', 'Name', 'Market']].reset_index(drop=True)
        os.makedirs(os.path.dirname(UNIVERSE_CSV), exist_ok=True)
        if apply_amount:
            uni.to_csv(UNIVERSE_CSV, index=False)             # 다음 번 조회 실패 대비 캐시
        return uni
    except Exception as e:                                # noqa: BLE001
        print(f'KRX 종목 목록 조회 실패: {e!r}')
        if os.path.exists(UNIVERSE_CSV):
            print('-> 저장해 둔 data/universe.csv 를 대신 사용합니다')
            return pd.read_csv(UNIVERSE_CSV, dtype={'Code': str})
        raise


def scan_one(code, start, asof):
    """('signal', (sig, chart)) / ('none', None) / ('error', 메시지)"""
    last_err = None
    for attempt in range(3):
        try:
            raw = fdr.DataReader(code, start)
            if raw is None or raw.empty:
                return 'none', None
            if raw.index[-1].date() != asof:               # 오늘 봉이 없는 종목(거래정지 등)
                return 'none', None
            if raw['Volume'].iloc[-1] == 0:
                return 'none', None
            df = prepare(raw)
            if len(df) < MA_LONG + 2:
                return 'none', None
            sig = check_at(df, len(df) - 1)
            if not sig:
                return 'none', None
            return 'signal', (sig, make_chart(df))
        except Exception as e:                            # noqa: BLE001
            last_err = repr(e)
            time.sleep(0.7 * (attempt + 1))
    return 'error', last_err


def scan_all(uni, asof):
    start = (datetime.now(KST) - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    found, errors, first_error = [], 0, None
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(scan_one, str(r.Code).zfill(6), start, asof): r for r in uni.itertuples()}
        for n, f in enumerate(as_completed(futs), start=1):
            r = futs[f]
            status, payload = f.result()
            if status == 'signal':
                sig, chart = payload
                code = str(r.Code).zfill(6)
                sig.update({'code': code, 'name': r.Name, 'market': r.Market})
                chart.update({'code': code, 'name': r.Name, 'signal_date': sig['signal_date'],
                              'cross_date': sig['cross_date'], 'window_end': sig['window_end']})
                found.append((sig, chart))
            elif status == 'error':
                errors += 1
                first_error = first_error or payload
            if n % 100 == 0:
                print(f'  {n}/{len(futs)} 확인 중...')
    return found, errors, first_error


# --------------------------------------------------------------------------- 저장 / 알림
def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, allow_nan=False)


def prune_superseded(history):
    """같은 역배열 구간(code + cross_date)에는 가장 늦은 신호 하나만 남긴다.
    -> (남은 기록, 정리된 기록). 구간이 같으면 기준봉은 하나라서, 앞선 신호는 새 신호에 밀려난다."""
    best = {}
    for h in history:
        k = (h['code'], h['cross_date'])
        if k not in best or h['signal_date'] > best[k]['signal_date']:
            best[k] = h
    keep = {id(v) for v in best.values()}
    kept = [h for h in history if id(h) in keep]
    dropped = [h for h in history if id(h) not in keep]
    return kept, dropped


def remove_charts(entries):
    for h in entries:
        name = h.get('chart')
        if name:
            path = os.path.join(DATA_DIR, name)
            if os.path.isfile(path):
                os.remove(path)


def send_telegram(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print('텔레그램 설정(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)이 없어 알림은 건너뜁니다')
        return False
    try:
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                          json={'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True},
                          timeout=20)
        if r.status_code != 200:
            print(f'텔레그램 전송 실패: {r.status_code} {r.text[:200]}')
            return False
        return True
    except requests.RequestException as e:
        print(f'텔레그램 전송 실패: {e!r}')
        return False


def build_messages(signals, asof):
    site = os.environ.get('SITE_URL', '')
    msgs = []
    for k in range(0, len(signals), 20):
        part = signals[k:k + 20]
        lines = [f'기준봉 포착 {len(signals)}종목 ({asof})', '']
        for s in part:
            lines.append(f"{s['name']} ({s['code']}) {s['market']}")
            lines.append(f"  종가 {s['close']:,.0f}원 ({s['change_pct']:+.1f}%) / 거래량 {s['volume']:,}")
            lines.append(f"  역배열 {s['cross_date']} 시작, {s['day_no']}일째 (정배열 전까지 유효)")
        if site and k + 20 >= len(signals):
            lines += ['', site]
        msgs.append('\n'.join(lines))
    return msgs


# --------------------------------------------------------------------------- 지수 (코스피/코스닥)
def save_index_data():
    """코스피/코스닥 지수 일봉을 docs/data/index.json 에 저장하고 돌려줍니다.
    하나가 실패해도 스캔은 계속하고, 실패한 지수는 예전에 저장한 값을 그대로 둡니다."""
    out = load_json(INDEX_JSON, {})
    start = (datetime.now(KST) - timedelta(days=560)).strftime('%Y-%m-%d')
    for name, sym in INDEX_SYMBOLS.items():
        try:
            df = fdr.DataReader(sym, start)
            df = df.dropna(subset=['High', 'Low', 'Close'])
            df = df[df['Close'] > 0].tail(INDEX_BARS).copy()
            if len(df) < 60:
                raise RuntimeError(f'지수 봉이 {len(df)}개뿐')
            if 'Open' not in df.columns:
                df['Open'] = df['Close'].shift(1)
            df['Open'] = df['Open'].where(df['Open'] > 0, df['Close'].shift(1)).fillna(df['Close'])
            out[name] = {'t': [d.date().isoformat() for d in df.index],
                         'o': [round(float(x), 2) for x in df['Open']], 'h': [round(float(x), 2) for x in df['High']],
                         'l': [round(float(x), 2) for x in df['Low']], 'c': [round(float(x), 2) for x in df['Close']]}
        except Exception as e:                              # noqa: BLE001
            print(f'{name} 지수 조회 실패(예전 값 유지): {e!r}')
    if out:
        save_json(INDEX_JSON, out)
    return out


def judge_vs_index(stock, idx, date):
    """기준봉 날 지수와 비교: 종목은 양봉으로 전날 고점을 넘었는데 지수는 못 넘으면 '강함'.
    둘 다 넘으면 '보통', 종목이 전날 고점을 못 넘으면 '약함'. 날짜가 없으면 None"""
    try:
        i, j = stock['t'].index(date), idx['t'].index(date)
    except ValueError:
        return None
    if i < 1 or j < 1:
        return None
    s_break = stock['c'][i] > stock['o'][i] and stock['h'][i] > stock['h'][i - 1]
    i_break = idx['h'][j] > idx['h'][j - 1]
    verdict = '약함' if not s_break else ('보통' if i_break else '강함')
    return {'v': verdict, 'idx_pct': round((idx['c'][j] / idx['c'][j - 1] - 1) * 100, 2)}


def annotate_vs_index(history, index_data):
    """기록에 '지수 대비' 판정을 붙입니다 (이미 붙은 건 건너뜀)"""
    done = 0
    for h in history:
        if h.get('vs') or not index_data:
            continue
        chart = load_json(os.path.join(DATA_DIR, h.get('chart', '')), None) if h.get('chart') else None
        if not chart:
            continue
        vs = {}
        for name, idx in index_data.items():
            r = judge_vs_index(chart, idx, h['signal_date'])
            if r:
                vs[name] = r
        if vs:
            h['vs'] = vs
            done += 1
    return done


# --------------------------------------------------------------------------- main
def main():
    now = datetime.now(KST)
    force = os.environ.get('FORCE') == '1'
    dry = os.environ.get('DRY_RUN') == '1'

    asof = reference_date()
    if not force:
        if asof != now.date():
            print(f'오늘({now.date()})은 휴장이거나 아직 데이터가 없어요 (최근 거래일 {asof}). 종료합니다.')
            return 0
        if now.hour < 16:
            print('장 마감 후 데이터가 확정되기 전(16시 이전)이라 종료합니다.')
            return 0

    uni = get_universe()
    print(f'기준일 {asof} / 스캔 대상 {len(uni)}종목')
    found, errors, first_error = scan_all(uni, asof)
    print(f'신호 {len(found)}종목, 조회 실패 {errors}종목')
    if len(uni) and errors / len(uni) > MAX_ERROR_RATIO:
        print(f'조회 실패가 너무 많아 결과를 저장하지 않습니다. 첫 에러: {first_error}')
        return 1

    found.sort(key=lambda x: x[0]['change_pct'], reverse=True)
    signals = []
    for sig, chart in found:
        fname = f"charts/{sig['code']}_{sig['signal_date']}.json"
        save_json(os.path.join(DATA_DIR, fname), chart)
        signals.append({**sig, 'chart': fname})

    save_json(LATEST_JSON, {
        'updated_at': now.isoformat(timespec='seconds'),
        'asof': asof.isoformat(),
        'universe_size': int(len(uni)),
        'signals': signals,
    }, indent=1)

    index_data = save_index_data()
    if dry:
        print('DRY_RUN: 기록 저장과 알림은 건너뜁니다')
        return 0

    # 기록 갱신 (같은 종목+날짜는 한 번만)
    history = load_json(HISTORY_JSON, [])
    known = {(h['code'], h['signal_date']) for h in history}
    for s in signals:
        if (s['code'], s['signal_date']) not in known:
            history.append({**s, 'notified': False})

    history, dropped = prune_superseded(history)       # 같은 구간의 앞선 신호는 새 신호에 밀려남
    remove_charts(dropped)
    print(f'지수 대비 판정 {annotate_vs_index(history, index_data)}건 추가')

    # 오늘 신호 중 아직 알리지 않은 것만 알림 (실패하면 다음 실행 때 다시 시도)
    pending = [h for h in history if not h.get('notified') and h['signal_date'] == asof.isoformat()]
    exit_code = 0
    if pending:
        ok = all(send_telegram(m) for m in build_messages(pending, asof.isoformat()))
        if ok:
            for h in pending:
                h['notified'] = True
            print(f'텔레그램 알림 {len(pending)}종목 전송')
        elif os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'):
            exit_code = 1          # 설정은 있는데 전송이 실패한 경우만 실패로 표시

    history.sort(key=lambda h: (h['signal_date'], h['change_pct']), reverse=True)
    save_json(HISTORY_JSON, history[:50000], indent=1)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
