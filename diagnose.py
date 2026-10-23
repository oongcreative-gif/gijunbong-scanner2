"""종목별 진단 (Actions의 diagnose에서 실행)

CODES 에 종목명 또는 6자리 코드를 쉼표로 넣으면, 각 종목이
- 스캔 대상에 들어가는지(시총/거래대금)
- 최근 역전일과 그 이후 봉별 종가·양봉 여부
- 어떤 봉이 '역전일 이후 종가 최고 양봉'(A)인지, '직전 60봉 종가 최고 양봉'(B, 현재 규칙)인지
- 현재 규칙으로 어떤 날 신호가 나는지
를 로그로 보여준다. 파일은 바꾸지 않는다.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import scan


def resolve(items, lst):
    out = []
    for it in items:
        if it.isdigit():
            out.append(it.zfill(6))
            continue
        hit = lst[lst['Name'] == it]
        if hit.empty:
            hit = lst[lst['Name'].str.contains(it, regex=False, na=False)]
        if hit.empty:
            print(f'[{it}] 종목 목록에서 못 찾았어요')
            continue
        out.append(str(hit.iloc[0]['Code']).zfill(6))
    return out


def show(code, lst):
    row = lst[lst['Code'] == code]
    name = row.iloc[0]['Name'] if not row.empty else code
    print('=' * 70)
    if not row.empty:
        r = row.iloc[0]
        marcap = r.get('Marcap', float('nan'))
        amount = r.get('Amount', float('nan'))
        in_uni = (marcap >= scan.MIN_MARCAP) if pd.notna(marcap) else None
        print(f'{name} ({code}) {r.get("Market", "")}  시총 {marcap / 1e8:,.0f}억  오늘 거래대금 {amount / 1e8:,.1f}억'
              f'  → 시총 500억 이상: {in_uni}')
    else:
        print(f'{name} ({code}) 종목 목록에 없음')
    start = (datetime.now(scan.KST) - timedelta(days=scan.LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    raw = scan.fdr.DataReader(code, start)
    df = scan.prepare(raw)
    crosses = np.flatnonzero(df['cross'].values)
    if len(crosses) == 0:
        print('역전일 없음 (조회 기간 안에 역배열 시작이 없어요)')
        return
    print('역전일(최근 3개):', [df.index[i].date().isoformat() for i in crosses[-3:]])
    c = int(crosses[-1])
    end = df.index[c] + timedelta(days=scan.WINDOW_DAYS - 1)
    print(f'마지막 역전일 {df.index[c].date()} → 60일 구간 끝 {end.date()}')
    seg = df.iloc[c:]
    closes = df['Close'].values
    print('날짜        시가    종가   전일비  양봉 역배열  A(역전일이후최고)  B(직전60봉최고)  구간')
    first_a = None
    for k, (d, r) in enumerate(seg.iterrows()):
        i = c + k
        prev_all = closes[c:i]
        bull = bool(r['Close'] > r['Open'])
        a = bull and (len(prev_all) == 0 or r['Close'] > prev_all.max())
        lo = max(0, i - 59)
        prev60 = closes[lo:i]
        b = bull and (len(prev60) == 0 or r['Close'] > prev60.max())
        if a and first_a is None:
            first_a = d
        chg = (r['Close'] / closes[i - 1] - 1) * 100 if i > 0 else 0
        inwin = d <= end
        mark = ' ◀ A 첫 후보' if (a and first_a == d) else ''
        if k < 70:
            print(f'{d.date()} {r["Open"]:>8,.0f} {r["Close"]:>8,.0f} {chg:>+6.1f}%  {"양" if bull else "음"}   '
                  f'{"O" if r["inv"] else "정배열"}      {"A" if a else "-"}               {"B" if b else "-"}             '
                  f'{"안" if inwin else "밖"}{mark}')
    print('--- 현재 규칙(scan.py)으로 신호가 나는 날 ---')
    found = False
    for i in range(c, len(df)):
        s = scan.check_at(df, i)
        if s:
            found = True
            amt = float(df['Close'].iloc[i]) * float(df['Volume'].iloc[i]) / 1e8
            print(f"{s['signal_date']}  종가 {s['close']:,.0f}  거래대금 {amt:,.1f}억  역배열 {s['day_no']}일째")
    if not found:
        print('없음')


def main():
    items = [x.strip() for x in os.environ.get('CODES', '').replace('\n', ',').split(',') if x.strip()]
    if not items:
        print('CODES 가 비었어요')
        return 1
    lst = scan.fdr.StockListing('KRX')
    if 'Code' not in lst.columns and 'Symbol' in lst.columns:
        lst = lst.rename(columns={'Symbol': 'Code'})
    lst['Code'] = lst['Code'].astype(str).str.zfill(6)
    for code in resolve(items, lst):
        try:
            show(code, lst)
        except Exception as e:  # noqa: BLE001
            print(f'{code} 진단 실패: {e!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
