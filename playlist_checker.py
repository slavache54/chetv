import asyncio
import aiohttp
import re
import os
import sys
from collections import defaultdict

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'
DEFAULT_CATEGORY = 'Общие'
MAX_CONCURRENT_REQUESTS = 200  # Количество одновременных асинхронных запросов
TIMEOUT = 4  # Таймаут в секундах для одного запроса

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def parse_m3u_content(content):
    """Парсит M3U и извлекает каналы с категориями."""
    channels = []
    pattern = re.compile(r'#EXTINF:-1(.*?),([^\n]*)\n(https?://[^\n]*)')
    matches = pattern.findall(content)

    for attributes, name, url in matches:
        group_title_match = re.search(r'group-title="(.*?)"', attributes, re.IGNORECASE)
        category = group_title_match.group(1).strip() if group_title_match else DEFAULT_CATEGORY
        clean_name = name.strip()

        if clean_name and url:
            channels.append({'name': clean_name, 'url': url.strip(), 'category': category})
    return channels

async def check_stream_url(session, channel, semaphore):
    """Асинхронно проверяет доступность URL."""
    async with semaphore:
        try:
            async with session.head(channel['url'], timeout=TIMEOUT, allow_redirects=True) as response:
                if 200 <= response.status < 400:
                    return channel
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

async def main():
    """Основная асинхронная функция."""
    print("--- Запуск асинхронного скрипта обработки плейлистов ---")

    if not os.path.exists(SOURCES_FILE):
        print(f"[ОШИБКА] Файл '{SOURCES_FILE}' не найден.")
        return

    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        source_urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    if not source_urls:
        print("[ИНФО] Файл источников пуст.")
        return
        
    print(f"Найдено {len(source_urls)} плейлистов-источников.")

    final_header = '#EXTM3U'
    epg_found = False
    all_channels = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for url in source_urls:
            try:
                print(f"  Загрузка: {url}")
                async with session.get(url, timeout=15) as response:
                    response.raise_for_status()
                    content = await response.text()

                    if not epg_found:
                        for line in content.splitlines():
                            if line.strip().startswith("#EXTM3U") and 'url-tvg' in line:
                                final_header = line.strip()
                                epg_found = True
                                print(f"    -> Найден заголовок с EPG.")
                                break
                    
                    channels = parse_m3u_content(content)
                    all_channels.extend(channels)
                    print(f"    -> Найдено {len(channels)} каналов.")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"    -> Не удалось загрузить: {e}")

    if not all_channels:
        print("\nНе найдено ни одного канала для проверки.")
        return

    print(f"\nВсего найдено {len(all_channels)} каналов. Начинается проверка...")
    
    categorized_working_channels = defaultdict(list)
    unique_urls = set()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [check_stream_url(session, channel, semaphore) for channel in all_channels]
        total = len(tasks)
        for i, future in enumerate(asyncio.as_completed(tasks), 1):
            result = await future
            sys.stdout.write(f"\rПрогресс: {i}/{total} ({i/total*100:.1f}%)")
            sys.stdout.flush()

            if result and result['url'] not in unique_urls:
                unique_urls.add(result['url'])
                categorized_working_channels[result['category']].append(result)

    print("\nПроверка завершена.")
    
    sorted_categories = sorted(categorized_working_channels.keys())
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{final_header}\n")
        for category in sorted_categories:
            channels_in_category = sorted(categorized_working_channels[category], key=lambda x: x['name'])
            for channel in channels_in_category:
                f.write(f'#EXTINF:-1 group-title="{channel["category"]}",{channel["name"]}\n')
                f.write(f'{channel["url"]}\n')

    total_working = len(unique_urls)
    print("\n--- Результаты ---")
    print(f"✅ Итоговый плейлист сохранен в файл: {OUTPUT_FILE}")
    print(f"📊 Всего уникальных и рабочих каналов: {total_working}")
    print(f"🗑️  Отсеяно нерабочих и дубликатов: {len(all_channels) - total_working}")

if __name__ == '__main__':
    asyncio.run(main())