import asyncio
import aiohttp
import os
import re

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'
TIMEOUT_SECONDS = 45

# Маскируемся под VLC
HEADERS = {
    'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
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
            # Убираем кавычки, если они есть
            url = line.replace('"', '').replace("'", "").strip()
            # Если формат с запятой, берем только ссылку
            if ',' in url:
                url = url.split(',', 1)[1].strip()
            
            if url:
                urls.append(url)
    return urls

def fix_github_url(url):
    """
    Автоматически исправляет ссылки GitHub, которые пользователь 
    вставил в формате /refs/heads/, так как они выдают ошибку 404.
    """
    if 'raw.githubusercontent.com' in url and '/refs/heads/' in url:
        # Убираем '/refs/heads/' заменяя на '/'
        fixed_url = url.replace('/refs/heads/', '/')
        return fixed_url
    return url

def clean_channel_name(name):
    """
    Убирает символы, которые ломают группировку в Televizo (RUZIEV FIX).
    """
    if not name:
        return "Канал"
    # Заменяем вертикальную черту на тире. Это лечит 'призрачные' группы.
    return name.replace('|', ' - ').strip()

def parse_channels_strict(content):
    """
    Парсер, который игнорирует мусор и текст ошибок.
    """
    channels = []
    current_name = None
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('#EXTINF'):
            # Извлекаем имя после запятой
            parts = line.split(',', 1)
            if len(parts) > 1:
                current_name = clean_channel_name(parts[1])
            else:
                current_name = "Без названия"
        
        # Игнорируем старые группы
        elif line.startswith('#'):
            continue
            
        else:
            # ВАЖНО: Проверяем, что это действительно ссылка http/rtmp
            # Это отсекает текст '404 Not Found'
            if re.match(r'^(http|rtmp|udp)', line, re.IGNORECASE):
                url = line
                name = current_name if current_name else "Канал"
                channels.append({'name': name, 'url': url})
                current_name = None
    
    return channels

async def fetch_playlist(session, raw_url, index):
    # Применяем авто-фикс ссылки перед скачиванием
    url = fix_github_url(raw_url)
    
    try:
        print(f"  [{index}] Скачивание: {url}")
        async with session.get(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                print(f"    X ОШИБКА [{index}]: Код ответа {response.status}")
                return index, []
            
            content = await response.text(encoding='utf-8', errors='ignore')
            
            # Проверка на HTML (часто сервер отдает страницу ошибки вместо плейлиста)
            if content.lstrip().lower().startswith(('<html', '<!doctype')):
                print(f"    X ОШИБКА [{index}]: Ссылка ведет на HTML-страницу (возможно, 404).")
                return index, []
                
            channels = parse_channels_strict(content)
            
            if not channels:
                print(f"    ! Пусто [{index}]: Каналы не найдены.")
            else:
                print(f"    V Успех [{index}]: {len(channels)} каналов.")
                
            return index, channels

    except Exception as e:
        print(f"    X СБОЙ [{index}]: {e}")
        return index, []

async def main():
    print("--- СТРОГАЯ СБОРКА + RUZIEV FIX + GITHUB FIX ---")
    
    urls = load_source_urls()
    if not urls:
        print("Sources.txt пуст!")
        return

    tasks = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i, url in enumerate(urls, 1):
            task = asyncio.create_task(fetch_playlist(session, url, i))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)

    # Сортируем результаты, чтобы Плейлист-1 шел перед Плейлист-2
    results.sort(key=lambda x: x[0])

    total_count = 0
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        for index, channels in results:
            if not channels: continue
            
            group_title = f"Плейлист - {index}"
            
            for ch in channels:
                f.write(f'#EXTINF:-1 group-title="{group_title}",{ch["name"]}\n')
                f.write(f"{ch['url']}\n")
                total_count += 1

    print(f"\n--- ГОТОВО ---")
    print(f"Сохранено в: {OUTPUT_FILE}")
    print(f"Всего каналов: {total_count}")

if __name__ == '__main__':
    asyncio.run(main())
