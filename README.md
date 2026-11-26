# naverPydoll

[pydoll](https://github.com/autoscrape-labs/pydoll)(WebDriver 없이 CDP로 Chrome을 직접 제어하는 Python 라이브러리)로
stealth 접속을 구성하고, 네이버 쇼핑 검색 결과의 상품 목록을 JSON으로 저장하는 시험 프로젝트입니다.

- 시험 일자: 2026-11-26
- 시험 환경: macOS(Apple Silicon), Google Chrome 158, Python 3.12, pydoll-python 3.0.1
- Windows용 분기도 들어 있지만 **실제 Windows 기기에서는 실행해 보지 않았습니다.**

## 요약

- macOS 의 실제 Chrome 을 CDP 로 제어해 네이버 가격비교 상품 목록을 받을 수 있었습니다.
- 새 브라우저 프로필에서는 보안 확인(CAPTCHA)을 **사람이 한 번** 통과해야 합니다. 통과한 프로필을 저장해 두면
  이후 실행은 헤드리스로도 그대로 열렸습니다.
- 보안 확인은 자동으로 풀지 않습니다. 브라우저 창에서 직접 풀거나, Slack 으로 화면을 받아 답을 적어 보냅니다.
  Slack 전달은 실제 보안 확인으로 통과를 확인했습니다.
- 가격 필터, 정렬, 여러 페이지 수집이 동작합니다. 가격 필터와 정렬을 서버에서 함께 쓰는 것은 차단됩니다.
- 출구 IP 가 매번 바뀌는 프록시에서는 목록 조회만 되고 가격 필터는 차단됩니다.
- **Linux 신원(Docker 컨테이너 포함)은 보안 확인 단계 없이 바로 차단됩니다.**
- 모두 검색어 1개, 하루, 수십 회 수준의 소규모 시험 결과입니다.

## 소스 구성

| 파일 | 역할 |
| --- | --- |
| `stealth_visit.py` | stealth 접속 샘플. 브라우저 옵션, 핑거프린트 적용, 사전 방문(warm-up), 보안 확인 대기, 접속 후 브라우저가 보고하는 값 출력 |
| `fingerprints.py` | 일관된 핑거프린트 프로필. macOS(Apple Silicon)용과 Windows 11용, 둘 다 서울 신원 |
| `naver_products.py` | 네이버 쇼핑 검색 결과를 JSON으로 저장. 가격 필터, 정렬 지원 |
| `human_relay.py` | 보안 확인 화면을 메신저(Telegram, Slack)로 사람에게 보내고 답을 받아 오는 모듈 |
| `tests/relay_mock_test.py` | 메신저 호출을 가짜 서버로 검증하는 시험 |
| `.env.example` | 메신저 토큰 설정 예시 |
| `Dockerfile` | 시험용 컨테이너 이미지 (Linux, 헤드리스). 아래 "Docker 시험" 참고 |
| `requirements.txt` | 의존 패키지 |

`naver_products.py`는 `stealth_visit.py`의 접속 흐름(`build_options`, `open_page`)을 그대로 가져다 씁니다.

### stealth 구성

1. **CDP 직접 연결**: WebDriver를 쓰지 않아 `navigator.webdriver` 같은 자동화 흔적이 처음부터 없습니다.
2. **브라우저 옵션**: WebRTC IP 유출 차단, `Accept-Language` 설정, 알림·팝업 차단.
3. **핑거프린트**: `tab.apply_fingerprint()`로 User-Agent, Client Hints, WebGL, 화면, 폰트, 음성, 언어, 시간대를
   하나의 신원으로 맞춥니다. pydoll 저장소의 `examples/fingerprints.py`를 기반으로 했습니다.
   - Chrome 버전은 하드코딩하지 않고 실제로 띄운 Chrome에서 읽습니다 (TLS/HTTP2 지문은 위장할 수 없으므로 버전이 어긋나면 안 됨).
   - OS는 실행 기기와 같게 둡니다. Mac에서는 Mac 프로필, Windows에서는 Windows 프로필이 자동 선택됩니다.
   - 언어·시간대·위치는 서울 기준입니다. 다른 나라 프록시를 쓰면 `fingerprints.py`의 지역 값을 바꿔야 합니다.
4. **사람 같은 동작**: 마우스 이동, 클릭, 입력에 `humanize=True`를 씁니다.

### 보안 확인(CAPTCHA) 처리 원칙

보안 확인은 **자동으로 풀지 않습니다.** 보안 확인이 뜨면 알림을 보내고 브라우저 창에서 사람이 직접 풀 때까지
기다린 뒤 이어서 진행합니다. 헤드리스 실행 중이었다면 같은 프로필을 창 표시 모드로 다시 엽니다.
`--user-data-dir`로 프로필을 유지하면 한 번 통과한 상태가 다음 실행에도 남습니다.

### 메신저로 보안 확인 전달 (`--relay`)

창 앞에 사람이 없어도 되도록, 보안 확인 화면의 스크린샷과 질문을 메신저로 보내고 사람이 답장한 답을
입력해 제출합니다. 답은 사람이 냅니다. 헤드리스에서도 동작합니다.

```bash
cp .env.example .env                       # 토큰과 채널(대화방) ID 를 채운다
.venv/bin/python human_relay.py telegram   # 연결 시험 (slack 도 같은 방식)
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --headless --relay telegram
```

- `telegram`: 봇 토큰과 chat id 가 필요합니다. 봇 메시지에 **답장**으로 답합니다.
- `slack`: 봇 토큰(`chat:write`, `files:write`, `channels:history` 권한)과 채널 ID 가 필요합니다.
  봇 메시지의 **스레드**에 답합니다.
- `dialog`: 메신저 없이 이 Mac 화면에 스크린샷과 입력 창을 띄웁니다 (연동 전 시험용).
- 여러 인스턴스가 동시에 보안 확인을 만나도 메신저에는 한 번에 한 건만 나갑니다.
  틀리면 새 문제를 다시 보내며(최대 3회), `--wait-human` 초 안에 답이 없으면 작업을 중단합니다.
- 준비 절차는 `human_relay.py` 맨 위의 설명을 참고하세요.

시험 상태: Slack 은 실제 워크스페이스에서 연결 시험과 보안 확인 통과까지 확인했습니다
(아래 "시험 내용과 결과" 6번). Telegram 은 가짜 서버로만 검증했고(`tests/relay_mock_test.py`)
실제 토큰으로는 실행하지 않았습니다.

## 설치

Python 3.10 이상과 Google Chrome이 필요합니다.

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

```bat
:: Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

아래 명령은 macOS 기준입니다. Windows에서는 `.venv/bin/python` 대신 `.venv\Scripts\python`을 씁니다.

## 사용 방법

### 1. stealth 접속 샘플

```bash
.venv/bin/python stealth_visit.py                         # 기본 URL (bot.sannysoft.com)
.venv/bin/python stealth_visit.py https://example.com     # URL 지정
.venv/bin/python stealth_visit.py <url> --headless        # 창 없이 실행
.venv/bin/python stealth_visit.py <url> --profile minimal # 언어·시간대만 맞춤
.venv/bin/python stealth_visit.py <url> --proxy socks5://host:port
```

접속 후 HTTP 상태, 제목, 브라우저가 보고하는 값(User-Agent, WebGL, 화면, 언어, 시간대 등)을 출력하고
`result.png`에 전체 화면을 저장합니다.

| 옵션 | 설명 |
| --- | --- |
| `--headless` | 창 없이 실행 |
| `--profile full\|minimal` | `full`(기본): 전체 프로필, `minimal`: 언어·시간대만 |
| `--user-data-dir 폴더` | Chrome 프로필을 유지할 폴더 (쿠키, 통과한 보안 확인 보존) |
| `--warmup URL` | 대상 URL 전에 먼저 방문할 주소 |
| `--wait-human 초` | 보안 확인이 뜨면 사람이 풀 때까지 기다릴 최대 시간 (기본 300, 0이면 안 기다림) |
| `--proxy URL` | 프록시 주소 |
| `--turnstile` | Cloudflare Turnstile 위젯 클릭 처리 (pydoll 기능, 이 프로젝트에서는 실행해 보지 않음) |

### 2. 네이버 쇼핑 상품 목록 추출

```bash
# 기본: 가격비교 상품, 네이버 랭킹순, products.json 에 저장
.venv/bin/python naver_products.py "LG 그램 16인치 5060"

# 가격 필터 (서버에서 적용)
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --min-price 2000000 --max-price 3000000

# 정렬
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --sort price-asc

# 정렬 + 가격대 (받은 목록에서 가격대만 골라냄)
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --sort review-count \
    --min-price 2000000 --max-price 3000000 --local-price-filter

# 여러 페이지 (페이지당 40개)
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --pages 3

# 헤드리스, 프록시
.venv/bin/python naver_products.py "LG 그램 16인치 5060" --headless
.venv/bin/python naver_products.py "LG 그램 16인치 5060" \
    --proxy socks5://host:port --user-data-dir chrome-profile-proxy
```

| 옵션 | 설명 |
| --- | --- |
| `-o 파일` | 저장할 JSON 파일 (기본 `products.json`) |
| `--all` | 가격비교 상품만이 아니라 전체 상품 (실행해 보지 않음) |
| `--min-price`, `--max-price` | 가격 필터(원). 화면의 가격 입력란과 "가격대 검색" 버튼을 조작 |
| `--sort` | `rank`(네이버 랭킹순, 기본), `price-asc`(낮은 가격순), `price-desc`(높은 가격순), `review-count`(리뷰 많은순), `review-score`(리뷰 좋은순), `date`(등록일순) |
| `--local-price-filter` | 가격 필터를 서버가 아니라 받은 목록에서 적용. `--sort`와 가격 필터를 함께 쓸 때 필요 |
| `--pages N` | 받을 페이지 수 (기본 1, 페이지당 40개). 하단의 페이지 번호 버튼을 눌러 이어서 받음 |
| `--headless` | 창 없이 실행. 보안 확인이 뜨면 창 표시 모드로 자동 전환 |
| `--user-data-dir 폴더` | 유지할 Chrome 프로필 (기본 `chrome-profile`) |
| `--proxy URL` | 프록시 주소 |
| `--wait-human 초` | 보안 확인 대기 시간 (기본 300) |
| `--relay 방식` | 보안 확인을 사람에게 전달하는 방식: `slack`, `telegram`, `dialog`, `file`. 주지 않으면 브라우저 창에서 직접 품 |

**처음 실행할 때**는 보안 확인이 뜰 가능성이 높습니다. 창에서 한 번 풀면 `chrome-profile` 폴더에 상태가 남아
이후 실행(헤드리스 포함)은 그대로 통과했습니다.

#### 추출 방식

- 필터·정렬이 없으면 페이지에 내장된 원본 데이터(`__NEXT_DATA__`)를 읽습니다.
- 필터·정렬을 주면 화면 요소를 직접 조작하고, 그때 페이지가 호출하는 검색 API(`/api/search/all`) 응답을 읽습니다.
- 한 페이지는 40개입니다. 스크롤할 때 상품이 늘어나 보이는 것은 화면에 늦게 그려지는 것일 뿐,
  40개는 처음부터 페이지에 들어 있습니다.
- `--pages N`을 주면 맨 아래까지 스크롤한 뒤 페이지 번호 버튼을 눌러 N페이지까지 받습니다.
  중간에 막히거나 버튼이 없으면 그때까지 받은 것만 저장합니다.

#### 출력 형식

```json
{
  "query": "LG 그램 16인치 5060",
  "min_price": 2000000,
  "max_price": 3000000,
  "price_filter": "server",
  "sort": "네이버 랭킹순",
  "pages": 1,
  "url": "https://search.shopping.naver.com/search/all?query=...&productSet=model",
  "fetched_at": "2026-11-26T15:51:00+09:00",
  "total": 130,
  "received": 40,
  "count": 40,
  "products": [
    {
      "rank": 1,
      "id": "58509823828",
      "title": "LG전자 그램 노트북 프로 16ZD95U-GX56K 40.6cm(16인치) 라이젠 AI 5 16GB, 256GB",
      "is_ad": false,
      "is_catalog": true,
      "brand": "그램",
      "maker": "LG전자",
      "category": "디지털/가전 > 노트북",
      "price": 1976640,
      "currency": "KRW",
      "mall_count": 130,
      "mall_name": null,
      "lowest_malls": [{"name": "G마켓", "price": 1976640}],
      "review_count": 659,
      "score": 4.96,
      "release_date": "2026-01-14",
      "options": {"RAM용량": "16GB", "저장용량": "256GB", "색상": "에어로미늄 화이트"},
      "specs": ["40.6cm(16인치)", "1.199kg", "라이젠AI 5"],
      "image_url": "https://shopping-phinf.pstatic.net/...",
      "url": "https://search.shopping.naver.com/catalog/58509823828"
    }
  ]
}
```

- `total`: 검색 결과 전체 수, `received`: 받은 수, `count`: 저장한 수, `pages`: 요청한 페이지 수.
- `price_filter`: `server`(네이버가 전체 결과에서 거름), `local`(받은 목록에서만 거름), `null`(필터 없음).
- 가격비교 상품의 `url`은 id로 조립한 카탈로그 주소이며, 실제로 열리는지는 확인하지 않았습니다.

## 시험 내용과 결과

### 1. 핑거프린트·봇 탐지 사이트

전체 프로필(`full`, macOS M3급 + 서울)로 시험했습니다.

| 시험 | 모드 | 결과 |
| --- | --- | --- |
| bot.sannysoft.com | 창 표시 | 통과 31, 실패 0, 경고 0. Fingerprint Scanner 20개 항목 모두 `ok` |
| CreepJS | 창 표시 | "0% headless", "0% stealth". GPU·화면·음성·언어가 프로필대로 읽힘. "38% like headless" 항목 있음 |
| 스크립트 자체 출력 | 창 표시 / 헤드리스 | `webdriver: False`, 프로필 값과 일치, `HeadlessChrome` 표식 없음 |

- CreepJS의 lie 탐지 수치는 확인하지 못했습니다.
- 헤드리스에서는 sannysoft·CreepJS 결과를 확인하지 않았습니다.
- 헤드리스에서 `innerHeight`가 프로필 값(785)이 아닌 773으로 나옵니다.

### 2. 네이버 쇼핑 접속

대상: `https://search.shopping.naver.com/search/all?query=LG 그램 16인치 5060&productSet=model`

| 조건 | 결과 |
| --- | --- |
| 새 프로필로 바로 접속 | HTTP 418, "쇼핑 서비스 접속이 일시적으로 제한되었습니다" |
| 새 프로필 + 네이버 메인 먼저 방문 | HTTP 405, 보안 확인(CAPTCHA) 페이지 |
| 위 상태에서 사람이 창에서 보안 확인 통과 | HTTP 200, 상품 목록 |
| 통과한 프로필로 다시 실행 (대기 없이) | HTTP 200 |
| 통과한 프로필, 헤드리스 | HTTP 200. 창 표시 모드와 같은 40개, 같은 순서·가격 |

- 418은 첫 문서 요청에서 바로 나옵니다. 자바스크립트 실행 전이라 핑거프린트 주입과는 무관합니다.
- 정상 브라우저의 요청(HAR)과 비교하면 요청 헤더는 사실상 같았습니다. 차이는 쇼핑 페이지를 정상적으로 써 오면서
  쌓인 쿠키와, 서버가 이전 응답의 `Accept-CH`로 요청해 둔 추가 Client Hints 헤더였습니다.
  이 중 무엇이 판정에 쓰이는지는 구분하지 못했습니다.
- 통과 상태가 얼마나 오래 유지되는지는 확인하지 못했습니다.

### 3. 프록시

요청마다 출구 IP가 바뀌는 서울 지역 SOCKS4 프록시로 시험했습니다.

| 조건 | 결과 |
| --- | --- |
| 브라우저 출구 IP 확인 | 프록시 IP로 나감 (직접 연결 IP와 다름) |
| 새 프로필 첫 접속 | HTTP 405 (보안 확인) |
| 같은 프로필 두 번째 접속 | HTTP 200 (보안 확인을 풀지 않았는데 통과. 쿠키 덕인지 바뀐 출구 IP 덕인지 구분 못 함) |
| 헤드리스 | HTTP 200, 2회 연속 |
| 가격 필터 | HTTP 418로 차단 (창 표시, 헤드리스, 최소 프로필 모두) |

가격 필터는 직접 연결로 바꾸자 바로 동작했습니다. 페이지를 연 IP와 필터를 요청한 IP가 달라 막힌 것으로 보이지만,
IP가 고정되는 프록시로 확인해 본 것은 아닙니다.

### 4. 가격 필터와 정렬 (직접 연결)

| 실행 | 전체 수 | 받은 수 | 결과 |
| --- | --- | --- | --- |
| 필터 없음 | 383 | 40 | 가격·주소 누락 없음, id 중복 없음 |
| 200만~300만 원, 창 표시 | 130 | 40 | 2,018,790 ~ 2,899,000원. 범위 밖 0 |
| 최고 220만 원만, 헤드리스 | 249 | 40 | 1,261,000 ~ 2,199,000원. 범위 밖 0 |
| 낮은 가격순, 창 표시 | 120 | 40 | 가격 오름차순 |
| 리뷰 많은순, 헤드리스 | 290 | 40 | 리뷰 수 내림차순 |
| 리뷰 많은순 + 200만~300만 원 로컬 필터, 헤드리스 | 290 | 40 | 13개 저장. 범위 밖 0, 정렬 유지 |

- `price-desc`, `review-score`, `date` 정렬은 같은 코드 경로지만 실행해 보지 않았습니다.
- 정렬을 바꾸면 검색 결과 전체 수가 달라집니다.
- 주소에 `minPrice`/`maxPrice`를 직접 붙여 여는 방식은 프록시에서 한 번 시도했고 HTTP 418이어서 쓰지 않았습니다.

#### 가격 필터와 정렬을 서버에서 함께 쓸 수 없음

한 페이지에서 두 번째 조작을 하면 그 요청이 HTTP 418로 차단됩니다. 필터 후 정렬, 5초 간격을 둔 필터 후 정렬,
정렬 후 필터를 각각 시도했고 모두 두 번째 요청에서 막혔습니다. 원인은 파악하지 못했습니다.

그래서 두 옵션을 같이 주면 오류로 안내합니다. 둘 다 필요하면 `--local-price-filter`로 정렬된 목록을 받은 뒤
가격대만 골라냅니다. 이 방식은 받은 40개 안에서만 거르므로 서버 필터 결과보다 적습니다
(위 예: 서버 필터 130개, 로컬 필터 13개).

### 5. 보안 확인 대기와 헤드리스 자동 전환

새 프로필로 `naver_products.py --headless`를 실행해 실제 보안 확인으로 확인했습니다.

1. 헤드리스에서 HTTP 405 보안 확인을 감지
2. 같은 프로필을 창 표시 모드로 다시 열고, 알림을 보낸 뒤 대기
3. 사람이 창에서 푼 뒤 HTTP 200으로 바뀐 것을 감지하고 상품 40개를 추출

입력란이 없는 접속 제한 페이지(HTTP 418)는 사람이 풀 수 없으므로 기다리지 않고 끝내도록 했는데,
이 구분은 실제 418 페이지로는 시험하지 않았습니다.

### 6. 메신저로 보안 확인 전달 (Slack)

| 시험 | 결과 |
| --- | --- |
| 가짜 서버 검증 (`tests/relay_mock_test.py`) | Telegram·Slack 요청 형태, 사람의 답만 골라 받기, 잠금 순서 통과 |
| Slack 연결 시험 (`human_relay.py slack`) | 메시지 전송, 이미지 업로드, 스레드 답글 읽기, 결과 표시 동작 |
| 새 프로필 + `--headless --relay slack` | HTTP 405 → Slack 으로 화면 전달 → 스레드에 적은 답을 입력·제출 → 한 번에 통과, 40개 추출 |

- 사람이 창에서 직접 입력하지 않고, 받은 답을 스크립트가 입력해도 통과했습니다.
- 헤드리스 상태에서 창 전환 없이 끝까지 처리됐습니다.
- Slack 봇에는 `chat:write`, `files:write`, `channels:history`(비공개 채널은 `groups:history`) 권한이 모두 필요합니다.
  하나라도 없으면 `missing_scope` 오류와 함께 필요한 권한 이름이 출력됩니다. 권한을 추가한 뒤에는 앱을 재설치해야 적용됩니다.
- 확인하지 못한 것: 오답 후 재시도, 답이 늦게 왔을 때 문제가 유효한지, 여러 인스턴스에서 동시에 발생했을 때의
  줄 세우기(가짜 서버 시험으로만 확인), Telegram 실제 연동.

### 7. 여러 페이지 (직접 연결, 헤드리스)

| 실행 | 전체 수 | 받은 수 | 결과 |
| --- | --- | --- | --- |
| `--pages 3` | 383 | 120 | 순위 1~120 연속, id 중복 0, 가격 누락 0 |
| 200만~300만 원 + `--pages 2` | 130 | 80 | 범위 밖 0, id 중복 0 |
| 낮은 가격순 + `--pages 2` | 120 | 80 | 두 페이지에 걸쳐 가격 오름차순, id 중복 0 |

- 가격 필터와 정렬을 이어서 했을 때와 달리, 페이지 이동은 연속 요청에서도 막히지 않았습니다.
  페이지 이동 전에 매번 맨 아래까지 스크롤한다는 점이 다르지만, 그것이 이유인지는 확인하지 않았습니다.
- 4페이지 이상과 프록시 경유는 시험하지 않았습니다.
- 실행 중 `Command timeout: ... timeout=5s` 경고가 가끔 찍히지만 결과에는 영향이 없었습니다.

### 8. Windows

Mac에서 확인한 것까지입니다.

- Windows 프로필을 Mac의 Chrome에 적용해 값이 의도대로 읽히는 것을 확인 (Windows UA, `Win32`, RTX 3060, 1920x1080)
- OS를 Windows로 흉내 내어 프로필 선택, 창 크기, 경고음 호출 분기를 확인

실제 Windows에서의 Chrome 실행, 네이버 접속 통과 여부, 경고음, 콘솔 한글 출력은 확인하지 않았습니다.

### 9. Docker 시험 (Linux 컨테이너)

```bash
docker build -t naver-pydoll .
docker run --rm -v "$PWD/docker-data:/data" naver-pydoll "LG 그램 16인치 5060"
```

Apple Silicon Mac 의 Docker(Linux arm64, Chromium 156)에서 시험했습니다.

| 시험 | 결과 |
| --- | --- |
| 이미지 빌드, 컨테이너 안에서 브라우저 실행 | 성공 |
| 컨테이너 안 핑거프린트 적용 (example.com) | Linux 프로필 값대로 읽힘, `webdriver: False` |
| 컨테이너에서 네이버 가격비교 접속 (새 프로필) | **HTTP 418 차단** (보안 확인 화면이 아니라 접속 제한) |
| 같은 시각·같은 IP, Mac 새 프로필 | HTTP 405 (보안 확인) |
| 같은 시각·같은 IP, Mac 통과한 프로필 | HTTP 200 |
| Mac 의 Chrome 에 Linux 프로필만 적용 (새 프로필) | **HTTP 418 차단** |

마지막 줄이 원인을 가립니다. 같은 기기, 같은 IP, 같은 Chrome 에서 브라우저 신원만 Linux 로 바꾸자
보안 확인 단계 없이 바로 차단됐습니다. 요청에서 달라진 것은 User-Agent(`X11; Linux x86_64`)와
`sec-ch-ua-platform`(`"Linux"`)뿐입니다. 즉 **Linux 데스크톱 신원으로는 사람이 풀 기회조차 없이 막힙니다.**
각 조건은 한 번씩만 시험했습니다.

따라서 지금의 Docker 이미지로는 상품 목록을 받을 수 없습니다. 메신저 전달(`--relay`)은 보안 확인 화면이
나와야 동작하므로 이 경우에는 쓰이지 않습니다. 컨테이너용 전달 방식(`--relay file`)과 호스트의
`human_relay.py watch` 는 만들어 두었지만, 보안 확인이 나오지 않아 컨테이너에서는 실행되지 않았습니다.

## 알려진 문제와 주의 사항

- **Linux 에서는 쓸 수 없습니다.** Linux 신원은 네이버 가격비교에서 바로 차단(HTTP 418)됩니다 (시험 9번).
  Docker 이미지는 시험 기록용으로 남겨 두었습니다. 실제 수집은 macOS 또는 Windows 기기에서 해야 합니다.

- **pydoll 3.0.1의 새 프로필 폴더 버그**: 새 `--user-data-dir` 폴더로 처음 실행하면 종료 단계에서 없는
  `Preferences.backup`을 복원하려다 예외가 나고, Chrome 프로세스가 남아 다음 실행이 실패합니다.
  이 프로젝트는 빈 `Preferences`를 미리 만들어 우회합니다 (`stealth_visit.py`의 `build_options`).
- **같은 프로필로 Chrome이 이미 떠 있으면** "The browser exited with code 0" 오류가 납니다. 그 Chrome을 닫고 다시 실행하세요.
- **프로필 폴더는 OS 사이에 옮길 수 없습니다.** 쿠키가 OS별로 암호화됩니다.
- **프록시 지역**: 프록시 IP의 지역이 `fingerprints.py`의 언어·시간대·위치와 맞아야 합니다.
- **Windows 한글 폰트**: Windows 프로필은 굴림·돋움·바탕·궁서·맑은 고딕이 설치된 한국어 Windows를 전제로 합니다.
- **요청 빈도**: 짧은 시간에 요청이 많으면 IP 단위로 접속이 제한됩니다. 반복 실행은 간격을 두세요.
- **이용 약관**: 자동화된 접근은 대상 사이트의 이용 약관을 확인하고 사용하세요. 상품 목록 데이터만 필요하다면
  [네이버 쇼핑 검색 Open API](https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md)가 공식 경로입니다.
