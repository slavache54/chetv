import asyncio
import aiohttp
import re
import os
import sys

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'

# Маскируемся под плеер, чтобы сервера не блокировали скачивание
HEADERS = {
    'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
    'Accept': '*/*'
}

def load_source_urls():
    """Загружает только ссылки из файла."""
    urls = []
    if not os.path.exists(SOURCES_FILE):
        return urls
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Игнорируем пустые строки и комментарии, кавычки убираем если есть
            if not line or line.startswith('#'):
                continue
            url = line.replace('"', '').replace("'", "").strip()
            if url:
                urls.append(url)
    return urls

def parse_m3u_channels(content):
    """Парсит каналы: возвращает список (Название канала, Ссылка)."""
    channels = []
    # Регулярка ищет имя канала после запятой и следующую строку-ссылку
    pattern = re.compile(r'#EXTINF:-1.*?,([^\n]*)\n(https?://[^\n]*)')
    matches = pattern.findall(content)
    
    for name, url in matches:
        channels.append((name.strip(), url.strip()))
    
    return channels

async def main():
    print("--- Запуск сборщика плейлистов (Авто-нумерация категорий) ---")
    
    urls = load_source_urls()
    if not urls:
        print(f"[ОШИБКА] Файл '{SOURCES_FILE}' пуст или не найден.")
        return

    print(f"Загружено ссылок: {len(urls)}")
    
    final_header = '#EXTM3U'
    epg_found = False
    total_channels_written = 0

    # Открываем итоговый файл для записи
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f_out:
        
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            # Проходим по ссылкам, i начинает с 1 (Плейлист - 1, Плейлист - 2...)
            for i, url in enumerate(urls, 1):
                group_name = f"Плейлист - {i}"
                
                try:
                    print(f"  Обработка [{i}/{len(urls)}]: {url}")
                    async with session.get(url, timeout=30) as response:
                        if response.status != 200:
                            print(f"    -> Ошибка: Сервер вернул код {response.status}")
                            continue
                            
                        content = await response.text()
                        
                        # Ищем EPG заголовок (только один раз, из первого успешного листа)
                        if not epg_found:
                            for line in content.splitlines():
                                if line.startswith('#EXTM3U') and 'url-tvg' in line:
                                    final_header = line.strip()
                                    epg_found = True
                                    break
                        
                        # Парсим каналы
                        channels = parse_m3u_channels(content)
                        
                        if not channels:
                            print("    -> Каналы не найдены (пустой лист или неверный формат)")
                            continue

                        # Записываем каналы в итоговый файл (только если это не первый проход - заголовок пишем в конце)
                        # Но так как мы пишем потоково, лучше сначала собрать буфер
                        # Для простоты: сразу пишем в файл каналы этой группы
                        
                        if i == 1:
                            # Если это первый плейлист, запишем заголовок в начало файла
                            f_out.seek(0)
                            f_out.write(f"{final_header}\n")
                        
                        for channel_name, channel_url in channels:
                            # ФОРМИРУЕМ СТРОКУ С ГРУППОЙ
                            # group-title="..." заставляет плеер создать "плашку" (категорию)
                            f_out.write(f'#EXTINF:-1 group-title="{group_name}",{channel_name}\n')
                            f_out.write(f'{channel_url}\n')
                        
                        print(f"    -> Успешно добавлено {len(channels)} каналов в группу '{group_name}'")
                        total_channels_written += len(channels)

                except Exception as e:
                    print(f"    -> СБОЙ: {e}")

    print("\n--- Готово ---")
    print(f"Итоговый файл: {OUTPUT_FILE}")
    print(f"Всего каналов: {total_channels_written}")

if __name__ == '__main__':
    asyncio.run(main())
