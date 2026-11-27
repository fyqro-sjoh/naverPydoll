"""네이버 쇼핑 검색 결과의 상품 목록을 JSON 으로 저장한다.

실행 (macOS 기준. Windows 에서는 .venv/bin/python 대신 .venv\\Scripts\\python 을 쓴다):
    .venv/bin/python naver_products.py "LG 그램 16인치 5060"
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" --all          # 가격비교 외 전체 상품
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" -o gram.json
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" --min-price 2000000 --max-price 3000000
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" --sort price-asc
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" --pages 3            # 3페이지(120개)까지
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" --sort review-count \
        --min-price 2000000 --max-price 3000000 --local-price-filter
    .venv/bin/python naver_products.py "LG 그램 16인치 5060" \\
        --proxy socks4://host:port --user-data-dir chrome-profile-proxy

동작:
    stealth_visit.py 의 접속 흐름(핑거프린트 + 네이버 메인 경유 + 유지되는 프로필)으로 페이지를 열고,
    페이지에 내장된 데이터(__NEXT_DATA__)에서 상품 목록을 읽는다. 화면을 긁는 것이 아니라
    서버가 내려준 원본 데이터라 값이 정확하다. 한 페이지는 40개이고, --pages N 을 주면
    하단의 페이지 번호 버튼을 눌러 N 페이지까지 이어서 받는다.

    --min-price / --max-price / --sort 를 주면 화면의 가격 입력란과 정렬 버튼을 직접 조작한 뒤,
    그때 페이지가 호출하는 검색 API 응답에서 목록을 읽는다. 가격 필터와 정렬은 서버에서 함께
    적용할 수 없다 (한 페이지에서 두 번째 조작은 네이버가 차단한다). 둘 다 필요하면
    --local-price-filter 로 정렬된 목록을 받은 뒤 가격대만 골라낸다. 이때는 받은 목록(첫 화면분)
    안에서만 걸러지므로 서버 필터 결과보다 적을 수 있다. 이 요청은 요청마다 출구 IP 가
    바뀌는 프록시에서는 차단되므로, 프록시 없이 쓰거나 IP 가 고정되는 프록시를 써야 한다.

    --relay telegram|slack 을 주면 보안 확인 화면을 메신저로 보내고, 사람이 답장한 답을 입력해
    제출한다 (설정은 human_relay.py 참고). 창 앞에 사람이 없어도 되고 헤드리스에서도 동작한다.

    --relay 가 없으면: 보안 확인(CAPTCHA)이 뜨면 자동으로 풀지 않고, 알림을 보낸 뒤 브라우저 창에서 사람이 풀 때까지
    기다린다. 헤드리스 실행 중이면 같은 프로필을 창 표시 모드로 다시 열어 풀게 하고 이어서 추출한다.
"""

import argparse
import asyncio
import base64
import binascii
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from human_relay import RELAYS, RelayError, RelayLock, create_relay
from stealth_visit import launch, needs_human, open_page, setup_console

SEARCH_URL = 'https://search.shopping.naver.com/search/all?query={query}'
CATALOG_URL = 'https://search.shopping.naver.com/catalog/{id}'
SEARCH_API_PATH = '/api/search/all'  # 필터를 적용할 때 페이지가 호출하는 검색 API
FILTER_TIMEOUT = 20  # 필터 적용 후 API 응답을 기다릴 최대 시간(초)
# --sort 값 → 화면 정렬 버튼의 이름. 'rank'(네이버 랭킹순)는 기본 정렬이라 누르지 않는다.
SORT_LABELS = {
    'rank': '네이버 랭킹순',
    'price-asc': '낮은 가격순',
    'price-desc': '높은 가격순',
    'review-count': '리뷰 많은순',
    'review-score': '리뷰 좋은순',
    'date': '등록일순',
}
SCROLL_MAX_STEPS = 25  # 맨 아래까지 스크롤할 때의 최대 단계 수
AT_BOTTOM_JS = 'window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 50'
RELAY_MAX_ATTEMPTS = 3  # 메신저로 보안 확인을 다시 보내는 최대 횟수
RELAY_REFRESH_AFTER = 60  # 차례를 이 시간(초) 넘게 기다렸으면 새 문제를 받아서 보낸다
NEXT_DATA_JS = "document.getElementById('__NEXT_DATA__')?.textContent ?? ''"


