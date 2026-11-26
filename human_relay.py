"""보안 확인(CAPTCHA)을 메신저로 사람에게 전달하고 답을 받아 오는 모듈.

보안 확인을 자동으로 풀지 않는다. 화면 스크린샷과 질문을 메신저로 보내고, 사람이 보낸 답을 그대로 돌려준다.

지원하는 메신저 (--relay 값):
    telegram : Telegram 봇. 환경 변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    slack    : Slack 봇.    환경 변수 SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
    dialog   : 메신저 없이 이 Mac 의 화면에 스크린샷과 입력 창을 띄운다 (연동 전 시험용, macOS 전용)
    file     : 폴더(RELAY_DIR, 기본 relay)에 captcha.png 와 question.txt 를 쓰고 answer.txt 를 기다린다.
               Docker 컨테이너 시험용. 호스트에서 `human_relay.py watch 폴더` 를 띄워 두면
               그 폴더를 지켜보다가 입력 창을 띄우고 답을 answer.txt 로 써 준다.

환경 변수는 실행 폴더의 .env 파일에 적어 두어도 된다 (.env.example 참고).

연결 시험 (시험용 이미지를 보내고 답장을 기다린다):
    .venv/bin/python human_relay.py telegram
    .venv/bin/python human_relay.py slack

Telegram 준비:
    1. @BotFather 에게 /newbot 으로 봇을 만들고 토큰을 받는다.
    2. 봇과 1:1 대화를 시작하거나, 봇을 그룹에 초대한다.
    3. 대화방의 chat id 를 TELEGRAM_CHAT_ID 에 넣는다.
    그룹에서는 봇이 "봇 메시지에 대한 답장"만 볼 수 있다 (privacy mode). 반드시 답장으로 답한다.

Slack 준비:
    1. api.slack.com/apps 에서 앱을 만들고 Bot Token Scopes 에
       chat:write, files:write, channels:history (비공개 채널이면 groups:history) 를 추가한다.
    2. 워크스페이스에 설치해 Bot User OAuth Token (xoxb-...) 을 받는다.
    3. 전용 채널에 봇을 초대(/invite @봇이름)하고 채널 ID (C...) 를 SLACK_CHANNEL_ID 에 넣는다.
    답은 봇 메시지의 스레드에 쓴다.

여러 인스턴스를 동시에 돌려도 메신저에는 한 번에 한 건만 나가도록 RelayLock 으로 줄을 세운다.
"""

import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Self

import aiohttp

POLL_SECONDS = 3  # 답장 확인 간격
LOCK_STALE_SECONDS = 20 * 60  # 이보다 오래된 잠금은 죽은 프로세스의 것으로 보고 무시한다
MAX_ANSWER_LENGTH = 50


class RelayError(Exception):
    """메신저 API 호출이 실패했다."""


def load_env(path: str = '.env') -> None:
    """.env 파일의 KEY=VALUE 를 환경 변수로 읽는다 (이미 설정된 값은 덮어쓰지 않는다)."""
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise SystemExit(f'환경 변수 {name} 가 필요합니다 (.env.example 참고).')
    return value


def clean_answer(text: str) -> str:
    """사람이 보낸 답에서 앞뒤 공백과 줄바꿈을 정리한다."""
    return ' '.join(text.split())[:MAX_ANSWER_LENGTH]


class RelayLock:
    """여러 프로세스가 동시에 보안 확인을 만나도 메신저에는 한 번에 한 건만 내보내는 잠금."""

    def __init__(self, name: str = 'naver-human-relay.lock'):
        # 여러 컨테이너가 줄을 서려면 RELAY_LOCK_DIR 을 공유 볼륨으로 지정한다.
        self.path = Path(os.environ.get('RELAY_LOCK_DIR') or tempfile.gettempdir()) / name
        self.waited = 0.0  # 잠금을 얻기까지 기다린 시간(초)

    async def __aenter__(self) -> Self:
        started = time.monotonic()
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_SECONDS:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                await asyncio.sleep(1)
        self.waited = time.monotonic() - started
        return self

    async def __aexit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


