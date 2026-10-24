"""가격 출처 진단 2차 (Actions의 price_probe). 파일은 바꾸지 않고 로그만 남겨요.

1차 결과: 네이버 일봉은 tradeType 을 바꿔도 KRX 값(8/14 종가 44,100)만 나온다.
2차: (1) 가격/실시간 응답 전체, (2) 네이버 페이지 코드에서 NXT 관련 문구, (3) 다른 파라미터 이름 시험,
     (4) 넥스트레이드 사이트와 KRX 주소 확인
"""
import json
import os
import re
import sys

import requests

CODE = os.environ.get('CODE', '456160').strip().zfill(6)
DATE = os.environ.get('DATE', '2026-08-14').strip()
D8 = DATE.replace('-', '')
WANT_CLOSE = os.environ.get('CLOSE', '44600').strip()
WANT_VOL = os.environ.get('VOLUME', '358632').strip()
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/124.0 Safari/537.36',
           'Referer': 'https://m.stock.naver.com/'}


def get(url, **kw):
    return requests.get(url, headers=HEADERS, timeout=25, **kw)


def day_row(text):
    i = text.find(f'"localDate":"{D8}"')
    return text[i: i + 200].replace('\n', ' ') if i >= 0 else ''


def section(t):
    print('\n' + '=' * 70 + f'\n{t}\n' + '=' * 70)


def main():
    print(f'종목 {CODE}, 날짜 {DATE}, 찾는 값: 종가 {WANT_CLOSE}, 거래량 {WANT_VOL}')

    section('1) 가격 / 실시간 응답 전체 (NXT 정보가 들어 있는지)')
    for label, url in (('가격', f'https://stock.naver.com/api/domestic/detail/{CODE}/price?tradeType=KRX&startIdx=0&pageSize=60'),
                       ('실시간', f'https://polling.finance.naver.com/api/realtime/domestic/stock/{CODE}')):
        try:
            t = get(url).text
            print(f'[{label}] {url}\n  [진단] {t[:2600]}')
        except Exception as e:                      # noqa: BLE001
            print(f'[{label}] 실패 {e!r}')

    section('2) 네이버 페이지 코드에서 NXT / tradeType 문구 찾기')
    pages = [f'https://m.stock.naver.com/domestic/stock/{CODE}/chart',
             f'https://m.stock.naver.com/domestic/stock/{CODE}/total',
             f'https://stock.naver.com/domestic/stock/{CODE}/chart',
             f'https://stock.naver.com/domestic/stock/{CODE}/price']
    seen, shown = set(), 0
    for p in pages:
        try:
            r = get(p)
        except Exception as e:                      # noqa: BLE001
            print(f'[페이지] {p} 실패 {e!r}')
            continue
        html = r.text
        srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html) + re.findall(r'"(/[^"\s]+\.js)"', html)
        print(f'[페이지] {p} 상태 {r.status_code}, {len(html)}자, 스크립트 {len(set(srcs))}개')
        blobs = [('html', html)]
        for s in list(dict.fromkeys(srcs))[:40]:
            u = s if s.startswith('http') else ('https:' + s if s.startswith('//') else
                                                 'https://' + p.split('/')[2] + (s if s.startswith('/') else '/' + s))
            if u in seen:
                continue
            seen.add(u)
            try:
                blobs.append((u, get(u).text))
            except Exception:                       # noqa: BLE001
                pass
        for name, txt in blobs:
            for m in re.finditer(r'NXT|nxt|tradeType|넥스트|통합시세|sorCode|exchangeType', txt):
                if shown >= 70:
                    break
                a = max(0, m.start() - 90)
                print(f'  [진단] {name.split("/")[-1][:40]}: …{txt[a: m.end() + 130]!r}')
                shown += 1
    print(f'  (문구 {shown}개 출력)')

    section('3) 다른 파라미터 이름 시험 (일봉 API, 8/14 행 비교)')
    base = f'https://api.stock.naver.com/chart/domestic/item/{CODE}/day?startDateTime=20260801&endDateTime=20261024'
    variants = ['', '&exchange=NXT', '&exchangeType=NXT', '&marketType=NXT', '&stockExchangeType=NXT', '&stockExchange=NXT',
                '&tradingSessionType=TOTAL', '&sessionType=TOTAL', '&sorCode=NXT', '&nxt=true', '&includeNxt=true',
                '&venue=NXT', '&exchange=TOTAL', '&exchangeType=TOTAL', '&tradeType=NX', '&tradeType=KRX_NXT',
                '&tradeType=INTEGRATED', '&tradeType=UNION', '&marketCode=NXT']
    ref = None
    for v in variants:
        try:
            t = get(base + v).text
        except Exception as e:                      # noqa: BLE001
            print(f'  {v or "(기본)"}: 실패 {e!r}')
            continue
        row = day_row(t)
        if ref is None:
            ref = row
        diff = '' if row == ref else '  <<<<<< 기본과 다름'
        hit = '  <<<<<< HTS 값 일치' if (WANT_CLOSE in t.replace(",", "") and WANT_VOL in t.replace(",", "")) else ''
        print(f'  {v or "(기본)"}: 상태 OK {len(t)}자 {row[:130]}{diff}{hit}')

    section('4) 넥스트레이드 / KRX 확인')
    for u in ('https://www.nextrade.co.kr/', 'https://www.nextrade.co.kr/menu/transactionStatusMain/menuList.do',
              'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'):
        try:
            r = get(u)
            print(f'[주소] {u} 상태 {r.status_code}, {len(r.text)}자\n  [진단] {re.sub(chr(10), " ", r.text[:300])}')
        except Exception as e:                      # noqa: BLE001
            print(f'[주소] {u} 실패 {e!r}')
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(f'KRX:{CODE}', '2026-08-10', '2026-08-20')
        print('[FDR KRX 짧은 기간]\n', df.to_string())
    except Exception as e:                          # noqa: BLE001
        print(f'[FDR KRX 짧은 기간] 실패 {e!r}')
    print('\n끝. 위 [진단] 줄과 "<<<<<<" 표시된 줄을 알려주세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