def build_url(query: str, model_only: bool) -> str:
    url = SEARCH_URL.format(query=quote(query))
    # productSet=model: 여러 판매처를 묶은 "가격비교" 상품만 보여 준다.
    return url + '&productSet=model' if model_only else url


def to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def split_bar(value: str | None) -> list[str]:
    return [part for part in (value or '').split('|') if part]


def parse_product(item: dict) -> dict:
    """네이버의 원본 상품 항목(필드 200여 개)에서 쓸모 있는 값만 골라 정리한다."""
    is_catalog = item.get('mallId') == 'naver_model'  # 가격비교(카탈로그) 상품
    open_date = item.get('openDate') or ''
    categories = [item.get(f'category{level}Name') for level in range(1, 5)]
    return {
        'rank': to_int(item.get('rank')),
        'id': item.get('id'),
        'title': item.get('productTitle') or item.get('productName'),
        'is_ad': bool(item.get('adId')),
        'is_catalog': is_catalog,
        'brand': item.get('brand') or None,
        'maker': item.get('maker') or None,
        'category': ' > '.join(name for name in categories if name),
        'price': to_int(item.get('lowPrice') or item.get('price')),
        'currency': item.get('priceUnit') or 'KRW',
        # 가격비교 상품은 판매처 수, 일반 상품은 판매처 이름이 들어 있다.
        'mall_count': to_int(item.get('mallCount')) if is_catalog else None,
        'mall_name': None if is_catalog else item.get('mallName') or None,
        'lowest_malls': [
            {'name': mall.get('name'), 'price': to_int(mall.get('price'))}
            for mall in item.get('lowMallList') or []
        ],
        'review_count': to_int(item.get('reviewCount')),
        'score': to_float(item.get('scoreInfo')),
        'release_date': (
            f'{open_date[:4]}-{open_date[4:6]}-{open_date[6:8]}' if len(open_date) >= 8 else None
        ),
        'options': dict(
            zip(
                split_bar(item.get('stdPrchOptNames')),
                split_bar(item.get('stdPrchOptValNames')),
            )
        ),
        'specs': split_bar(item.get('characterValue')),
        'image_url': item.get('imageUrl') or None,
        # 가격비교 상품은 카탈로그 주소를 id 로 조립하고, 일반 상품은 판매처 상품 주소를 쓴다.
        'url': CATALOG_URL.format(id=item['id']) if is_catalog else item.get('mallProductUrl'),
    }


def parse_products(next_data: dict) -> tuple[int | None, list[dict]]:
    """(검색 결과 전체 수, 이 페이지의 상품 목록)"""
    composite = next_data['props']['pageProps']['compositeList']
    products = [
        parse_product(entry['item'])
        for entry in composite.get('list', [])
        if entry.get('type') == 'product'
    ]
    return to_int(composite.get('total')), products


def parse_api_products(api_data: dict) -> tuple[int | None, list[dict]]:
    """필터 적용 시 페이지가 호출하는 검색 API 응답에서 (전체 수, 상품 목록)을 읽는다."""
    result = api_data['shoppingResult']
    return to_int(result.get('total')), [parse_product(item) for item in result['products']]


def response_json(entry: dict) -> dict:
    content = entry['response']['content']
    text = content.get('text') or ''
    if content.get('encoding') == 'base64':
        text = base64.b64decode(text).decode('utf-8')
    return json.loads(text)


def filter_by_price(
    products: list[dict], min_price: int | None, max_price: int | None
) -> list[dict]:
    """받은 목록에서 가격대에 맞는 상품만 남긴다 (서버 필터와 달리 받은 범위 안에서만 걸러진다)."""
    return [
        product
        for product in products
        if product['price'] is not None
        and (min_price is None or product['price'] >= min_price)
        and (max_price is None or product['price'] <= max_price)
    ]


