"""가격 출처 진단 6차 (Actions의 price_probe). 파일은 바꾸지 않고 로그만 남겨요.

pricesByPeriod 는 지수용. 종목용으로 보이는 /front-api/chart/domesticPriceByTime(/marketInfo) 을
exchangeType=KRX/NXT 로 호출해서 8/14 행을 비교한다.
"""
import itertools
import os
import re
import sys

import requests

CODE = os.environ.get('CODE', '456160').strip().zfill(6)
DATE = os.environ.get('DATE', '2026-08-14').strip()
D8 = DATE.replace('-', '')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')
H = {'User-Agent': UA, 'Referer': 'https://m.stock.naver.com/'}
BASE = 'https://m.stock.naver.com/front-api/chart/'


def section(t):
    print('\n' + '=' * 70 + f'\n{t}\n' + '=' * 70)


def get(url):
    return requests.get(url, headers=H, timeout=25)


def row_of(t):
    for key in (D8, DATE, DATE.replace('-', '.')):
        i = t.find(key)
        if i >= 0:
            return t[max(0, i - 60): i + 280].replace('\n', ' ')
    return ''


def main():
    print(f'종목 {CODE}, 날짜 {DATE}')

    section('1) domesticPriceByTime 에러 메시지 (허용 값 확인)')
    errs = set()
    for path in ('domesticPriceByTime', 'domesticPriceByTime/marketInfo'):
        for q in (f'reutersCode={CODE}', f'reutersCode={CODE}&chartInfoType=item',
                  f'reutersCode={CODE}&chartInfoType=item&timeFrame=day&startDateTime=202608010000&endDateTime=202610242359'):
            try:
                r = get(f'{BASE}{path}?{q}')
            except Exception as e:                  # noqa: BLE001
                print(f'  {path}?{q}\n    실패 {e!r}')
                continue
            if r.text not in errs:
                errs.add(r.text)
                print(f'  {path}?{q}\n    상태 {r.status_code}, {len(r.text)}자: {r.text[:1500]}')

    section('2) 조합 시험 (200 응답만 출력, 8/14 행이 KRX 값 196853 이 아니면 후보)')
    infos = ['item', 'stock']
    frames = ['day', 'DAY', 'candleDay', 'dayCandle', 'days', 'daily']
    dates = [('202608010000', '202610242359'), ('20260801', '20261024'), ('20260801000000', '20261024235959')]
    exch = [None, 'KRX', 'NXT', 'nxt', 'ALL']
    shown = 0
    for path, ci, tf, (sd, ed), ex in itertools.product(('domesticPriceByTime', 'domesticPriceByTime/marketInfo'), infos, frames, dates, exch):
        q = f'reutersCode={CODE}&chartInfoType={ci}&timeFrame={tf}&startDateTime={sd}&endDateTime={ed}' + (f'&exchangeType={ex}' if ex else '')
        try:
            r = get(f'{BASE}{path}?{q}')
        except Exception:                           # noqa: BLE001
            continue
        if r.status_code == 200 and len(r.text) > 80:
            row = row_of(r.text)
            flag = '  <<<<<< 후보(KRX 값과 다름)' if row and '196853' not in row else ''
            print(f'  200 {path}?{q}\n    {len(r.text)}자 {row or r.text[:260]}{flag}')
            shown += 1
            if shown >= 45:
                break
    print(f'  (200 응답 {shown}건)')

    section('3) 참고: 같은 방식으로 지투지바이오 8/14 값 직접 비교용 (KRX/NXT 별 응답 앞부분)')
    for ex in ('KRX', 'NXT'):
        q = f'reutersCode={CODE}&chartInfoType=item&timeFrame=day&startDateTime=202608100000&endDateTime=202608200000&exchangeType={ex}'
        try:
            r = get(f'{BASE}domesticPriceByTime?{q}')
            print(f'  {ex}: 상태 {r.status_code}, {len(r.text)}자: {r.text[:700]}')
        except Exception as e:                      # noqa: BLE001
            print(f'  {ex} 실패 {e!r}')
    print('\n끝. 로그 파일을 통째로 첨부해 주세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
