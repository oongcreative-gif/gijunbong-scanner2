"""가격 출처 진단 3차 (Actions의 price_probe). 파일은 바꾸지 않고 로그만 남겨요.

지금까지: 네이버 일봉 API 는 KRX 값만. 실시간 응답에는 NXT/통합 정보가 있음(integratedPriceInfo).
이번: NXT 일봉 주소를 찾는다. (1) 네이버 코드 속 chart/nxt 주소 문자열 (2) 추정 주소 시험 (3) 넥스트레이드 사이트 주소
"""
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


def scripts_of(page):
    r = get(page)
    html = r.text
    srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html) + re.findall(r'"(/[^"\s]+\.js)"', html)
    host = page.split('/')[2]
    out = []
    for s in dict.fromkeys(srcs):
        out.append(s if s.startswith('http') else ('https:' + s if s.startswith('//') else f'https://{host}' + (s if s.startswith('/') else '/' + s)))
    return html, out


def main():
    print(f'종목 {CODE}, 날짜 {DATE}')

    section('1) 네이버 코드 속 chart / nxt 주소 문자열')
    found = {}
    for page in (f'https://m.stock.naver.com/domestic/stock/{CODE}/chart', f'https://stock.naver.com/domestic/stock/{CODE}/price'):
        try:
            html, srcs = scripts_of(page)
        except Exception as e:                      # noqa: BLE001
            print(f'[페이지] {page} 실패 {e!r}')
            continue
        blobs = [(page, html)]
        for u in srcs[:80]:
            try:
                blobs.append((u, get(u).content.decode('utf-8', 'ignore')))
            except Exception:                       # noqa: BLE001
                pass
        for name, txt in blobs:
            for m in re.finditer(r'[\'"`]([^\'"`\s]{0,90}(?:chart|Chart|candle|nxt|Nxt|NXT)[^\'"`\s]{0,90})[\'"`]', txt):
                s = m.group(1)
                if re.search(r'(api|/chart|/nxt|/domestic|candle|Nxt|NXT)', s) and not s.endswith(('.png', '.svg', '.css', '.js')) and len(s) > 6:
                    found.setdefault(s, name.split('/')[-1][:30])
    print(f'  고유 문자열 {len(found)}개')
    for s, n in list(found.items())[:150]:
        print(f'  [진단] {s}   ({n})')

    section('2) 추정 NXT 일봉 주소 시험 (8/14 행, 거래량이 196853 이 아니면 후보)')
    rng = 'startDateTime=20260801&endDateTime=20261024'
    c = CODE
    cands = [
        f'https://api.stock.naver.com/chart/domestic-nxt/item/{c}/day?{rng}',
        f'https://api.stock.naver.com/chart/domesticNxt/item/{c}/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/nxt/item/{c}/day?{rng}',
        f'https://api.stock.naver.com/chart/nxt/item/{c}/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}_NXT/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}.NXT/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}:NXT/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}/nxt/day?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}/day/nxt?{rng}',
        f'https://api.stock.naver.com/chart/domestic/item/{c}?periodType=dayCandle&exchange=NXT&{rng}',
        f'https://m.stock.naver.com/api/stock/{c}/price/nxt?pageSize=60&page=1',
        f'https://m.stock.naver.com/api/nxt/stock/{c}/price?pageSize=60&page=1',
        f'https://m.stock.naver.com/api/stock/{c}.NXT/price?pageSize=60&page=1',
        f'https://m.stock.naver.com/api/stock/{c}/price?pageSize=60&page=1&stockExchangeType=NXT',
        f'https://m.stock.naver.com/api/stock/{c}/price?pageSize=60&page=1&exchangeType=NXT',
        f'https://m.stock.naver.com/api/stock/{c}/integration',
        f'https://m.stock.naver.com/api/stock/{c}/basic',
    ]
    for u in cands:
        try:
            r = get(u)
        except Exception as e:                      # noqa: BLE001
            print(f'  {u}\n    실패 {e!r}')
            continue
        t = r.text
        i = t.find(D8) if D8 in t else t.find(DATE)
        row = t[i - 20: i + 190].replace('\n', ' ') if i >= 0 else t[:140].replace('\n', ' ')
        flag = '  <<<<<< 후보' if r.status_code == 200 and i >= 0 and '196853' not in t[i: i + 200] and '196,853' not in t[i: i + 200] else ''
        print(f'  {u}\n    상태 {r.status_code}, {len(t)}자: {row}{flag}')

    section('3) 넥스트레이드 사이트 주소 (.do / api)')
    for page in ('https://www.nextrade.co.kr/menu/transactionStatusMain/menuList.do', 'https://www.nextrade.co.kr/'):
        try:
            html, srcs = scripts_of(page)
        except Exception as e:                      # noqa: BLE001
            print(f'[넥스트레이드] {page} 실패 {e!r}')
            continue
        urls = set(re.findall(r'[\'"]((?:/[A-Za-z0-9_\-]+)+\.do)[\'"]', html))
        for u in srcs[:30]:
            if 'nextrade' in u or u.startswith('https://www.nextrade'):
                try:
                    urls |= set(re.findall(r'[\'"]((?:/[A-Za-z0-9_\-]+)+\.do)[\'"]', get(u).text))
                except Exception:                   # noqa: BLE001
                    pass
        print(f'[넥스트레이드] {page}: .do 주소 {len(urls)}개, 스크립트 {len(srcs)}개')
        for u in sorted(urls)[:100]:
            print(f'  [진단] {u}')
    print('\n끝. "<<<<<<" 표시된 줄과 [진단] 줄을 알려주세요. 로그 파일을 통째로 첨부해 주셔도 돼요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
