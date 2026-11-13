#!/usr/bin/env python3
"""IPTV merger: publishes only streams with positive ffprobe media checks.

Requires aiohttp and ffprobe (from FFmpeg). Designed for GitHub Actions.
No URLs or access tokens are written into diagnostics.
"""

import asyncio
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

SOURCES_FILE = Path(os.getenv('SOURCES_FILE', 'sources.txt'))
OUTPUT_FILE = Path(os.getenv('OUTPUT_FILE', 'master_playlist.m3u'))
REPORT_FILE = Path(os.getenv('REPORT_FILE', 'playlist_report.json'))
MAX_CONCURRENT_PROBES = max(1, int(os.getenv('MAX_CONCURRENT_PROBES', '20')))
MAX_CONCURRENT_DOWNLOADS = max(1, int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '12')))
PROBE_TIMEOUT = max(3, int(os.getenv('PROBE_TIMEOUT', '14')))
FETCH_TIMEOUT = max(3, int(os.getenv('FETCH_TIMEOUT', '35')))
RETRIES = max(1, int(os.getenv('RETRIES', '2')))
# Guard against an outage removing most previously verified channels.
MIN_RETAIN_RATIO = max(0.0, min(1.0, float(os.getenv('MIN_RETAIN_RATIO', '0.25'))))
MAX_PLAYLIST_BYTES = 12 * 1024 * 1024
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
HEADERS = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
VALID_URL = re.compile(r'^(https?|rtmp|rtmps|rtsp|udp|rtp)://', re.I)
GROUP_ATTR = re.compile(r'\s+group-title="[^"]*"')


@dataclass
class Channel:
    source_id: int
    url: str
    extinf: str
    options: list[str] = field(default_factory=list)
    user_agent: str = ''
    referer: str = ''


def load_sources():
    if not SOURCES_FILE.exists():
        raise FileNotFoundError('sources.txt is missing')
    urls = []
    for line in SOURCES_FILE.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip().strip('"\'')
        if not line or line.startswith('#'):
            continue
        # Compatibility with old 'name,URL' entries; do not split URL queries.
        if not VALID_URL.match(line) and ',' in line:
            line = line.split(',', 1)[1].strip()
        line = line.replace('/refs/heads/', '/') if 'raw.githubusercontent.com/' in line else line
        if VALID_URL.match(line):
            urls.append(line)
        else:
            print('Skipped an invalid source line (URL not displayed).')
    return urls


def clean_name(name):
    name = name.replace('|', ' - ').replace('RUZIEV+ IPTV', '').replace('RUZIEV+', '')
    return name.strip(' -\t') or 'Канал'


def safe_extinf(line, source_id):
    # Keep EPG/logo/tvg-id metadata, but sanitize output channel names.
    head, sep, name = line.partition(',')
    if not sep:
        head, name = '#EXTINF:-1', 'Без названия'
    head = head.replace('\r', '').replace('\n', '')
    if not GROUP_ATTR.search(head):
        head += f' group-title="Плейлист - {source_id}"'
    return f'{head},{clean_name(name)}'


def parse_channels(content, source_id, playlist_url):
    lines = content.splitlines()
    # An HLS master/media manifest is itself a single playable stream.
    if any(line.strip().startswith('#EXT-X-') for line in lines):
        return [Channel(source_id, playlist_url,
                        f'#EXTINF:-1 group-title="Плейлист - {source_id}",HLS источник {source_id}')]
    channels = []
    current = None
    options = []
    agent, referer = '', ''
    for raw in lines:
        line = raw.strip()
        if line.startswith('#EXTINF'):
            current = safe_extinf(line, source_id)
            options = []
            agent, referer = '', ''
        elif line.startswith('#EXTVLCOPT:') or line.startswith('#KODIPROP:'):
            if current is not None:
                options.append(line)
                if line.lower().startswith('#extvlcopt:http-user-agent='):
                    agent = line.split('=', 1)[1].strip()
                elif line.lower().startswith('#extvlcopt:http-referrer='):
                    referer = line.split('=', 1)[1].strip()
        elif line and not line.startswith('#') and VALID_URL.match(line):
            extinf = current or f'#EXTINF:-1 group-title="Плейлист - {source_id}",Канал'
            channels.append(Channel(source_id, line, extinf, options[:], agent, referer))
            current, options, agent, referer = None, [], '', ''
    return channels


async def download(session, semaphore, source_url, index):
    async with semaphore:
        for attempt in range(RETRIES):
            try:
                async with session.get(source_url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
                                       allow_redirects=True) as response:
                    if response.status != 200:
                        raise ValueError(f'HTTP {response.status}')
                    body = await response.content.read(MAX_PLAYLIST_BYTES + 1)
                    if len(body) > MAX_PLAYLIST_BYTES:
                        raise ValueError('playlist exceeds 12 MiB')
                    content = body.decode('utf-8-sig', errors='replace')
                    if content.lstrip().lower().startswith(('<html', '<!doctype')):
                        raise ValueError('server returned HTML instead of M3U')
                    channels = parse_channels(content, index, str(response.url))
                    if not channels:
                        raise ValueError('no channel URLs found')
                    print(f'Источник {index}: получен, найдено {len(channels)} каналов')
                    return channels, None
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                # IMPORTANT: never log exception strings from aiohttp, they can contain private URLs.
                error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                if attempt + 1 < RETRIES:
                    await asyncio.sleep(1 + attempt)
        print(f'Источник {index}: недоступен ({error})')
        return [], error