class TelegramRelay:
    """Telegram 봇으로 사진을 보내고, 그 메시지에 대한 답장을 답으로 받는다."""

    name = 'telegram'

    def __init__(self, token: str, chat_id: str, api_base: str = 'https://api.telegram.org'):
        self.chat_id = str(chat_id)
        self.base = f'{api_base}/bot{token}'

    async def _call(self, method: str, *, data=None, params=None, timeout: int = 30) -> dict:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with (
            aiohttp.ClientSession(timeout=client_timeout) as session,
            session.post(f'{self.base}/{method}', data=data, params=params) as resp,
        ):
            body = await resp.json(content_type=None)
        if not body.get('ok'):
            raise RelayError(f'Telegram {method} 실패: {body.get("description")}')
        return body['result']

    async def send(self, image: bytes, caption: str) -> dict:
        # 이전에 쌓인 메시지를 답으로 착각하지 않도록, 지금까지의 업데이트를 건너뛴다.
        pending = await self._call('getUpdates', params={'offset': -1, 'timeout': 0})
        offset = pending[-1]['update_id'] + 1 if pending else 0

        form = aiohttp.FormData()
        form.add_field('chat_id', self.chat_id)
        form.add_field('caption', caption)
        form.add_field('photo', image, filename='captcha.png', content_type='image/png')
        message = await self._call('sendPhoto', data=form)
        return {'message_id': message['message_id'], 'offset': offset, 'caption': caption}

    async def wait_answer(self, handle: dict, timeout: int) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            wait = max(1, min(25, int(deadline - time.monotonic())))
            updates = await self._call(
                'getUpdates',
                params={
                    'offset': handle['offset'],
                    'timeout': wait,
                    'allowed_updates': json.dumps(['message']),
                },
                timeout=wait + 15,
            )
            for update in updates:
                handle['offset'] = update['update_id'] + 1
                message = update.get('message') or {}
                if str(message.get('chat', {}).get('id')) != self.chat_id:
                    continue
                reply_to = (message.get('reply_to_message') or {}).get('message_id')
                # 답장이면 우리 메시지에 대한 것만, 답장이 아니면(1:1 대화) 그대로 답으로 받는다.
                if reply_to not in (None, handle['message_id']):
                    continue
                if message.get('text'):
                    return clean_answer(message['text'])
        return None

    async def update(self, handle: dict, status: str) -> None:
        await self._call(
            'editMessageCaption',
            data={
                'chat_id': self.chat_id,
                'message_id': str(handle['message_id']),
                'caption': f'{handle["caption"]}\n\n{status}',
            },
        )


