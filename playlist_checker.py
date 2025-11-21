import asyncio
import aiohttp
import os
import re

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'
TIMEOUT_SECONDS = 30

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
            # Чистка ссылок
            url = line.replace('"', '').replace("'", "").strip()
            if ',' in url:
                url = url.split(',', 1)[1].strip()
            if url:
                urls.append(url)
    return urls

def parse_channels_clean(content):
    """
    Жесткий парсер:
    1. Игнорирует старые группы (#EXTGRP).
    2. Вырезает всё лишнее из #EXTINF (логотипы, id), оставляя только имя.
    3. Игнорирует мусорные строки (не URL).
    """
    channels = []
    current_name = None
    
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            # Наша цель - найти НАЗВАНИЕ, которое всегда идет после последней запятой
            # Но иногда в названии тоже есть запятые. 
            # Безопаснее всего разбить по первой запятой, а потом вычистить атрибуты
            
            # Пример: #EXTINF:-1 tvg-id="mb1",Первый канал
            # Пример: #EXTINF:-1,Первый канал
            
            if ',' in line:
                # Берем правую часть после первой запятой
                raw_name_part = line.split(',', 1)[1].strip()
                
                # Иногда "плохие" плейлисты вставляют атрибуты ПОСЛЕ запятой (редко, но бывает)
                # Или само название просто чистое.
                current_name = raw_name_part
            else:
                current_name = "Без названия"
        
        elif line.startswith('#'):
            # ПОЛНОСТЬЮ ИГНОРИРУЕМ #EXTGRP и прочие теги, чтобы не сбивать категории
            continue
            
        else:
            # ЭТО ССЫЛКА?
            # Проверка: строка должна начинаться на http (или rtmp, udp)
            # Это защищает от добавления текста ошибки "404 Not Found" как канала
            if line.lower().startswith(('http', 'rtmp', 'udp')):
                url = line
                name = current_name if current_name else "Канал"
                
                # Дополнительная чистка имени, если вдруг туда попал мусор
                channels.append({'name': name, 'url': url})
                current_name = None
            
    return channels

async def fetch_playlist(session, url, index):
    try:
        print(f"  Скачивание [{index}]: {url}")
        async with session.get(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                print(f"    X Ошибка {index}: Сервер вернул код {response.status}")
                return index, []
            
            content = await response.text(encoding='utf-8', errors='replace')
            channels = parse_channels_clean(content)
            
            if not channels:
                print(f"    ! Пусто {index}: каналы не найдены (возможно, битая ссылка).")
            else:
                print(f"    V Успех {index}: найдено {len(channels)} каналов.")
                
            return index, channels
            
    except Exception as e:
        print(f"    X Сбой {index}: {e}")
        return index, []

async def main():
    print("--- Запуск: Чистка категорий и проверка URL ---")
    
    urls = load_source_urls()
    if not urls:
        print("Файл sources.txt пуст!")
        return

    tasks = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i, url in enumerate(urls, 1):
            task = asyncio.create_task(fetch_playlist(session, url, i))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)

    # Сортируем по номеру (1, 2, 3...), чтобы сохранить порядок
    results.sort(key=lambda x: x[0])

    total_written = 0
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        for index, channels in results:
            # Принудительная категория
            group_title = f"Плейлист - {index}"
            
            for ch in channels:
                # Собираем чистую строку
                safe_name = ch['name'].replace('\n', ' ').strip()
                
                # Мы игнорируем любые оригинальные группы и пишем ТОЛЬКО нашу
                f.write(f'#EXTINF:-1 group-title="{group_title}",{safe_name}\n')
                f.write(f"{ch['url']}\n")
                total_written += 1

    print(f"\nГотово! Файл: {OUTPUT_FILE}")
    print(f"Всего записано каналов: {total_written}")

if __name__ == '__main__':
    asyncio.run(main())
