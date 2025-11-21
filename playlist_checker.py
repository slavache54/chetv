import asyncio
import aiohttp
import os
import re

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'
TIMEOUT_SECONDS = 45

# Маскируемся под Chrome (самая надежная маскировка)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def load_source_urls():
    urls = []
    if not os.path.exists(SOURCES_FILE):
        return urls
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Чистим кавычки
            url = line.replace('"', '').replace("'", "").strip()
            if ',' in url:
                url = url.split(',', 1)[1].strip()
            
            if url:
                urls.append(url)
    return urls

def fix_github_url(url):
    """
    Исправляет битые ссылки GitHub (с refs/heads), которые отдают 404.
    """
    if 'raw.githubusercontent.com' in url and '/refs/heads/' in url:
        return url.replace('/refs/heads/', '/')
    return url

def clean_channel_name(name):
    """
    Жесткая очистка имени канала для Televizo.
    """
    if not name: return "Канал"
    
    # 1. Убиваем вертикальную черту - главный враг Televizo
    name = name.replace('|', ' - ')
    
    # 2. Убираем приставку RUZIEV+ IPTV, чтобы не мусорила
    name = name.replace('RUZIEV+ IPTV', '')
    name = name.replace('RUZIEV+', '')
    
    # 3. Чистим лишние пробелы и тире в начале
    name = name.strip()
    if name.startswith('-'):
        name = name.lstrip('-').strip()
        
    return name

def parse_channels_strict(content):
    channels = []
    current_name = None
    
    # Используем errors='replace', чтобы не падать на кривых символах
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('#EXTINF'):
            # Берем всё после первой запятой
            if ',' in line:
                raw_name = line.split(',', 1)[1]
                current_name = clean_channel_name(raw_name)
            else:
                current_name = "Без названия"
        
        elif line.startswith('#'):
            continue # Игнорируем любые другие теги
            
        else:
            # Если это ссылка на поток (http/rtmp/udp)
            if re.match(r'^(http|rtmp|udp)', line, re.IGNORECASE):
                name = current_name if current_name else "Канал"
                channels.append({'name': name, 'url': line})
                current_name = None # Сброс имени
    
    return channels

async def fetch_playlist(session, raw_url, index):
    # АВТО-ИСПРАВЛЕНИЕ ССЫЛКИ ПЕРЕД СКАЧИВАНИЕМ
    url = fix_github_url(raw_url)
    
    try:
        print(f"  [{index}] Скачивание: {url}")
        async with session.get(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                print(f"    X ОШИБКА [{index}]: Код {response.status}")
                return index, []
            
            content = await response.text(encoding='utf-8', errors='replace')
            
            # Проверка: если скачался HTML (страница ошибки 404) - игнорируем
            if content.lstrip().lower().startswith(('<html', '<!doctype')):
                print(f"    X ОШИБКА [{index}]: По ссылке не плейлист, а HTML-страница (возможно 404)")
                return index, []

            channels = parse_channels_strict(content)
            
            if not channels:
                print(f"    ! ПУСТО [{index}]: Каналы не найдены")
            else:
                print(f"    V ОК [{index}]: Найдено {len(channels)}")
            
            return index, channels

    except Exception as e:
        print(f"    X СБОЙ [{index}]: {e}")
        return index, []

async def main():
    print("--- ФИНАЛЬНАЯ СБОРКА: Auto-Fix URL + Clean RUZIEV ---")
    
    urls = load_source_urls()
    if not urls:
        print("Sources.txt пуст!")
        return

    tasks = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i, url in enumerate(urls, 1):
            tasks.append(asyncio.create_task(fetch_playlist(session, url, i)))
        
        results = await asyncio.gather(*tasks)

    # Сортируем по индексу 1, 2, 3...
    results.sort(key=lambda x: x[0])

    total_written = 0
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        for index, channels in results:
            if not channels: continue
            
            group_title = f"Плейлист - {index}"
            
            for ch in channels:
                # Пишем строго нашу группу
                f.write(f'#EXTINF:-1 group-title="{group_title}",{ch["name"]}\n')
                f.write(f"{ch['url']}\n")
                total_written += 1

    print(f"\nГотово. Файл: {OUTPUT_FILE}")
    print(f"Каналов: {total_written}")

if __name__ == '__main__':
    asyncio.run(main())
