"""과거 기준봉 이력 채우기 (필요할 때 한 번만 실행)

BACKFILL_FROM ~ BACKFILL_TO 사이에 신호가 난 봉을 찾아서 history.json 에 넣는다.
- 같은 역배열 구간(역전일이 같은 것)에서는 마지막 신호, 즉 그 기간의 최종 기준봉만 남긴다.
- 거래대금 조건은 따지지 않는다 (시총 500억 이상 종목만 대상).
- 종목 목록은 오늘 기준(시총 500억 이상, 스팩/ETF/우선주/관리종목 제외)이라
  그 사이 상장폐지된 종목은 빠진다.
- 이미 알림이 지나간 과거 기록이라 notified=True 로 저장한다 (텔레그램은 보내지 않음).
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import scan


def stock_history(code, start, d_from, d_to):
    """('ok', [(sig, chart), ...]) / ('none', []) / ('error', 메시지)"""
    last_err = None
    for attempt in range(3):
        try:
            raw = scan.fdr.DataReader(code, start)
            if raw is None or raw.empty:
                return 'none', []
            df = scan.prepare(raw)
            if len(df) < scan.MA_LONG + 2:
                return 'none', []
            fired = []
            for i in range(scan.MA_LONG + 1, len(df)):
                d = df.index[i].date()
                if d < d_from or d > d_to:
                    continue
                sig = scan.check_at(df, i)
                if not sig:
                    continue
                fired.append(sig)
            if not fired:
                return 'none', []
            final = {}
            for s in fired:                                    # 날짜순이라 같은 구간은 마지막 신호만 남음
                final[s['cross_date']] = s
            chart = scan.make_chart(df)                        # 최신 봉까지 포함해서 그 뒤 흐름도 보이게
            return 'ok', [(s, chart) for s in final.values()]
        except Exception as e:                                 # noqa: BLE001
            last_err = repr(e)
            time.sleep(0.7 * (attempt + 1))
    return 'error', last_err


def main():
    d_from = date.fromisoformat(os.environ.get('BACKFILL_FROM') or '2026-08-01')
    d_to = date.fromisoformat(os.environ.get('BACKFILL_TO') or '2026-10-21')
    print(f'채울 기간: {d_from} ~ {d_to}')

    uni = scan.get_universe(apply_amount=False)
    start = (datetime.now(scan.KST) - timedelta(days=scan.LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    print(f'스캔 대상 {len(uni)}종목')

    results, errors, first_error = [], 0, None
    with ThreadPoolExecutor(max_workers=scan.MAX_WORKERS) as ex:
        futs = {ex.submit(stock_history, str(r.Code).zfill(6), start, d_from, d_to): r for r in uni.itertuples()}
        for n, f in enumerate(as_completed(futs), start=1):
            r = futs[f]
            status, payload = f.result()
            code = str(r.Code).zfill(6)
            if status == 'ok':
                for sig, chart in payload:
                    sig = {**sig, 'code': code, 'name': r.Name, 'market': r.Market}
                    chart = {**chart, 'code': code, 'name': r.Name, 'signal_date': sig['signal_date'],
                             'cross_date': sig['cross_date'], 'window_end': sig['window_end']}
                    results.append((sig, chart))
            elif status == 'error':
                errors += 1
                first_error = first_error or payload
            if n % 200 == 0:
                print(f'  {n}/{len(futs)} 확인 중...')
    print(f'구간별 기준봉 {len(results)}건, 조회 실패 {errors}종목')
    if len(uni) and errors / len(uni) > scan.MAX_ERROR_RATIO:
        print(f'조회 실패가 너무 많아 저장하지 않습니다. 첫 에러: {first_error}')
        return 1

    history = scan.load_json(scan.HISTORY_JSON, [])
    # 이 기간의 기존 기록은 지우고 새 규칙으로 다시 채운다 (규칙이 바뀌었을 때 옛 결과가 남지 않게)
    old = [h for h in history if d_from.isoformat() <= h['signal_date'] <= d_to.isoformat()]
    history = [h for h in history if h not in old]
    scan.remove_charts(old)
    known = {(h['code'], h['signal_date']) for h in history}
    payloads = []
    for sig, chart in results:
        if (sig['code'], sig['signal_date']) in known:
            continue
        entry = {**sig, 'chart': f"charts/{sig['code']}_{sig['signal_date']}.json", 'notified': True}
        history.append(entry)
        payloads.append((entry, chart))

    # 같은 구간에 더 늦은 신호가 이미 있으면(예: 오늘 라이브 신호) 과거 것은 정리
    history, dropped = scan.prune_superseded(history)
    kept_ids = {id(h) for h in history}
    saved = 0
    for entry, chart in payloads:
        if id(entry) in kept_ids:
            scan.save_json(os.path.join(scan.DATA_DIR, entry['chart']), chart)
            saved += 1
    scan.remove_charts(dropped)

    history.sort(key=lambda h: (h['signal_date'], h['change_pct']), reverse=True)
    scan.save_json(scan.HISTORY_JSON, history[:50000], indent=1)
    print(f'새로 추가 {saved}건 / 전체 기록 {len(history)}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