async def probe_stream(channel, semaphore):
    async with semaphore:
        for attempt in range(RETRIES):
            cmd = [
                'ffprobe', '-hide_banner', '-v', 'error',
                '-rw_timeout', str(PROBE_TIMEOUT * 1_000_000),
                '-analyzeduration', '1500000', '-probesize', '1000000',
                '-show_entries', 'stream=codec_type', '-of', 'json',
            ]
            # Some providers require matching playback headers.
            if channel.url.lower().startswith(('http://', 'https://')):
                cmd += ['-user_agent', channel.user_agent or USER_AGENT]
                if channel.referer:
                    cmd += ['-referer', channel.referer]
            cmd += ['-i', channel.url]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
                )
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    reason = 'timeout'
                    continue
                if proc.returncode == 0:
                    try:
                        data = json.loads(out)
                        types = {s.get('codec_type') for s in data.get('streams', [])}
                        if 'video' in types or 'audio' in types:
                            return True, 'ok'
                    except (ValueError, TypeError):
                        pass
                reason = 'no_media_stream'
            except OSError:
                reason = 'ffprobe_error'
            if attempt + 1 < RETRIES:
                await asyncio.sleep(0.5)
        return False, reason


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def existing_count():
    if not OUTPUT_FILE.exists():
        return 0
    try:
        return sum(line.startswith('#EXTINF') for line in OUTPUT_FILE.open(encoding='utf-8'))
    except (OSError, UnicodeError):
        return 0


async def main():
    if not shutil.which('ffprobe'):
        raise RuntimeError('ffprobe is missing: install FFmpeg before running the checker')
    sources = load_sources()
    if not sources:
        raise RuntimeError('sources.txt has no valid sources')
    print(f'Начинаем проверку {len(sources)} источников; параллельных потоков: {MAX_CONCURRENT_PROBES}')

    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_DOWNLOADS, ttl_dns_cache=300)
    download_sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        downloads = await asyncio.gather(*[
            download(session, download_sem, url, i)
            for i, url in enumerate(sources, 1)
        ])

    by_source = {}
    all_channels = []
    for i, (channels, err) in enumerate(downloads, 1):
        by_source[i] = {'id': i, 'total': len(channels), 'working': 0, 'rejected': 0,
                        'download_error': err, 'status': 'unavailable' if err else 'checking'}
        all_channels.extend(channels)

    # Probe a URL + playback headers only once, even if it occurs in multiple playlists.
    unique = {}
    for channel in all_channels:
        unique.setdefault((channel.url, channel.user_agent, channel.referer), channel)
    print(f'Каналов всего: {len(all_channels)}, уникальных потоков для проверки: {len(unique)}')
    sem = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
    keys = list(unique)
    checked = await asyncio.gather(*(probe_stream(unique[k], sem) for k in keys))
    results = dict(zip(keys, checked))

    written = []
    errors = Counter()
    for ch in all_channels:
        ok, reason = results[(ch.url, ch.user_agent, ch.referer)]
        if ok:
            by_source[ch.source_id]['working'] += 1
            written.append(ch)
        else:
            by_source[ch.source_id]['rejected'] += 1
            errors[reason] += 1

    for item in by_source.values():
        if item['download_error']:
            continue
        item['status'] = 'active' if item['working'] else 'disabled_no_working_channels'
        print(f"Источник {item['id']}: {item['working']}/{item['total']} рабочих, "
              f"отключено {item['rejected']}")

    previous = existing_count()
    current = len(written)
    # Fail closed on a suspicious mass outage, preserving the last published file.
    safe = current > 0 and (previous == 0 or current >= previous * MIN_RETAIN_RATIO)
    reason = None
    if current == 0:
        reason = 'no verified channels'
    elif previous and current < previous * MIN_RETAIN_RATIO:
        reason = 'mass outage protection: below MIN_RETAIN_RATIO'

    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'sources': list(by_source.values()),
        'sources_total': len(sources),
        'channels_found': len(all_channels),
        'unique_streams_checked': len(unique),
        'channels_verified': current,
        'channels_rejected': len(all_channels) - current,
        'failures_by_reason': dict(errors),
        'previous_published_channels': previous,
        'published': safe,
        'publication_block_reason': reason,
    }
    write_atomic(REPORT_FILE, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if not safe:
        print(f'Сборка не опубликована: {reason}. Последний рабочий файл сохранён.')
        return 1

    output = ['#EXTM3U']
    for ch in written:
        output.append(ch.extinf)
        output.extend(ch.options)
        output.append(ch.url)
    write_atomic(OUTPUT_FILE, '\n'.join(output) + '\n')
    print(f'Опубликовано: {current} рабочих каналов в {OUTPUT_FILE}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Ошибка настройки: {type(exc).__name__}: {exc}')
        raise SystemExit(1)