class SlackRelay:
    """Slack 봇으로 메시지와 이미지를 올리고, 그 스레드의 답글을 답으로 받는다."""

    name = 'slack'

    def __init__(self, token: str, channel: str, api_base: str = 'https://slack.com/api'):
        self.channel = channel
        self.base = api_base
        self.headers = {'Authorization': f'Bearer {token}'}

    async def _call(self, method: str, *, data: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=30)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=self.headers) as session,
            session.post(f'{self.base}/{method}', data=data) as resp,
        ):
            body = await resp.json(content_type=None)
        if not body.get('ok'):
            needed = f' (필요한 권한: {body["needed"]})' if body.get('needed') else ''
            raise RelayError(f'Slack {method} 실패: {body.get("error")}{needed}')
        return body

    async def send(self, image: bytes, caption: str) -> dict:
        # 1) 안내 메시지를 올리고, 2) 그 스레드에 이미지를 첨부한다. 답은 같은 스레드에서 받는다.
        posted = await self._call('chat.postMessage', data={'channel': self.channel, 'text': caption})
        ts = posted['ts']

        ticket = await self._call(
            'files.getUploadURLExternal',
            data={'filename': 'captcha.png', 'length': str(len(image))},
        )
        timeout = aiohttp.ClientTimeout(total=60)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.post(ticket['upload_url'], data=image) as resp,
        ):
            if resp.status >= 400:
                raise RelayError(f'Slack 이미지 업로드 실패: HTTP {resp.status}')
        await self._call(
            'files.completeUploadExternal',
            data={
                'files': json.dumps([{'id': ticket['file_id'], 'title': '보안 확인 화면'}]),
                'channel_id': self.channel,
                'thread_ts': ts,
            },
        )
        return {'ts': ts, 'caption': caption}

    async def wait_answer(self, handle: dict, timeout: int) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            thread = await self._call(
                'conversations.replies', data={'channel': self.channel, 'ts': handle['ts']}
            )
            for message in thread.get('messages', []):
                # 원글, 봇이 올린 글(이미지 첨부 포함), 시스템 메시지는 답이 아니다.
                if message.get('ts') == handle['ts'] or message.get('bot_id'):
                    continue
                if message.get('subtype') or not message.get('text'):
                    continue
                return clean_answer(message['text'])
        return None

    async def update(self, handle: dict, status: str) -> None:
        await self._call(
            'chat.update',
            data={
                'channel': self.channel,
                'ts': handle['ts'],
                'text': f'{handle["caption"]}\n\n{status}',
            },
        )


class DialogRelay:
    """메신저 없이 이 Mac 화면에 스크린샷과 입력 창을 띄운다 (연동 전 시험용)."""

    name = 'dialog'

    def __init__(self):
        if sys.platform != 'darwin':
            raise SystemExit('dialog 방식은 macOS 에서만 쓸 수 있습니다.')

    async def send(self, image: bytes, caption: str) -> dict:
        path = Path(tempfile.gettempdir()) / f'naver-captcha-{os.getpid()}.png'
        path.write_bytes(image)
        await asyncio.to_thread(subprocess.run, ['open', str(path)], check=False)
        return {'path': path, 'caption': caption}

    async def wait_answer(self, handle: dict, timeout: int) -> str | None:
        # 질문 문구는 스크립트에 끼워 넣지 않고 인자로 넘긴다.
        ask = (
            'set r to display dialog (item 1 of argv) default answer "" '
            'with title "보안 확인" giving up after (item 2 of argv as integer)'
        )
        lines = ['on run argv', ask, 'if gave up of r then return ""', 'return text returned of r']
        script = [part for line in [*lines, 'end run'] for part in ('-e', line)]
        result = await asyncio.to_thread(
            subprocess.run,
            ['osascript', *script, handle['caption'], str(timeout)],
            capture_output=True,
            text=True,
            check=False,
        )
        answer = clean_answer(result.stdout)
        return answer or None

    async def update(self, handle: dict, status: str) -> None:
        print(f'  [보안 확인] {status}', flush=True)
        handle['path'].unlink(missing_ok=True)


class FileRelay:
    """폴더에 스크린샷과 질문을 쓰고, 같은 폴더의 answer.txt 를 답으로 읽는다 (컨테이너 시험용)."""

    name = 'file'

    def __init__(self, directory: str):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    async def send(self, image: bytes, caption: str) -> dict:
        (self.dir / 'answer.txt').unlink(missing_ok=True)
        (self.dir / 'status.txt').unlink(missing_ok=True)
        (self.dir / 'captcha.png').write_bytes(image)
        # question.txt 를 마지막에 쓴다. 지켜보는 쪽은 이 파일이 생기면 새 문제로 본다.
        (self.dir / 'question.txt').write_text(caption, encoding='utf-8')
        return {'caption': caption}

    async def wait_answer(self, handle: dict, timeout: int) -> str | None:
        answer_file = self.dir / 'answer.txt'
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if answer_file.exists():
                answer = clean_answer(answer_file.read_text(encoding='utf-8'))
                answer_file.unlink(missing_ok=True)
                if answer:
                    return answer
        return None

    async def update(self, handle: dict, status: str) -> None:
        (self.dir / 'question.txt').unlink(missing_ok=True)
        (self.dir / 'status.txt').write_text(status, encoding='utf-8')
        print(f'  [보안 확인] {status}', flush=True)


