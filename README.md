# 기준봉 스캐너

매 거래일 장 마감 후(한국시간 18:30) GitHub가 알아서 전종목을 스캔해서

- 새 기준봉이 뜨면 **텔레그램으로 알림**을 보내고
- 결과를 **사이트(GitHub Pages)**에 올려줍니다.

## 규칙
1. 60일선이 120일선 아래로 내려간 첫 날 = 역배열 시작일 (1일째)
2. 시작일부터 **60일(달력일)** 동안, 역배열이 유지되는 구간에서
3. 그 봉이 양봉이고 종가가 **직전 60거래일 모든 봉(음봉 포함)의 종가보다 높으면** 기준봉이에요 (봉 크기·거래량은 안 봐요)
4. 한 역배열 구간에서는 **처음 뜬 기준봉이 고정**되고 더 알리지 않아요

## 올리는 순서

### 1. 텔레그램 봇 만들기 (폰에서 5분)
1. 텔레그램에서 `@BotFather` 검색 → `/newbot` → 이름과 아이디를 정하면 **봇 토큰**을 줘요. (예: `123456:ABC-DEF...`)
2. 방금 만든 봇 대화창에서 아무 말이나 한 번 보내요. (이걸 해야 봇이 나한테 메시지를 보낼 수 있어요)
3. 브라우저 주소창에 `https://api.telegram.org/bot<봇토큰>/getUpdates` 를 열면 JSON이 나와요. 거기서 `"chat":{"id":123456789,...}` 의 숫자가 **chat id**예요.

### 2. GitHub 저장소 만들기
1. github.com 가입/로그인 → 오른쪽 위 `+` → **New repository**
2. 이름은 자유(예: `gijunbong-scanner`), **Public**으로 만들어요. (무료 계정은 Public이어야 사이트를 띄울 수 있어요)
3. 이 폴더의 파일을 전부 올려요. 저장소 화면의 **uploading an existing file** 에 폴더째 끌어다 놓으면 돼요.
   - `.github/workflows/scan.yml` 이 안 올라가면: **Add file → Create new file** 에서 파일 이름 칸에 `.github/workflows/scan.yml` 을 입력하고 내용을 붙여넣어요.

### 3. 비밀값 넣기
저장소 **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` : 1번에서 받은 봇 토큰
- `TELEGRAM_CHAT_ID` : 1번에서 찾은 chat id

### 4. 사이트 켜기
**Settings → Pages → Build and deployment**
- Source: **Deploy from a branch**
- Branch: **main**, 폴더: **/docs** → Save

몇 분 뒤 `https://<내 아이디>.github.io/<저장소 이름>/` 에서 사이트가 열려요.

### 5. 첫 실행 (테스트)
**Actions 탭 → scan → Run workflow**
- `force` 칸에 `1` 을 넣으면 휴장일/장 마감 전에도 마지막 거래일 기준으로 돌아가요.
- 끝나면 텔레그램에 알림이 오고, 사이트에 종목이 보여요.
- 초록 체크가 뜨면 성공이에요. 이후에는 평일 18:30에 자동으로 돌아요.

### 6. 과거 기록 채우기 (선택, 한 번만)
**Actions 탭 → backfill → Run workflow** 에서 시작일/종료일(기본 2026-08-01 ~ 2026-10-21)을 확인하고 실행해요.
- 기간 안에 뜬 기준봉을 역배열 구간별로 **마지막(최종) 기준봉만** 남겨서 사이트 기록에 넣어요. 텔레그램은 보내지 않아요.
- 종목 목록은 오늘 기준이라 그 사이 상장폐지된 종목은 빠져요.
- 10~20분쯤 걸려요. 끝나면 사이트 기록 표에 과거 종목이 채워져요.

## 문제가 생기면
- **`KRX 종목 목록 조회 실패`** 가 로그에 나오면: GitHub 서버에서 KRX 목록이 막힌 거예요. 코랩에서 `get_universe().to_csv('universe.csv', index=False)` 를 실행해 만든 파일을 저장소의 `data/universe.csv` 로 올려주면 그걸 대신 써요.
- **사이트가 안 바뀌면**: Actions 탭의 `pages build and deployment` 가 끝났는지 확인해 주세요.
- **알림이 안 오면**: Secrets 이름 철자와 chat id를 확인하고, 봇에게 먼저 말을 걸었는지 확인해 주세요.

