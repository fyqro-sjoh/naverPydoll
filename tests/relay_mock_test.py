"""human_relay 의 Telegram / Slack 호출을 가짜 서버로 검증한다 (실제 메신저 없이 실행).

    .venv/bin/python tests/relay_mock_test.py

가짜 서버는 각 API 가 받는 요청 형태를 흉내 낼 뿐이다. 실제 서비스에서의 동작은
토큰을 넣고 `human_relay.py telegram|slack` 으로 따로 확인해야 한다.
"""

import asyncio
import json
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import human_relay
from human_relay import RelayLock, SlackRelay, TelegramRelay, sample_png

human_relay.POLL_SECONDS = 0.1
calls: list[tuple[str, dict]] = []


async def telegram(request: web.Request) -> web.Response:
    method = request.match_info['method']
    if request.content_type.startswith('multipart/'):
        reader = await request.multipart()
        data = {}
        async for part in reader:
            body = await part.read()
            data[part.name] = len(body) if part.filename else body.decode()
    else:
        data = dict(await request.post())
    data.update(request.query)
    calls.append((f'tg.{method}', data))
    if method == 'getUpdates':
        if data.get('offset') == '-1':
            return web.json_response({'ok': True, 'result': [{'update_id': 100, 'message': {}}]})
        other_chat = {'chat': {'id': 999}, 'text': '다른 방'}
        other_reply = {'chat': {'id': 42}, 'text': '딴 답', 'reply_to_message': {'message_id': 1}}
        answer = {'chat': {'id': 42}, 'text': ' 12  3\n', 'reply_to_message': {'message_id': 7}}
        updates = [
            {'update_id': 101, 'message': other_chat},
            {'update_id': 102, 'message': other_reply},
            {'update_id': 103, 'message': answer},
        ]
        return web.json_response({'ok': True, 'result': updates})
    if method == 'sendPhoto':
        return web.json_response({'ok': True, 'result': {'message_id': 7}})
    return web.json_response({'ok': True, 'result': True})


async def slack(request: web.Request) -> web.Response:
    method = request.match_info['method']
    data = dict(await request.post())
    data['_auth'] = request.headers.get('Authorization', '')
    calls.append((f'slack.{method}', data))
    if method == 'chat.postMessage':
        return web.json_response({'ok': True, 'ts': '111.222'})
    if method == 'files.getUploadURLExternal':
        url = f'http://{request.host}/upload'
        return web.json_response({'ok': True, 'upload_url': url, 'file_id': 'F1'})
    if method == 'conversations.replies':
        messages = [
            {'ts': '111.222', 'text': '원글', 'bot_id': 'B1'},
            {'ts': '111.300', 'text': '', 'bot_id': 'B1', 'files': [{}]},
            {'ts': '111.350', 'text': '입장', 'subtype': 'channel_join'},
            {'ts': '111.400', 'text': '  45 6 ', 'user': 'U1'},
        ]
        return web.json_response({'ok': True, 'messages': messages})
    return web.json_response({'ok': True})


async def upload(request: web.Request) -> web.Response:
    calls.append(('slack.upload', {'bytes': len(await request.read())}))
    return web.Response(text='OK')


def called(name: str) -> dict:
    return next(data for method, data in calls if method == name)


async def main() -> None:
    app = web.Application()
    app.router.add_post('/bot{token}/{method}', telegram)
    app.router.add_post('/api/{method}', slack)
    app.router.add_post('/upload', upload)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    base = f'http://127.0.0.1:{runner.addresses[0][1]}'
    image = sample_png()
    assert image.startswith(b'\x89PNG')

    tg = TelegramRelay('TOKEN', '42', api_base=base)
    handle = await tg.send(image, '질문')
    assert handle['message_id'] == 7 and handle['offset'] == 101, handle
    assert called('tg.sendPhoto') == {'chat_id': '42', 'caption': '질문', 'photo': len(image)}
    # 다른 대화방의 글과 다른 메시지에 대한 답장은 건너뛰고, 우리 메시지의 답장만 받는다.
    assert await tg.wait_answer(handle, 5) == '12 3'
    assert handle['offset'] == 104
    await tg.update(handle, '통과했습니다.')
    edited = called('tg.editMessageCaption')
    assert edited['message_id'] == '7' and edited['caption'].endswith('통과했습니다.'), edited

    sl = SlackRelay('xoxb-TEST', 'C123', api_base=f'{base}/api')
    handle = await sl.send(image, '질문')
    assert handle['ts'] == '111.222'
    assert called('slack.chat.postMessage')['_auth'] == 'Bearer xoxb-TEST'
    assert called('slack.files.getUploadURLExternal')['length'] == str(len(image))
    assert called('slack.upload') == {'bytes': len(image)}
    done = called('slack.files.completeUploadExternal')
    assert json.loads(done['files'])[0]['id'] == 'F1' and done['thread_ts'] == '111.222', done
    # 원글, 봇이 올린 이미지, 시스템 메시지는 건너뛰고 사람의 답글만 받는다.
    assert await sl.wait_answer(handle, 5) == '45 6'
    await sl.update(handle, '통과했습니다.')
    assert called('slack.chat.update')['ts'] == '111.222'

    # 잠금: 두 번째 요청은 첫 번째가 끝날 때까지 기다린다.
    order = []

    async def worker(name: str, hold: float) -> None:
        async with RelayLock('relay-mock-test.lock'):
            order.append(f'{name} 시작')
            await asyncio.sleep(hold)
            order.append(f'{name} 끝')

    first = asyncio.create_task(worker('A', 1.2))
    await asyncio.sleep(0.1)
    await asyncio.gather(first, worker('B', 0))
    assert order == ['A 시작', 'A 끝', 'B 시작', 'B 끝'], order

    await runner.cleanup()
    print('모든 검증 통과:', ', '.join(dict.fromkeys(method for method, _ in calls)))


asyncio.run(main())
