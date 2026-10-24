"""가격 출처 진단 4차 (Actions의 price_probe). 파일은 바꾸지 않고 로그만 남겨요.

단서: 네이버 코드의 /chart/pricesByPeriod, krxNxtIntegratedPriceInfo / 넥스트레이드 transactionStatusDaily
이번: (1) 그 이름 주변 코드 전문 (2) pricesByPeriod 추정 호출 (3) 넥스트레이드 일별 시세 페이지가 부르는 주소
"""
import json
import os
import re
import sys

import requests

CODE = os.environ.get('CODE', '456160').strip().zfill(6)
DATE = os.environ.get('DATE', '2026-08-14').strip()
D8 = DATE.replace('-', '')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/124.0 Safari/537.36',
           'Referer': 'https://m.stock.naver.com/'}


def get(url, **kw):
    return requests.get(url, headers=HEADERS, timeout=25, **kw)


def section(t):
    print('\n' + '=' * 70 + f'\n{t}\n' + '=' * 70)


def scripts_of(page, hostfilter=None):
    html = get(page).text
    srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html) + re.findall(r'"(/[^"\s]+\.js)"', html)
    host = page.split('/')[2]
    out = []
    for s in dict.fromkeys(srcs):
        out.append(s if s.startswith('http') else ('https:' + s if s.startswith('//') else f'https://{host}' + (s if s.startswith('/') else '/' + s)))
    return html, out


def ctx(txt, key, before=300, after=700, limit=3):
    n = 0
    for m in re.finditer(re.escape(key), txt):
        a = max(0, m.start() - before)
        print(f'  [진단] …{txt[a: m.end() + after]!r}')
        n += 1
        if n >= limit:
            break
    return n


def main():
    print(f'종목 {CODE}, 날짜 {DATE}')

    section('1) 네이버 코드 속 pricesByPeriod / securityService/chart / fchart 주변')
    page = f'https://m.stock.naver.com/domestic/stock/{CODE}/chart'
    html, srcs = scripts_of(page)
    keys = ['/chart/pricesByPeriod', '/api/securityService/chart/', '/api/securityFe/api/fchart/', 'krxNxtIntegratedPriceInfo',
            'scriptChartType', 'chartInfoType']
    used = {k: 0 for k in keys}
    for u in srcs[:90]:
        try:
            t = get(u).content.decode('utf-8', 'ignore')
        except Exception:                           # noqa: BLE001
            continue
        for k in keys:
            if k in t and used[k] < 3:
                print(f'\n--- {k}  ({u.split("/")[-1][:34]})')
                used[k] += ctx(t, k, limit=2)
    print('\n  검색 결과 개수:', used)

    section('2) pricesByPeriod 추정 호출 (8/14 행의 거래량이 196853 이 아니면 후보)')
    bases = ['https://m.stock.naver.com/front-api/chart/pricesByPeriod',
             'https://m.stock.naver.com/front-api/v1/chart/pricesByPeriod']
    qs = [
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&stockExchangeType=NXT',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&exchangeType=NXT',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&priceSourceKey=NXT',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&exchange=NXT',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&isNxt=true',
        f'reutersCode={CODE}&category=stock&chartInfoType=stock&scriptChartType=candle&periodType=dayCandle&startDateTime=202608010000&endDateTime=202610242359&integrated=true',
    ]
    for b in bases:
        for q in qs:
            u = f'{b}?{q}'
            try:
                r = get(u)
            except Exception as e:                  # noqa: BLE001
                print(f'  {u}\n    실패 {e!r}')
                continue
            t = r.text
            i = t.find(D8) if D8 in t else t.find(DATE)
            row = t[max(0, i - 30): i + 220].replace('\n', ' ') if i >= 0 else t[:160].replace('\n', ' ')
            flag = '  <<<<<< 후보' if r.status_code == 200 and i >= 0 and '196853' not in t[i: i + 250] else ''
            print(f'  {u.replace("https://m.stock.naver.com", "")[:150]}\n    상태 {r.status_code}, {len(t)}자: {row}{flag}')

    section('3) 넥스트레이드 일별 시세 페이지가 부르는 주소')
    for page in ('https://www.nextrade.co.kr/menu/transactionStatusDaily/menuList.do',
                 'https://www.nextrade.co.kr/menu/transactionStatusMain/menuList.do'):
        try:
            html, srcs = scripts_of(page)
        except Exception as e:                      # noqa: BLE001
            print(f'[페이지] {page} 실패 {e!r}')
            continue
        print(f'[페이지] {page}: 스크립트 {len(srcs)}개')
        blobs = [(page, html)]
        for u in srcs:
            if 'nextrade' in u:
                try:
                    blobs.append((u, get(u).content.decode('utf-8', 'ignore')))
                except Exception:                   # noqa: BLE001
                    pass
        seen = set()
        for name, t in blobs:
            for m in re.finditer(r'(?:url|URL|href)\s*[:=]\s*[\'"]([^\'"]+)[\'"]', t):
                s = m.group(1)
                if s not in seen and ('.do' in s or 'api' in s or 'brd' in s):
                    seen.add(s)
                    print(f'  [진단] url: {s}   ({name.split("/")[-1][:30]})')
            for m in re.finditer(r'[\'"](/[A-Za-z0-9_\-/]*(?:brd|Brd|daily|Daily|trans|Trans)[A-Za-z0-9_\-/]*\.do)[\'"]', t):
                s = m.group(1)
                if s not in seen:
                    seen.add(s)
                    print(f'  [진단] .do: {s}   ({name.split("/")[-1][:30]})')
        # 일별 시세 추정 호출 (POST)
        break_cands = ['/brdinfoDaily/brdinfoDailyList.do', '/brdinfoTime/brdinfoTimeList.do',
                       '/transactionStatusDaily/list.do', '/brdinfoDay/brdinfoDayList.do']
        for p in break_cands:
            for body in ({'pageUnit': 10, 'pageIndex': 1, 'scAll': 'N', 'searchKey': CODE, 'scMktId': '', 'scIsuNo': CODE, 'scTrdDd': D8},
                         {'trdDd': D8, 'isuCd': CODE}):
                try:
                    r = requests.post('https://www.nextrade.co.kr' + p, data=body, headers={**HEADERS, 'Referer': page,
                                      'X-Requested-With': 'XMLHttpRequest'}, timeout=25)
                    print(f'  POST {p} {list(body)[:3]} -> 상태 {r.status_code}, {len(r.text)}자: {r.text[:160]!r}')
                except Exception as e:              # noqa: BLE001
                    print(f'  POST {p} 실패 {e!r}')
        break
    print('\n끝. 로그 파일을 통째로 첨부해 주세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
