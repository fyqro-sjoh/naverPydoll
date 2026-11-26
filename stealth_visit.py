"""Pydoll stealth URL 접속 샘플 (pydoll-python 3.x, async API).

실행 (macOS 기준. Windows 에서는 .venv/bin/python 대신 .venv\\Scripts\\python 을 쓴다):
    .venv/bin/python stealth_visit.py                       # 기본 URL
    .venv/bin/python stealth_visit.py https://example.com   # URL 지정
    .venv/bin/python stealth_visit.py <url> --headless      # 창 없이 실행
    .venv/bin/python stealth_visit.py <url> --turnstile     # Cloudflare Turnstile 처리
    .venv/bin/python stealth_visit.py <url> --profile minimal   # 언어·시간대만 맞춤

    # 쿠키·방문 이력을 보는 사이트(예: 네이버 쇼핑): 프로필을 유지하고, 메인을 먼저 거치고,
    # 보안 확인(CAPTCHA)이 뜨면 사람이 창에서 직접 풀 때까지 기다린다 (기본 최대 300초).
    .venv/bin/python stealth_visit.py <url> --user-data-dir chrome-profile \
        --warmup https://www.naver.com/

    .venv/bin/python stealth_visit.py <url> --proxy socks5://host:port   # 프록시 경유

Stealth 구성 (3단계):
    1. 기본 구조  : WebDriver 없이 CDP로 직접 연결 → navigator.webdriver,
                    --enable-automation 같은 자동화 흔적이 처음부터 없음.
    2. 브라우저 옵션: WebRTC IP 유출 차단, Accept-Language 정렬, 알림/팝업 차단.
    3. 핑거프린트 : tab.apply_fingerprint() 로 UA·Client Hints·WebGL·화면·폰트·
                    언어·시간대를 하나의 일관된 신원으로 맞춤 (fingerprints.py).
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from pydoll import Chrome, ChromiumOptions

from fingerprints import (
    LANGUAGES,
    build_full_profile,
    build_minimal_profile,
    window_size,
)

DEFAULT_URL = 'https://bot.sannysoft.com/'

# 접속 후 브라우저가 실제로 무엇을 보고하는지 확인하는 스크립트
STEALTH_CHECK_JS = """
(() => {
    const gl = document.createElement('canvas').getContext('webgl');
    const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
    return JSON.stringify({
        webdriver: navigator.webdriver,
        userAgent: navigator.userAgent,
        brands: (navigator.userAgentData?.brands ?? []).map(b => b.brand + ' ' + b.version),
        platform: navigator.platform,
        languages: navigator.languages,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        webgl: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : null,
        screen: `${screen.width}x${screen.height} @${devicePixelRatio}x`,
        window: `${outerWidth}x${outerHeight} (inner ${innerWidth}x${innerHeight})`,
        cores: navigator.hardwareConcurrency,
        memoryGB: navigator.deviceMemory,
    });
})()
"""


def build_options(
    headless: bool, user_data_dir: str | None = None, proxy: str | None = None
) -> ChromiumOptions:
    options = ChromiumOptions()
    options.headless = headless
    # 컨테이너 등 Chrome 이 표준 위치에 없는 환경: CHROME_BINARY 로 실행 파일을 지정한다.
    if os.environ.get('CHROME_BINARY'):
        options.binary_location = os.environ['CHROME_BINARY']
    # Docker 컨테이너는 Chrome 의 샌드박스를 만들 권한이 없고 /dev/shm 도 작다.
    if os.environ.get('CHROME_NO_SANDBOX') == '1':
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
    if user_data_dir:
        # 프로필을 디스크에 유지: 쿠키·Client Hints 설정·사람이 통과한 보안 확인이 다음 실행에도 남는다.
        # 지정하지 않으면 매번 빈 임시 프로필로 시작한다 (처음 방문하는 브라우저처럼 보임).
        profile_dir = Path(user_data_dir).resolve()
        options.add_argument(f'--user-data-dir={profile_dir}')
        # pydoll 3.0.1 은 새 프로필 폴더에서 종료할 때 없는 Preferences.backup 을 복원하려다
        # 예외가 나고, 그 바람에 Chrome 을 끄지 못해 프로세스가 남는다 (다음 실행도 실패).
        # 빈 Preferences 를 미리 만들어 두면 백업이 정상적으로 생긴다.
        preferences = profile_dir / 'Default' / 'Preferences'
        if not preferences.exists():
            preferences.parent.mkdir(parents=True, exist_ok=True)
            preferences.write_text('{}', encoding='utf-8')
    options.webrtc_leak_protection = True  # 프록시 사용 시 실제 IP가 WebRTC로 새는 것을 방지
    options.set_accept_languages(','.join(LANGUAGES))  # HTTP Accept-Language 헤더
    options.block_notifications = True
    options.block_popups = True
    options.password_manager_enabled = False
    width, height = window_size()
    options.add_argument(f'--window-size={width},{height}')
    if proxy:
        # 프록시 IP 의 지역은 fingerprints.py 의 언어·시간대·위치와 맞아야 한다.
        # 예: http://host:port, socks5://host:port, socks4://host:port
        options.add_argument(f'--proxy-server={proxy}')
    return options


async def real_chrome_version(browser: Chrome) -> str:
    """실제로 띄운 Chrome 의 전체 버전. 예: 'Chrome/158.0.8127.38' → '158.0.8127.38'.

    헤드리스에서는 'HeadlessChrome/158.0.8127.38' 로 오지만 '/' 뒤만 쓰므로 똑같이 처리된다.
    """
    version = await browser.get_version()
    return version['product'].split('/', 1)[1]


def document_status(entries: list, url: str) -> int | None:
    """기록된 요청 중 대상 URL 문서 요청의 마지막 HTTP 상태 코드."""
    target = url.split('#', 1)[0].rstrip('/')
    statuses = [
        e['response']['status'] for e in entries if e['request']['url'].rstrip('/') == target
    ]
    return statuses[-1] if statuses else None


# 사람이 직접 처리할 수 있는 확인 화면인지: 입력란·버튼·iframe(위젯)이 있으면 그렇다고 본다.
# 안내문과 링크만 있는 접속 제한 페이지는 기다려도 풀 수 없으므로 구분한다.
HUMAN_CHALLENGE_JS = "!!document.querySelector('input:not([type=hidden]), button, iframe')"


async def needs_human(tab) -> bool:
    """현재 페이지가 사람이 풀 수 있는 보안 확인(CAPTCHA 등) 화면인지."""
    response = await tab.execute_script(HUMAN_CHALLENGE_JS, return_by_value=True)
    return bool(response['result']['result'].get('value'))


def notify(title: str, message: str) -> None:
    """소리로 사람을 부른다. macOS 에서는 알림 센터 알림도 함께 띄운다."""
    print('\a', end='', flush=True)  # 터미널 벨 (모든 OS)
    if sys.platform == 'darwin':
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(['osascript', '-e', script], check=False, timeout=5, capture_output=True)
    elif sys.platform == 'win32':
        import winsound  # Windows 전용 표준 모듈

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)


async def wait_for_human(tab, capture, url: str, timeout: int) -> int | None:
    """사람이 브라우저 창에서 보안 확인을 마칠 때까지 기다린다. 마지막 문서 상태 코드를 돌려준다."""
    print(
        f'          → 브라우저 창에서 보안 확인을 직접 완료해 주세요. 최대 {timeout}초 기다립니다.',
        flush=True,
    )
    await tab.bring_to_front()
    notify('보안 확인 필요', '브라우저 창에서 보안 확인을 완료해 주세요.')
    status = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(2)
        # 통과 후 주소가 바뀌는 경우도 있어, 대상 URL 과 현재 URL 둘 다 본다.
        for candidate in (await tab.current_url(), url):
            status = document_status(capture.entries, candidate) or status
            if status is not None and status < 400:
                await asyncio.sleep(2)  # 페이지가 그려질 시간
                return status
    print('          → 대기 시간이 지났습니다. 보안 확인이 완료되지 않았습니다.')
    return status


async def open_page(
    browser: Chrome,
    url: str,
    *,
    headless: bool = False,
    turnstile: bool = False,
    profile: str = 'full',
    warmup: str | None = None,
    wait_human: int = 300,
):
    """핑거프린트를 적용하고 URL 을 연다. (tab, 문서의 HTTP 상태 코드) 를 돌려준다."""
    tab = await browser.start()


    if profile == 'full':
        # UA 의 Chrome 버전은 실제 바이너리와 같아야 한다 (TLS/HTTP2 지문은 위장 불가).
        # 실행 중인 OS(macOS / Windows)에 맞는 프로필이 선택된다.
        fingerprint = build_full_profile(await real_chrome_version(browser))
    else:
        fingerprint = build_minimal_profile()
        if headless:
            # 헤드리스 Chrome 은 UA 에 "HeadlessChrome" 을 넣어 스스로를 드러낸다.
            # 실제 UA 에서 그 표식만 지운다 (전체 프로필은 UA 를 직접 만들므로 불필요).
            real_ua = (await browser.get_version())['userAgent']
            fingerprint['user_agent'] = real_ua.replace('HeadlessChrome', 'Chrome')

    # 반드시 이동 "전에" 적용: 오버라이드는 새 문서가 만들어질 때마다 주입된다.
    await tab.apply_fingerprint(fingerprint)

    if warmup:
        # 사이트 메인을 먼저 방문해 쿠키를 받는다. 쿠키 없는 첫 요청을 바로 막는 사이트가 있다.
        await tab.go_to(warmup)
        await tab.mouse.move(600, 300, humanize=True)
        await asyncio.sleep(3)

    # 문서 요청의 HTTP 상태를 보려고 이동 구간의 네트워크를 기록한다.
    async with tab.request.record() as capture:
        if turnstile:
            # Turnstile 위젯이 나타나면 사람처럼 클릭하고, 통과되면 계속 진행한다.
            # (우회가 아니라 실제 클릭이므로 통과 여부는 IP 평판·핑거프린트에 달려 있다.)
            async with tab.expect_cloudflare_turnstile():
                await tab.go_to(url)
        else:
            await tab.go_to(url)

        # 사람처럼 마우스를 움직인다 (베지어 곡선 + 미세 떨림).
        await tab.mouse.move(640, 360, humanize=True)
        await asyncio.sleep(2)

        status = document_status(capture.entries, url)
        print(f'Status  : {status}', flush=True)
        if status is not None and status >= 400:
            solvable = await needs_human(tab)
            if solvable:
                print('          → 사이트가 보안 확인을 요구했습니다.')
            else:
                print('          → 사이트가 접속을 제한했습니다 (사람이 풀 수 있는 확인 화면이 아님).')
            if solvable and not headless and wait_human > 0:
                # 보안 확인(CAPTCHA)은 자동으로 풀지 않는다. 사람이 창에서 직접 풀면
                # 페이지가 다시 로드되므로, 문서 응답이 정상으로 바뀔 때까지 기다린다.
                status = await wait_for_human(tab, capture, url, wait_human)
                print(f'Status  : {status} (대기 후)', flush=True)

    return tab, status


async def visit(
    url: str,
    *,
    headless: bool = False,
    turnstile: bool = False,
    profile: str = 'full',
    user_data_dir: str | None = None,
    warmup: str | None = None,
    wait_human: int = 300,
    proxy: str | None = None,
) -> None:
    async with Chrome(options=build_options(headless, user_data_dir, proxy)) as browser:
        tab, _ = await open_page(
            browser,
            url,
            headless=headless,
            turnstile=turnstile,
            profile=profile,
            warmup=warmup,
            wait_human=wait_human,
        )

        print(f'URL     : {await tab.current_url()}')
        print(f'Title   : {await tab.title()}')
        print(f'Profile : {profile}')

        response = await tab.execute_script(STEALTH_CHECK_JS, return_by_value=True)
        report = json.loads(response['result']['result']['value'])
        print('Stealth check:')
        for key, value in report.items():
            print(f'  {key:<10}: {value}')

        await tab.take_screenshot('result.png', beyond_viewport=True)
        print('Screenshot: result.png')


def setup_console() -> None:
    """Windows 콘솔(cp949 등)에서 표현할 수 없는 글자가 있어도 출력 오류로 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(description='Pydoll stealth URL 접속 샘플')
    parser.add_argument('url', nargs='?', default=DEFAULT_URL)
    parser.add_argument('--headless', action='store_true', help='창 없이 실행')
    parser.add_argument('--turnstile', action='store_true', help='Cloudflare Turnstile 처리')
    parser.add_argument(
        '--profile',
        choices=['full', 'minimal'],
        default='full',
        help='full: 전체 프로필(기본), minimal: 언어·시간대만',
    )
    parser.add_argument('--user-data-dir', help='Chrome 프로필을 유지할 폴더 (쿠키 등 보존)')
    parser.add_argument('--warmup', metavar='URL', help='대상 URL 전에 먼저 방문할 주소')
    parser.add_argument(
        '--wait-human',
        type=int,
        default=300,
        metavar='SECONDS',
        help='보안 확인이 뜨면 사람이 창에서 풀 때까지 기다릴 최대 시간 (기본 300, 0 이면 안 기다림)',
    )
    parser.add_argument('--proxy', metavar='URL', help='프록시 주소 (예: socks5://host:port)')
    args = parser.parse_args()

    asyncio.run(
        visit(
            args.url,
            headless=args.headless,
            turnstile=args.turnstile,
            profile=args.profile,
            user_data_dir=args.user_data_dir,
            warmup=args.warmup,
            wait_human=args.wait_human,
            proxy=args.proxy,
        )
    )


if __name__ == '__main__':
    main()
