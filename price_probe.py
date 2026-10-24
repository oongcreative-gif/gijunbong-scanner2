"""가격 출처 진단 (Actions의 price_probe 에서 실행). 파일은 바꾸지 않고 로그만 남겨요.

HTS(통합 시세)와 스캐너(KRX 시세)의 일봉이 다른 이유를 확인하려고,
여러 시세 주소를 호출해서 HTS 값(시가/종가/거래량)과 맞는 곳을 찾는다.
기본 예시: 지투지바이오 2026-08-14 -> 시가 43,350 / 종가 44,600 / 거래량 358,632
"""
import os
import re
import sys

import requests

CODE = os.environ.get('CODE', '456160').strip().zfill(6)
DATE = os.environ.get('DATE', '2026-08-14').strip()
WANT = {k: v for k, v in (('시가', os.environ.get('OPEN', '43350')),
                          ('종가', os.environ.get('CLOSE', '44600')),
                          ('거래량', os.environ.get('VOLUME', '358632'))) if v}
D8 = DATE.replace('-', '')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/124.0 Safari/537.36',
           'Referer': 'https://m.stock.naver.com/'}


def judge(text):
    flat = text.replace(',', '')
    hits = [k for k, v in WANT.items() if re.search(rf'(?<!\d){re.escape(v)}(?![\d])', flat)]
    return hits


def around(text, n=260):
    for key in (DATE, D8):
        i = text.find(key)
        if i >= 0:
            return text[max(0, i - 60): i + n].replace('\n', ' ')
    return ''


def try_url(label, url):
    print('-' * 70)
    print(f'[{label}] {url}')
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except Exception as e:                      # noqa: BLE001
        print(f'  [진단] 연결 실패: {e!r}')
        return
    t = r.text or ''
    hits = judge(t)
    print(f'  [진단] 상태 {r.status_code}, {len(t)}자, HTS 값과 일치: {hits if hits else "없음"}'
          f'{"  <<<<<< 후보" if len(hits) >= 2 else ""}')
    snip = around(t)
    print(f'  [진단] {DATE} 부근: {snip if snip else "(그 날짜 없음) 앞부분: " + t[:220].replace(chr(10), " ")}')


def try_fdr(sym):
    print('-' * 70)
    print(f'[FDR] DataReader({sym!r})')
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(sym, '2026-08-10', '2026-08-20')
        print(f'  [진단] 행 {len(df)}')
        print(df.to_string())
    except Exception as e:                      # noqa: BLE001
        print(f'  [진단] 실패: {e!r}')


def main():
    print(f'종목 {CODE}, 날짜 {DATE}, 찾을 값 {WANT}')
    try:
        import FinanceDataReader as fdr
        print('FinanceDataReader', getattr(fdr, '__version__', '?'))
    except Exception as e:                      # noqa: BLE001
        print('FDR 불러오기 실패', e)
    for s in (CODE, f'KRX:{CODE}', f'NXT:{CODE}', f'NAVER:{CODE}'):
        try_fdr(s)

    c = CODE
    urls = [
        ('네이버 fchart (FDR이 쓰는 곳)', f'https://fchart.stock.naver.com/sise.nhn?symbol={c}&timeframe=day&count=120&requestType=0'),
        ('api.stock 일봉', f'https://api.stock.naver.com/chart/domestic/item/{c}/day?startDateTime=20260801&endDateTime=20261024'),
        ('api.stock 일봉 NXT', f'https://api.stock.naver.com/chart/domestic/item/{c}/day?startDateTime=20260801&endDateTime=20261024&tradeType=NXT'),
        ('api.stock 일봉 TOTAL', f'https://api.stock.naver.com/chart/domestic/item/{c}/day?startDateTime=20260801&endDateTime=20261024&tradeType=TOTAL'),
        ('api.stock 일봉 ALL', f'https://api.stock.naver.com/chart/domestic/item/{c}/day?startDateTime=20260801&endDateTime=20261024&tradeType=ALL'),
        ('m.stock price', f'https://m.stock.naver.com/api/stock/{c}/price?pageSize=60&page=1'),
        ('m.stock price NXT', f'https://m.stock.naver.com/api/stock/{c}/price?pageSize=60&page=1&tradeType=NXT'),
        ('m.stock price TOTAL', f'https://m.stock.naver.com/api/stock/{c}/price?pageSize=60&page=1&tradeType=TOTAL'),
    ]
    for tt in ('KRX', 'NXT', 'TOTAL', 'ALL', 'INTEGRATED'):
        urls.append((f'stock.naver trend {tt}', f'https://stock.naver.com/api/domestic/detail/{c}/trend?tradeType={tt}&startIdx=0&pageSize=60'))
    for path in ('price', 'prices', 'chart', 'candle', 'daily', 'dailyPrice'):
        for tt in ('KRX', 'NXT', 'TOTAL'):
            urls.append((f'stock.naver {path} {tt}', f'https://stock.naver.com/api/domestic/detail/{c}/{path}?tradeType={tt}&startIdx=0&pageSize=60'))
    urls.append(('실시간(NXT 포함 여부)', f'https://polling.finance.naver.com/api/realtime/domestic/stock/{c}'))
    for label, u in urls:
        try_url(label, u)
    print('=' * 70)
    print('끝. "후보" 표시가 붙은 줄(HTS 값 2개 이상 일치)과 그 아래 [진단] 줄을 알려주세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