class SearchApiError(SystemExit):
    """화면 조작 뒤 검색 API 응답을 받지 못했거나 차단됐다. 잡지 않으면 메시지를 내고 종료한다."""


async def capture_search_api(tab, action, what: str) -> dict:
    """화면 조작(action)을 실행하고, 그때 페이지가 호출하는 검색 API 응답(JSON)을 돌려준다.

    필터·정렬은 페이지를 새로 열지 않고 API 만 다시 부르므로 __NEXT_DATA__ 는 갱신되지 않는다.
    주소에 파라미터를 직접 붙여 여는 방식은 서버가 418 로 막아서 쓰지 않는다.
    """
    async with tab.request.record() as capture:
        await action()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + FILTER_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(0.5)
            calls = [e for e in capture.entries if SEARCH_API_PATH in e['request']['url']]
            if calls and calls[-1]['response'].get('status'):
                break
        else:
            raise SearchApiError(f'{what}을(를) 적용했지만 검색 API 응답을 받지 못했습니다.')

    status = calls[-1]['response']['status']
    if status >= 400:
        raise SearchApiError(
            f'{what} 요청이 차단됐습니다 (HTTP {status}). '
            '요청마다 출구 IP 가 바뀌는 프록시를 쓰고 있다면 프록시 없이 실행하거나 '
            'IP 가 고정되는 프록시를 쓰세요. 그렇지 않다면 잠시 뒤 다시 시도하세요.'
        )
    return response_json(calls[-1])


async def apply_price_filter(tab, min_price: int | None, max_price: int | None) -> dict:
    """화면의 가격 입력란에 값을 넣고 "가격대 검색"을 누른다."""

    async def action():
        for element_id, price in (
            ('search-filter-min-price', min_price),
            ('search-filter-max-price', max_price),
        ):
            if price is None:
                continue
            box = await tab.find(id=element_id, timeout=10)
            await box.click(humanize=True)
            await box.type_text(str(price), humanize=True)

        button = await tab.find(tag_name='button', text='가격대 검색', timeout=10)
        await button.click(humanize=True)

    return await capture_search_api(tab, action, '가격 필터')


async def apply_sort(tab, sort: str) -> dict:
    """정렬 구역에서 원하는 정렬 버튼을 누른다."""
    label = SORT_LABELS[sort]

    async def action():
        # 클래스명은 배포마다 바뀔 수 있어, 정렬 버튼에 붙은 데이터 속성으로 찾는다.
        button = await tab.query(
            f'a[data-shp-area="flt_cor.sort"][data-shp-contents-id="{label}"]', timeout=10
        )
        await button.click(humanize=True)

    return await capture_search_api(tab, action, f'정렬({label})')


async def scroll_to_bottom(tab) -> None:
    """페이지 맨 아래까지 사람처럼 나눠서 스크롤한다. 목록이 스크롤에 따라 그려져 높이가 늘어난다."""
    for _ in range(SCROLL_MAX_STEPS):
        await tab.execute_script('window.scrollBy({top: 1400, behavior: "smooth"})')
        await asyncio.sleep(0.9)
        response = await tab.execute_script(AT_BOTTOM_JS, return_by_value=True)
        if response['result']['result'].get('value'):
            return


async def load_page(tab, page: int) -> list[dict] | None:
    """하단의 페이지 번호 버튼을 눌러 해당 페이지의 상품 목록을 받는다. 못 받으면 None."""

    async def action():
        await scroll_to_bottom(tab)
        # 클래스명은 배포마다 바뀔 수 있어, 페이지 버튼에 붙은 데이터 속성으로 찾는다.
        button = await tab.query(
            f'a[data-shp-area="prd_pgn.pgn"][data-shp-contents-id="{page}"]',
            timeout=5,
            raise_exc=False,
        )
        if button is None:
            raise SearchApiError(f'{page}페이지 버튼이 없습니다 (마지막 페이지를 지났을 수 있음).')
        await button.click(humanize=True)

    try:
        api_data = await capture_search_api(tab, action, f'{page}페이지')
    except SearchApiError as error:
        # 앞 페이지까지 받은 것은 살린다.
        print(f'  ※ {error} 앞 페이지까지만 저장합니다.', flush=True)
        return None
    return parse_api_products(api_data)[1]


