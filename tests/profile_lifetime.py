"""통과된 프로필이 얼마나 오래 유지되는지 주기적으로 확인한다.

정해진 간격(기본 1시간)마다 프로필로 검색을 한 번 실행하고 결과를 한 줄씩 기록한다.
보안 확인(405)이나 차단(418)이 나오면 풀지 않고 그대로 기록한 뒤 그 프로필의 확인을 끝낸다
(``--keep-going`` 을 주면 끝내지 않고 다음 차례에 다시 본다).
보안 확인을 자동으로 풀지 않으며, 사람에게 전달하지도 않는다 (유지 기간을 재는 것이 목적).

    .venv/bin/python tests/profile_lifetime.py chrome-profile chrome-profile-b:win32

프로필 뒤에 ``:win32`` 를 붙이면 그 프로필은 Windows 신원으로 연다 (만들 때의 신원과 같아야 한다).
세 번째 칸은 .env 에 적어 둔 프록시 이름이다: ``chrome-profile-kr01::kr01`` (신원 칸은 비워도 된다).
프로필이 여러 개면 간격 안에서 고르게 나눠 실행한다 (2개, 1시간이면 30분씩 엇갈림).

주의: 확인하는 접속 자체가 통과 상태를 연장할 수 있다. 이 시험이 재는 것은
"매 간격마다 한 번씩 쓰는 프로필"의 유지 기간이다. 쓰지 않고 둔 프로필의 유지 기간은 알 수 없다.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naver_products import build_url, fetch  # noqa: E402
from stealth_visit import resolve_proxy, setup_console  # noqa: E402


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def append(log: Path, record: dict) -> None:
    with log.open('a', encoding='utf-8') as file:
        file.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False), flush=True)


async def check(profile: str, identity: str, proxy: str, url: str) -> dict:
    """프로필로 검색을 한 번 실행한다. 보안 확인이 나와도 풀지 않는다."""
    if identity:
        os.environ['FINGERPRINT_OS'] = identity
    else:
        os.environ.pop('FINGERPRINT_OS', None)
    started = time.monotonic()
    record = {'time': now(), 'profile': profile, 'identity': identity or 'host', 'proxy': proxy or 'direct'}
    try:
        total, products = await fetch(
            url, headless=True, user_data_dir=profile, proxy=resolve_proxy(proxy), wait_human=0
        )
        record.update(ok=True, status=200, total=total, count=len(products))
    except SystemExit as error:
        # naver_products 는 실패를 SystemExit 메시지로 알린다. 'HTTP 405' 같은 상태를 꺼낸다.
        message = str(error)
        found = re.search(r'HTTP (\d{3})', message)
        record.update(ok=False, status=int(found.group(1)) if found else None, error=message, stop=True)
    except Exception as error:  # 네트워크 끊김 등. 기록하고 다음 차례에 다시 본다.
        record.update(ok=False, status=None, error=f'{type(error).__name__}: {error}')
    record['seconds'] = round(time.monotonic() - started, 1)
    return record


async def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(description='통과된 프로필의 유지 기간 확인')
    parser.add_argument('profiles', nargs='+', help='프로필[:신원[:프록시 이름]]. 예: chrome-profile-b:win32, chrome-profile-kr01::kr01')
    parser.add_argument('--query', default='LG 그램 16인치 5060')
    parser.add_argument('--interval', type=int, default=3600, metavar='SECONDS')
    parser.add_argument('--max-hours', type=float, default=168, help='이 시간이 지나면 끝낸다 (기본 7일)')
    parser.add_argument('--until', metavar='YYYY-MM-DDTHH:MM', help='이 시각에 끝낸다 (--max-hours 대신)')
    parser.add_argument('--first-delay', type=int, default=0, metavar='SECONDS', help='첫 확인까지 기다릴 시간')
    parser.add_argument('--log', default='lifetime-log.jsonl')
    parser.add_argument(
        '--keep-going',
        action='store_true',
        help='보안 확인이나 차단이 나와도 그 프로필의 확인을 끝내지 않고 다음 차례에 다시 본다',
    )
    args = parser.parse_args()
    if args.interval < 600:
        raise SystemExit('간격은 600초 이상이어야 합니다 (요청 빈도 제한).')

    log = Path(args.log)
    url = build_url(args.query, model_only=True)
    targets = [tuple((item.split(':') + ['', ''])[:3]) for item in args.profiles]
    for profile, _, proxy in targets:
        if '/' in proxy:
            raise SystemExit('프록시는 주소가 아니라 .env 에 적어 둔 이름으로 줍니다.')
        resolve_proxy(proxy)  # 이름이 .env 에 없으면 시작하기 전에 알린다
        if not Path(profile).is_dir():
            raise SystemExit(f'프로필 폴더가 없습니다: {profile}')

    # 일정은 벽시계로 잰다. time.monotonic() 은 기기가 잠든 동안 멈춰서 예정 시각이 밀린다.
    begin = time.time()
    end = datetime.fromisoformat(args.until).timestamp() if args.until else begin + args.max_hours * 3600
    step = args.interval / len(targets)
    # 프로필별 다음 실행 시각. 간격 안에서 고르게 엇갈린다.
    due = {
        profile: begin + args.first_delay + index * step
        for index, (profile, _, _) in enumerate(targets)
    }
    settings = {profile: (identity, proxy) for profile, identity, proxy in targets}
    append(log, {'time': now(), 'event': 'start', 'profiles': args.profiles, 'interval': args.interval})

    while due:
        profile = min(due, key=due.get)
        if due[profile] >= end:
            break
        # 짧게 나눠 잔다. 한 번에 길게 자면 기기가 잠들었다 깬 뒤 예정 시각을 지나칠 수 있다.
        while (remaining := due[profile] - time.time()) > 0:
            await asyncio.sleep(min(remaining, 20))
        record = await check(profile, *settings[profile], url)
        append(log, record)
        if record.get('stop') and not args.keep_going:
            # 405(보안 확인), 418(차단), 목록을 찾지 못함: 더 접속하지 않고 이 프로필의 확인을 끝낸다.
            append(log, {'time': now(), 'event': 'stopped', 'profile': profile, 'status': record['status']})
            del due[profile]
            continue
        # 기기가 잠들었다 깨어나도 밀린 횟수를 몰아서 실행하지 않는다.
        due[profile] += args.interval
        while due[profile] < time.time():
            due[profile] += args.interval
    append(log, {'time': now(), 'event': 'end'})


if __name__ == '__main__':
    asyncio.run(main())
