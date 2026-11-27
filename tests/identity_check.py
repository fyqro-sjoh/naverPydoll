"""브라우저가 내보내는 신원(요청 헤더, 스크립트 값)을 외부 접속 없이 확인한다.

같은 프로세스 안에 로컬 서버(127.0.0.1)를 띄우고 브라우저로 열어, 서버가 받은 요청 헤더와
페이지 스크립트에서 보이는 값을 출력한다. localhost 는 보안 컨텍스트라 Client Hints 도 나간다.

    FINGERPRINT_OS=win32 python tests/identity_check.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stealth_visit import launch, open_page  # noqa: E402

HEADERS = ('user-agent', 'sec-ch-ua', 'sec-ch-ua-platform', 'sec-ch-ua-mobile', 'accept-language')

SCRIPT = """
(async () => {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl');
  const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
  const high = navigator.userAgentData
    ? await navigator.userAgentData.getHighEntropyValues(
        ['platformVersion', 'architecture', 'bitness'])
    : null;
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = '16px "Malgun Gothic", monospace';
  const malgun = ctx.measureText('가나다라 mmmmmmmmmmlli').width;
  ctx.font = '16px monospace';
  const mono = ctx.measureText('가나다라 mmmmmmmmmmlli').width;
  return JSON.stringify({
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    uaDataPlatform: navigator.userAgentData && navigator.userAgentData.platform,
    highEntropy: high,
    webdriver: navigator.webdriver,
    languages: navigator.languages,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height, devicePixelRatio],
    hardware: [navigator.hardwareConcurrency, navigator.deviceMemory],
    webglRenderer: ext && gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
    malgunGothicReported: document.fonts.check('16px "Malgun Gothic"'),
    malgunGothicRendersDifferently: malgun !== mono,
  });
})()
"""


async def main() -> None:
    received: dict = {}

    async def handler(request: web.Request) -> web.Response:
        if request.path == '/':
            received.update({name: request.headers.get(name) for name in HEADERS})
        return web.Response(text='<!doctype html><title>identity</title>ok', content_type='text/html')

    app = web.Application()
    app.router.add_get('/{tail:.*}', handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    async with launch(True, None, None) as browser:
        tab, status = await open_page(browser, f'http://127.0.0.1:{port}/', headless=True)
        response = await tab.execute_script(SCRIPT, return_by_value=True, await_promise=True)
        values = json.loads(response['result']['result']['value'])
    await runner.cleanup()

    print(f'status: {status}')
    print('--- 서버가 받은 요청 헤더 ---')
    for name, value in received.items():
        print(f'{name}: {value}')
    print('--- 스크립트에서 보이는 값 ---')
    for name, value in values.items():
        print(f'{name}: {value}')

    # FINGERPRINT_OS=win32 일 때의 통과 조건. 하나라도 어긋나면 종료 코드 1.
    if os.environ.get('FINGERPRINT_OS', '').strip().lower() == 'win32':
        everything = json.dumps([received, values])
        checks = {
            'HeadlessChrome 표기가 어디에도 없음': 'Headless' not in everything,
            '헤더 UA 가 Windows': 'Windows NT 10.0' in (received.get('user-agent') or ''),
            '헤더 sec-ch-ua-platform 이 Windows': received.get('sec-ch-ua-platform') == '"Windows"',
            'navigator.userAgent 가 Windows': 'Windows NT 10.0' in values['userAgent'],
            'navigator.platform 이 Win32': values['platform'] == 'Win32',
            'userAgentData.platform 이 Windows': values['uaDataPlatform'] == 'Windows',
            'navigator.webdriver 가 false': values['webdriver'] is False,
            'Linux 표기가 어디에도 없음': 'Linux' not in everything and 'X11' not in everything,
        }
        print('--- 판정 ---')
        for name, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'}: {name}")
        if not all(checks.values()):
            raise SystemExit(1)
        print('RESULT: PASS')


if __name__ == '__main__':
    asyncio.run(main())