CAPTCHA_STATE_JS = """JSON.stringify({
    captcha: !!document.getElementById('rcpt_img'),
    loaded: !!document.getElementById('__NEXT_DATA__'),
    question: (document.getElementById('rcpt_info')?.innerText ?? '').trim(),
})"""


async def captcha_state(tab) -> dict:
    """보안 확인 화면인지, 상품 페이지가 열렸는지, 질문 문구는 무엇인지."""
    try:
        response = await tab.execute_script(CAPTCHA_STATE_JS, return_by_value=True)
        return json.loads(response['result']['result']['value'])
    except (KeyError, TypeError, ValueError, TimeoutError):
        # 통과 직후 페이지가 넘어가는 중이면 값을 못 읽는다. 다음 확인에서 다시 본다.
        return {'captcha': False, 'loaded': False, 'question': ''}


async def solve_with_relay(tab, relay, label: str, timeout: int) -> bool:
    """보안 확인 화면을 메신저로 사람에게 보내고, 받은 답을 입력해 제출한다. 통과하면 True.

    답은 사람이 낸다. 이 함수는 화면을 전달하고 받은 답을 그대로 입력할 뿐이다.
    """
    for attempt in range(1, RELAY_MAX_ATTEMPTS + 1):
        # 여러 인스턴스가 동시에 걸려도 메신저에는 한 번에 한 건만 나간다.
        async with RelayLock() as lock:
            if lock.waited > RELAY_REFRESH_AFTER:
                # 차례를 오래 기다렸으면 문제가 만료됐을 수 있어 새 문제를 받는다.
                reload_button = await tab.query('#rcpt_reload', timeout=5, raise_exc=False)
                if reload_button is not None:
                    await reload_button.click(humanize=True)
                    await asyncio.sleep(2)

            state = await captcha_state(tab)
            if not state['captcha']:
                return state['loaded']
            try:
                shot = base64.b64decode(await tab.take_screenshot(as_base64=True))
            except (binascii.Error, TypeError) as error:
                raise SystemExit(f'보안 확인 화면을 캡처하지 못했습니다: {error}') from error

            caption = (
                f'[{label}] 보안 확인 ({attempt}/{RELAY_MAX_ATTEMPTS})\n'
                f'{state["question"]}\n'
                '이 메시지에 답장으로 정답만 보내 주세요.'
            )
            handle = await relay.send(shot, caption)
            print(f'  보안 확인을 {relay.name} 로 보냈습니다. 답을 기다립니다...', flush=True)
            answer = await relay.wait_answer(handle, timeout)
            if answer is None:
                await relay.update(handle, '시간 초과: 답을 받지 못해 작업을 중단했습니다.')
                return False

            box = await tab.query('input[id^="rcpt_answer"]', timeout=10)
            await box.click(humanize=True)
            await box.type_text(answer, humanize=True)
            confirm = await tab.query('#cpt_confirm', timeout=10)
            await confirm.click(humanize=True)

            # 통과하면 상품 페이지가 열리고, 틀리면 보안 확인 화면에 새 문제가 나온다.
            passed = False
            for _ in range(20):
                await asyncio.sleep(1)
                state = await captcha_state(tab)
                if state['loaded'] and not state['captcha']:
                    passed = True
                    break
            if passed:
                await relay.update(handle, '통과했습니다.')
                return True
            await relay.update(handle, '통과하지 못했습니다. 새 문제를 다시 보냅니다.')
    return False


class NeedsHuman(Exception):
    """헤드리스 실행 중 사람이 풀어야 하는 보안 확인이 떴다."""


async def fetch_with_human_fallback(url: str, *, headless: bool, **options):
    """헤드리스에서 보안 확인이 뜨면 창 표시 모드로 다시 열어 사람이 풀게 한 뒤 이어서 추출한다."""
    try:
        return await fetch(url, headless=headless, **options)
    except NeedsHuman:
        print('보안 확인이 떠서 창 표시 모드로 다시 엽니다. 창에서 직접 풀어 주세요.', flush=True)
        return await fetch(url, headless=False, **options)


