"""가격 출처 진단 5차 (Actions의 price_probe). 파일은 바꾸지 않고 로그만 남겨요.

(1) 네이버 front-api/chart/pricesByPeriod : 허용 값(에러 메시지)과 exchangeType=NXT 호출
(2) 넥스트레이드 /dailyInfo/dailyInfoList.do : 페이지 코드의 폼 이름과 호출
"""
import itertools
import json
import os
import re
import sys

import requests

CODE = os.environ.get('CODE', '456160').strip().zfill(6)
DATE = os.environ.get('DATE', '2026-08-14').strip()
D8 = DATE.replace('-', '')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')
H = {'User-Agent': UA, 'Referer': 'https://m.stock.naver.com/'}


def section(t):
    print('\n' + '=' * 70 + f'\n{t}\n' + '=' * 70)


def get(url, **kw):
    return requests.get(url, headers=H, timeout=25, **kw)


def show_row(t):
    i = t.find(D8) if D8 in t else t.find(DATE)
    return t[max(0, i - 40): i + 260].replace('\n', ' ') if i >= 0 else ''


def main():
    print(f'종목 {CODE}, 날짜 {DATE}')
    base = 'https://m.stock.naver.com/front-api/chart/pricesByPeriod'

    section('1-a) 네이버 pricesByPeriod 에러 메시지 전체 (허용 값 확인)')
    seen = set()
    for q in (f'reutersCode={CODE}', f'reutersCode={CODE}&chartInfoType=item&timeFrame=day&startDateTime=202608010000&endDateTime=202610242359',
              f'reutersCode={CODE}&chartInfoType=stock&timeFrame=day&startDateTime=202608010000&endDateTime=202610242359'):
        try:
            r = get(f'{base}?{q}')
            m = r.text
            if m not in seen:
                seen.add(m)
                print(f'  {q}\n    상태 {r.status_code}: {m[:1800]}')
        except Exception as e:                      # noqa: BLE001
            print(f'  실패 {e!r}')

    section('1-b) 조합 시험 (8/14 행이 나오면 출력, 거래량이 196853 이 아니면 후보)')
    infos = ['item', 'ITEM', 'stock', 'domesticStock', 'domestic', 'itemChart']
    frames = ['day', 'DAY', 'candleDay', 'dayCandle', 'days']
    dates = [('202608010000', '202610242359'), ('20260801', '20261024'), ('2026-08-01', '2026-10-24')]
    exch = [None, 'KRX', 'NXT', 'nxt', 'ALL']
    shown = 0
    for ci, tf, (sd, ed), ex in itertools.product(infos, frames, dates, exch):
        q = f'reutersCode={CODE}&chartInfoType={ci}&timeFrame={tf}&startDateTime={sd}&endDateTime={ed}' + (f'&exchangeType={ex}' if ex else '')
        try:
            r = get(f'{base}?{q}')
        except Exception:                           # noqa: BLE001
            continue
        if r.status_code == 200 and len(r.text) > 50:
            row = show_row(r.text)
            flag = '  <<<<<< 후보(KRX 값과 다름)' if row and '196853' not in row else ''
            print(f'  200  {q}\n    {len(r.text)}자 {row or r.text[:200]}{flag}')
            shown += 1
            if shown >= 40:
                break
    print(f'  (200 응답 {shown}건)')

    section('2) 넥스트레이드 dailyInfoList.do')
    page = 'https://www.nextrade.co.kr/menu/transactionStatusDaily/menuList.do'
    try:
        html = requests.get(page, headers=H, timeout=25).text
        for m in re.finditer(r'dailyInfoList', html):
            a = max(0, m.start() - 900)
            print(f'  [진단] …{html[a: m.end() + 900]!r}')
            break
        srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html)
        for s in srcs:
            u = s if s.startswith('http') else 'https://www.nextrade.co.kr' + (s if s.startswith('/') else '/' + s)
            if 'nextrade' not in u:
                continue
            try:
                t = requests.get(u, headers=H, timeout=25).content.decode('utf-8', 'ignore')
            except Exception:                       # noqa: BLE001
                continue
            if 'dailyInfoList' in t:
                i = t.find('dailyInfoList')
                print(f'  [진단] JS {u.split("/")[-1]}: …{t[max(0, i - 800): i + 1200]!r}')
                break
        print('  [진단] 입력칸 이름:', sorted(set(re.findall(r'name="([^"]+)"', html)))[:60])
    except Exception as e:                          # noqa: BLE001
        print(f'  페이지 실패 {e!r}')
    hh = {**H, 'Referer': page, 'X-Requested-With': 'XMLHttpRequest'}
    tries = [
        {'scBeginDe': D8, 'scEndDe': D8, 'pageUnit': 500, 'pageIndex': 1},
        {'scBeginDe': D8, 'scEndDe': D8, 'pageUnit': 500, 'pageIndex': 1, 'scAll': 'Y'},
        {'scBeginDe': D8, 'scEndDe': D8, 'searchKey': CODE, 'pageUnit': 50, 'pageIndex': 1},
        {'scBeginDe': D8, 'scEndDe': D8, 'scIsuSrtCd': CODE, 'pageUnit': 50, 'pageIndex': 1},
        {'scDe': D8, 'pageUnit': 500, 'pageIndex': 1},
        {'trdDd': D8, 'pageUnit': 500, 'pageIndex': 1},
        {'scBeginDe': D8, 'scEndDe': D8, 'scMktId': '', 'scIsuNo': CODE, 'pageUnit': 50, 'pageIndex': 1},
    ]
    for body in tries:
        try:
            r = requests.post('https://www.nextrade.co.kr/dailyInfo/dailyInfoList.do', data=body, headers=hh, timeout=25)
            t = r.text
            print(f'  POST {body}\n    상태 {r.status_code}, {len(t)}자: {t[:420]!r}')
            if CODE in t:
                i = t.find(CODE)
                print(f'    <<<<<< 종목 발견: …{t[max(0, i - 200): i + 500]!r}')
        except Exception as e:                      # noqa: BLE001
            print(f'  POST {body} 실패 {e!r}')
    print('\n끝. 로그 파일을 통째로 첨부해 주세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
