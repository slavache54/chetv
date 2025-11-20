import asyncio
import aiohttp
import os
import sys

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'

# Заголовки для скачивания плейлистов
HEADERS = {
    'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
    'Accept': '*/*'
}

def load_source_urls():
    """Загружает только URL из файла источников."""
    urls = []
    if not os.path.exists(SOURCES_FILE):
        return urls
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Ищем URL, даже если есть название
            if ',' in line:
                url = line.split(',', 1)[1].strip()
            else:
                url = line
            
            if url:
                urls.append(url)
    return urls

async def main():
    """Основная функция для "тупой" склейки плейлистов."""
    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    print("--- Запуск скрипта 'тупой' склейки плейлистов (БЕЗ ПРОВЕРКИ И ПАРСИНГА) ---")
    
    source_urls = load_source_urls()
    if not source_urls:
        print(f"[ОШИБКА] Файл '{SOURCES_FILE}' не найден или пуст.")
        return
        
    print(f"Найдено {len(source_urls)} плейлистов-источников для склейки.")

    # Создаем или очищаем итоговый файл
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f_out:
        # Записываем заголовок только один раз
        f_out.write("#EXTM3U\n")

    is_first_playlist = True

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i, url in enumerate(source_urls, 1):
            try:
                print(f"  ({i}/{len(source_urls)}) Скачивание: {url}")
                async with session.get(url, timeout=20) as response:
                    response.raise_for_status()
                    content = await response.text()
                    
                    # Открываем итоговый файл в режиме дозаписи (append)
                    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f_out:
                        # Пропускаем заголовок #EXTM3U для всех плейлистов, кроме первого
                        lines_to_write = content.splitlines()
                        if not is_first_playlist:
                            lines_to_write = [line for line in lines_to_write if not line.strip().startswith('#EXTM3U')]
                        
                        f_out.write('\n'.join(lines_to_write) + '\n')
                    
                    is_first_playlist = False
                    print(f"    -> Успешно добавлено.")

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"    -> ОШИБКА: Не удалось скачать плейлист: {e}")

    print("\nСклейка завершена.")
    print(f"✅ Итоговый плейлист сохранен в файл: {OUTPUT_FILE}")
    print("\nВнимание: Плейлисты были объединены без какой-либо обработки или проверки.")

if __name__ == '__main__':
    asyncio.run(main())