async def fetch(
    url: str,
    *,
    headless: bool,
    user_data_dir: str,
    proxy: str | None,
    wait_human: int,
    min_price: int | None = None,
    max_price: int | None = None,
    sort: str = 'rank',
    pages: int = 1,
    relay=None,
) -> tuple[int | None, list[dict]]:
    async with launch(headless, user_data_dir, proxy) as browser:
        tab, status = await open_page(
            browser,
            url,
            headless=headless,
            warmup='https://www.naver.com/',
            # 메신저로 전달할 때는 창에서 기다리지 않는다 (헤드리스에서도 그대로 처리된다).
            wait_human=0 if relay else wait_human,
        )
        if relay and (status is None or status >= 400) and await needs_human(tab):
            label = Path(user_data_dir).name
            try:
                solved = await solve_with_relay(tab, relay, label, wait_human)
            except RelayError as error:
                raise SystemExit(f'메신저 전달에 실패했습니다: {error}') from error
            if not solved:
                raise SystemExit('보안 확인을 통과하지 못했습니다.')
            status = 200
            print('  보안 확인을 통과했습니다.', flush=True)
        if status is None or status >= 400:
            if headless and wait_human > 0 and await needs_human(tab):
                # 헤드리스에는 창이 없어 사람이 보안 확인을 풀 수 없다.
                # 같은 프로필을 창 표시 모드로 다시 열어 사람이 풀게 한다 (main 에서 재시도).
                raise NeedsHuman()
            raise SystemExit(f'상품 목록 페이지를 열지 못했습니다 (HTTP {status}).')

        # 가격 필터와 정렬은 한 번에 하나만 적용한다 (main 에서 함께 쓰는 것을 막는다).
        # 한 페이지에서 두 번째 조작의 API 요청은 순서·간격과 무관하게 418 로 차단됐다.
        api_data = None
        if min_price is not None or max_price is not None:
            api_data = await apply_price_filter(tab, min_price, max_price)
        elif sort != 'rank':
            api_data = await apply_sort(tab, sort)
        if api_data is not None:
            total, products = parse_api_products(api_data)
        else:
            response = await tab.execute_script(NEXT_DATA_JS, return_by_value=True)
            raw = response['result']['result'].get('value') or ''
            if not raw:
                raise SystemExit(
                    '페이지에서 상품 데이터(__NEXT_DATA__)를 찾지 못했습니다.\n'
                    f'  현재 주소: {await tab.current_url()}\n  제목: {await tab.title()}'
                )
            total, products = parse_products(json.loads(raw))

        # 2페이지부터는 하단의 페이지 번호 버튼을 눌러 받는다.
        seen = {product['id'] for product in products}
        for page in range(2, pages + 1):
            if total is not None and len(products) >= total:
                break  # 검색 결과를 이미 다 받았다
            more = await load_page(tab, page)
            if more is None:
                break
            fresh = [product for product in more if product['id'] not in seen]
            seen.update(product['id'] for product in fresh)
            products += fresh
            print(f'  {page}페이지: {len(fresh)}개 (누적 {len(products)}개)', flush=True)
        return total, products


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(description='네이버 쇼핑 상품 목록을 JSON 으로 저장')
    parser.add_argument('query', help='검색어 (예: "LG 그램 16인치 5060")')
    parser.add_argument('-o', '--output', default='products.json', help='저장할 JSON 파일')
    parser.add_argument('--all', action='store_true', help='가격비교 상품만이 아니라 전체 상품')
    parser.add_argument('--min-price', type=int, metavar='WON', help='최저가격 필터 (원)')
    parser.add_argument('--max-price', type=int, metavar='WON', help='최고가격 필터 (원)')
    parser.add_argument(
        '--local-price-filter',
        action='store_true',
        help='가격 필터를 서버가 아니라 받은 목록에서 적용 (--sort 와 함께 쓸 때 필요)',
    )
    parser.add_argument(
        '--sort',
        choices=list(SORT_LABELS),
        default='rank',
        help='정렬: ' + ', '.join(f'{key}={label}' for key, label in SORT_LABELS.items()),
    )
    parser.add_argument(
        '--pages', type=int, default=1, metavar='N', help='받을 페이지 수 (기본 1, 페이지당 40개)'
    )
    parser.add_argument('--headless', action='store_true', help='창 없이 실행')
    parser.add_argument('--user-data-dir', default='chrome-profile', help='유지할 Chrome 프로필')
    parser.add_argument('--proxy', metavar='URL', help='프록시 주소 (예: socks5://host:port)')
    parser.add_argument('--wait-human', type=int, default=300, metavar='SECONDS')
    parser.add_argument(
        '--relay',
        choices=RELAYS,
        help='보안 확인을 메신저로 사람에게 보내 답을 받음 (human_relay.py 참고). '
        '주지 않으면 브라우저 창에서 직접 푼다',
    )
    args = parser.parse_args()
    if args.min_price is not None and args.min_price < 0:
        parser.error('--min-price 는 0 이상이어야 합니다.')
    if args.max_price is not None and args.max_price < 0:
        parser.error('--max-price 는 0 이상이어야 합니다.')
    if None not in (args.min_price, args.max_price) and args.min_price > args.max_price:
        parser.error('--min-price 가 --max-price 보다 큽니다.')
    if args.pages < 1:
        parser.error('--pages 는 1 이상이어야 합니다.')
    has_price = args.min_price is not None or args.max_price is not None
    if args.local_price_filter and not has_price:
        parser.error('--local-price-filter 는 --min-price 나 --max-price 와 함께 써야 합니다.')
    if args.sort != 'rank' and has_price and not args.local_price_filter:
        parser.error(
            '가격 필터와 --sort 는 서버에서 함께 적용할 수 없습니다 '
            '(한 페이지에서 두 번째 조작은 네이버가 차단합니다). '
            '--local-price-filter 를 붙이면 정렬된 목록을 받은 뒤 가격대만 골라냅니다.'
        )

    url = build_url(args.query, model_only=not args.all)
    total, products = asyncio.run(
        fetch_with_human_fallback(
            url,
            headless=args.headless,
            user_data_dir=args.user_data_dir,
            proxy=args.proxy,
            wait_human=args.wait_human,
            # 로컬 필터일 때는 브라우저에서 가격 입력란을 건드리지 않는다.
            min_price=None if args.local_price_filter else args.min_price,
            max_price=None if args.local_price_filter else args.max_price,
            sort=args.sort,
            pages=args.pages,
            relay=create_relay(args.relay) if args.relay else None,
        )
    )
    received = len(products)
    if args.local_price_filter:
        products = filter_by_price(products, args.min_price, args.max_price)

    result = {
        'query': args.query,
        'min_price': args.min_price,
        'max_price': args.max_price,
        # server: 네이버가 전체 결과에서 거름 / local: 받은 목록(첫 화면분)에서만 거름
        'price_filter': ('local' if args.local_price_filter else 'server') if has_price else None,
        'sort': SORT_LABELS[args.sort],
        'pages': args.pages,
        'url': url,
        'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'total': total,
        'received': received,
        'count': len(products),
        'products': products,
    }
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    if args.local_price_filter:
        print(
            f'검색 결과 전체 {total}개 중 {received}개를 받아, '
            f'가격대에 맞는 {len(products)}개를 {args.output} 에 저장했습니다.'
        )
        if received and len(products) in (0, received) and args.sort.startswith('price-'):
            print(
                '  ※ 받은 목록이 전부 가격대 안이거나 전부 밖입니다. '
                '가격대에 맞는 상품이 받은 범위 밖에 더 있을 수 있습니다.'
            )
    else:
        print(f'검색 결과 전체 {total}개 중 {len(products)}개를 {args.output} 에 저장했습니다.')
    if not products:
        sys.exit(1)


if __name__ == '__main__':
    main()