RELAYS = ('telegram', 'slack', 'dialog', 'file')


def create_relay(name: str):
    """--relay 값에 맞는 전달 객체를 만든다. 필요한 환경 변수가 없으면 안내하고 끝낸다."""
    load_env()
    if name == 'telegram':
        return TelegramRelay(require_env('TELEGRAM_BOT_TOKEN'), require_env('TELEGRAM_CHAT_ID'))
    if name == 'slack':
        return SlackRelay(require_env('SLACK_BOT_TOKEN'), require_env('SLACK_CHANNEL_ID'))
    if name == 'dialog':
        return DialogRelay()
    if name == 'file':
        return FileRelay(os.environ.get('RELAY_DIR') or 'relay')
    raise SystemExit(f'알 수 없는 전달 방식: {name}')


def sample_png(width: int = 320, height: int = 120) -> bytes:
    """연결 시험용 단색 PNG (외부 라이브러리 없이 만든다)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    row = b'\x00' + bytes((30, 58, 95)) * width
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(row * height))
        + chunk(b'IEND', b'')
    )


async def connection_test(name: str, timeout: int) -> None:
    relay = create_relay(name)
    async with RelayLock():
        handle = await relay.send(
            sample_png(),
            '[연결 시험] 이 메시지에 답장(Slack 은 스레드)으로 아무 글자나 보내 주세요.',
        )
        print(f'{name} 로 시험 메시지를 보냈습니다. 답장을 {timeout}초 기다립니다...', flush=True)
        answer = await relay.wait_answer(handle, timeout)
        if answer is None:
            await relay.update(handle, '시간 초과: 답장을 받지 못했습니다.')
            raise SystemExit('답장을 받지 못했습니다.')
        await relay.update(handle, f'답장 확인: {answer}')
    print(f'받은 답장: {answer}')


async def watch(directory: str, timeout: int) -> None:
    """file 방식의 폴더를 지켜보다가, 문제가 생기면 이 Mac 에 입력 창을 띄워 답을 써 준다."""
    folder = Path(directory)
    dialog = DialogRelay()
    print(f'{folder} 를 지켜봅니다. 끝내려면 Ctrl+C.', flush=True)
    seen = None
    while True:
        await asyncio.sleep(1)
        question_file = folder / 'question.txt'
        if not question_file.exists():
            seen = None
            continue
        stamp = question_file.stat().st_mtime
        if stamp == seen:
            continue
        seen = stamp
        caption = question_file.read_text(encoding='utf-8')
        print('\a새 보안 확인이 도착했습니다.', flush=True)
        handle = await dialog.send((folder / 'captcha.png').read_bytes(), caption)
        answer = await dialog.wait_answer(handle, timeout)
        handle['path'].unlink(missing_ok=True)
        if answer:
            (folder / 'answer.txt').write_text(answer, encoding='utf-8')
            print('답을 전달했습니다.', flush=True)
        else:
            print('답이 입력되지 않았습니다.', flush=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='메신저 연결 시험 / file 방식 폴더 지켜보기')
    parser.add_argument('relay', choices=[*RELAYS, 'watch'])
    parser.add_argument('directory', nargs='?', default='relay', help='watch 할 폴더')
    parser.add_argument('--timeout', type=int, default=120, metavar='SECONDS')
    args = parser.parse_args()
    if args.relay == 'watch':
        try:
            asyncio.run(watch(args.directory, args.timeout))
        except KeyboardInterrupt:
            pass
    else:
        try:
            asyncio.run(connection_test(args.relay, args.timeout))
        except RelayError as error:
            raise SystemExit(f'연결 시험 실패: {error}') from None
