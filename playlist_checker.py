import asyncio
import aiohttp
import re
import os
import sys
from collections import defaultdict

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'

# Заголовки для скачивания плейлистов
HEADERS = {
    'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
    'Accept': '*/*'
}

def load_sources():
    """Загружает источники из файла формата 'Название,URL'."""
    sources = []
    if not os.path.exists(SOURCES_FILE):
        return sources
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                name, url = parts[0].strip(), parts[1].strip()
                sources.append({'name': name, 'url': url})
            else:
                name = f"Источник {i + 1}"
                url = line
                sources.append({'name': name, 'url': url})
    return sources

def parse_m3u_content(content):
    """Просто парсит M3U, извлекая название и URL канала."""
    channels = []
    # Простой regex, который ищет название после запятой и URL на следующей строке
    pattern = re.compile(r'#EXTINF:-1.*?,([^\n]*)\n(https?://[^\n]*)')
    matches = pattern.findall(content)
    for name, url in matches:
        clean_name = name.strip()
        if clean_name and url:
            channels.append({'name': clean_name, 'url': url.strip()})
    return channels

async def main():
    """Основная функция для простого объединения плейлистов."""
    print("--- Запуск скрипта простого объединения плейлистов (БЕЗ ПРОВЕРКИ) ---")
    
    sources = load_sources()
    if not sources:
        print(f"[ОШИБКА] Файл '{SOURCES_FILE}' не найден или пуст.")
        return
        
    print(f"Найдено {len(sources)} плейлистов-источников для объединения.")

    final_header = '#EXTM3U'
    epg_found = False
    # Словарь для хранения каналов, сгруппированных по имени источника
    categorized_channels = defaultdict(list)
    total_channels_found = 0

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for source in sources:
            source_name = source['name']
            url = source['url']
            try:
                print(f"  Обработка: {source_name} ({url})")
                async with session.get(url, timeout=15) as response:
                    response.raise_for_status()
                    content = await response.text()

                    if not epg_found:
                        for line in content.splitlines():
                            if line.strip().startswith("#EXTM3U") and 'url-tvg' in line:
                                final_header = line.strip()
                                epg_found = True
                                print(f"    -> Найден и сохранен заголовок с EPG.")
                                break
                    
                    parsed_channels = parse_m3u_content(content)
                    
                    # Просто добавляем все найденные каналы в категорию с именем источника
                    categorized_channels[source_name].extend(parsed_channels)
                    
                    count = len(parsed_channels)
                    total_channels_found += count
                    print(f"    -> Найдено и добавлено {count} каналов.")

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"    -> ОШИБКА: Не удалось загрузить плейлист: {e}")

    print("\nОбъединение завершено.")

    # Сортируем категории (имена источников) по алфавиту
    sorted_categories = sorted(categorized_channels.keys())
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{final_header}\n")
        for category in sorted_categories:
            # Сортируем каналы внутри каждой категории по имени
            channels_in_category = sorted(categorized_channels[category], key=lambda x: x['name'])
            for channel in channels_in_category:
                f.write(f'#EXTINF:-1 group-title="{category}",{channel["name"]}\n')
                f.write(f'{channel["url"]}\n')
            
    print("\n--- Результаты ---")
    print(f"✅ Итоговый плейлист сохранен в файл: {OUTPUT_FILE}")
    print(f"📊 Всего каналов добавлено в плейлист: {total_channels_found}")
    print("\nВнимание: Проверка на работоспособность и удаление дубликатов были отключены.")

if __name__ == '__main__':
    asyncio.run(main())
