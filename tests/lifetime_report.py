"""유지 기간 확인 기록(profile_lifetime.py 의 JSONL)을 요약한다. --slack 을 주면 Slack 채널에 올린다.

    .venv/bin/python tests/lifetime_report.py lifetime-proxy-log.jsonl            # 화면에만 출력
    .venv/bin/python tests/lifetime_report.py lifetime-proxy-log.jsonl --slack    # Slack 으로 전송

Slack 설정은 .env 의 SLACK_BOT_TOKEN, SLACK_CHANNEL_ID 를 쓴다. 프록시 주소는 기록에도 요약에도 없다 (이름만).
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from human_relay import SlackRelay, load_env, require_env  # noqa: E402

LABELS = {200: '정상(200)', 405: '보안 확인(405)', 418: '차단(418)', None: '연결 오류 등'}


def clock(stamp: str) -> str:
    return datetime.fromisoformat(stamp).strftime('%m-%d %H:%M')


def summarize(path: Path) -> str:
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    checks = [r for r in records if 'profile' in r and 'event' not in r]
    if not checks:
        return f'유지 기간 확인 기록이 비어 있습니다: {path.name}'
    # 간격은 도중에 바뀔 수 있다 (프로세스를 다시 띄울 때마다 start 기록이 남는다).
    # 각 확인 기록에 그 시점의 간격을 붙여 둔다.
    interval = None
    changes = []  # (바뀐 시각, 간격)
    for r in records:
        if r.get('event') == 'start':
            if r['interval'] != interval:
                changes.append((r['time'], r['interval']))
            interval = r['interval']
        elif 'profile' in r and 'event' not in r:
            r['_interval'] = interval
    if len(changes) == 1:
        pace = f', 프로필당 {changes[0][1] // 60}분 간격'
    elif changes:
        pace = ', 프로필당 ' + ' → '.join(
            f'{sec // 60}분 간격' + (f'({clock(when)}부터)' if index else '')
            for index, (when, sec) in enumerate(changes)
        )
    else:
        pace = ''

    lines = [
        '*네이버 프로필 유지 기간 확인 결과*',
        f'기간: {clock(checks[0]["time"])} ~ {clock(checks[-1]["time"])}' + pace,
    ]
    profiles = sorted({r['profile'] for r in checks})
    for profile in profiles:
        mine = [r for r in checks if r['profile'] == profile]
        counts: dict = {}
        for r in mine:
            counts[r['status']] = counts.get(r['status'], 0) + 1
        parts = ', '.join(
            f'{LABELS.get(status, f"HTTP {status}")} {count}회'
            for status, count in sorted(counts.items(), key=lambda item: (item[0] is None, item[0] or 0))
        )
        first = mine[0]
        lines.append('')
        lines.append(f'*{profile}* (프록시 {first.get("proxy", "direct")}, 신원 {first.get("identity")})')
        lines.append(f'• 확인 {len(mine)}회: {parts}')
        if len(changes) > 1:
            for _, sec in changes:
                part = [r for r in mine if r.get('_interval') == sec]
                if part:
                    ok = sum(1 for r in part if r['status'] == 200)
                    lines.append(f'  - {sec // 60}분 간격 구간: {len(part)}회 중 정상 {ok}회')

        blocked = [r for r in mine if r['status'] in (405, 418) or (r['status'] is None and r.get('stop'))]
        if blocked:
            lines.append(f'• 보안 확인·차단이 처음 나온 시각: {clock(blocked[0]["time"])} (HTTP {blocked[0]["status"]})')
            times = ', '.join(f'{clock(r["time"])}({r["status"]})' for r in blocked[:12])
            lines.append(f'• 발생 시각: {times}' + (' …' if len(blocked) > 12 else ''))
        else:
            lines.append('• 보안 확인·차단 없음')
        errors = [r for r in mine if r['status'] is None and not r.get('stop')]
        if errors:
            lines.append(f'• 네이버에 닿지 못한 회차 {len(errors)}회 (프록시 연결 실패 등). 첫 발생 {clock(errors[0]["time"])}')

        # 정상 응답이 이어진 가장 긴 구간
        best = run_start = None
        previous = None
        for r in mine:
            if r['status'] == 200:
                run_start = run_start or r['time']
                span = datetime.fromisoformat(r['time']) - datetime.fromisoformat(run_start)
                if best is None or span > best[0]:
                    best = (span, run_start, r['time'])
            elif r['status'] is not None:
                run_start = None
            previous = r
        if best:
            hours = best[0].total_seconds() / 3600
            lines.append(f'• 정상 응답이 이어진 가장 긴 구간: {hours:.1f}시간 ({clock(best[1])} ~ {clock(best[2])})')
        lines.append(f'• 마지막 확인: {clock(previous["time"])} → {LABELS.get(previous["status"], previous["status"])}')

        # 예정보다 크게 벌어진 간격 (기기가 잠들었거나 프로세스가 멈춘 구간)
        if interval:
            gaps = []
            for before, after in zip(mine, mine[1:]):
                gap = (datetime.fromisoformat(after['time']) - datetime.fromisoformat(before['time'])).total_seconds()
                # 간격이 바뀐 경계에서는 더 긴 쪽을 기준으로 본다.
                expected = max(before.get('_interval') or interval, after.get('_interval') or interval)
                if gap > expected * 1.5:
                    gaps.append(f'{clock(before["time"])}~{clock(after["time"])}')
            if gaps:
                lines.append(f'• 확인이 빠진 구간 {len(gaps)}곳: ' + ', '.join(gaps[:6]) + (' …' if len(gaps) > 6 else ''))

    ended = any(r.get('event') == 'end' for r in records)
    lines.append('')
    lines.append('확인 프로세스는 예정대로 끝났습니다.' if ended else '주의: 종료 기록이 없습니다. 확인이 아직 돌고 있거나 중간에 멈췄습니다.')
    lines.append('보안 확인은 풀지 않고 기록만 했습니다. 확인하는 접속 자체가 통과 상태를 연장했을 수 있습니다.')
    return '\n'.join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description='유지 기간 확인 기록 요약')
    parser.add_argument('log')
    parser.add_argument('--slack', action='store_true', help='요약을 Slack 채널에 올린다')
    parser.add_argument('--prefix', default='', help='메시지 맨 앞에 붙일 글')
    args = parser.parse_args()
    text = args.prefix + summarize(Path(args.log))
    print(text)
    if args.slack:
        load_env()
        relay = SlackRelay(require_env('SLACK_BOT_TOKEN'), require_env('SLACK_CHANNEL_ID'))
        await relay._call('chat.postMessage', data={'channel': relay.channel, 'text': text})
        print('\nSlack 으로 보냈습니다.')


if __name__ == '__main__':
    asyncio.run(main())
