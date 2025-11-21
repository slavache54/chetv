import asyncio
import aiohttp
import os

# --- НАСТРОЙКИ ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'master_playlist.m3u'
TIMEOUT_SECONDS = 30 # Увеличили время ожидания для медленных серверов

# Маскируемся под VLC плеер
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
            # Чистим от кавычек и лишнего
            url = line.replace('"', '').replace("'", "").strip()
            # Если пользователь оставил запятые (старый формат), берем часть после запятой
            if ',' in url:
                url = url.split(',', 1)[1].strip()
            if url:
                urls.append(url)
    return urls

def parse_channels_robust(content):
    """
    Надежный парсер, который читает файл построчно.
    Не ломается из-за лишних тегов (#EXTGRP, #EXTVLCOPT и т.д.)
    """
    channels = []
    current_name = None
    
    # Разбиваем на строки
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            # Попытка извлечь имя канала (всё что после запятой)
            # Формат обычно: #EXTINF:-1 key="value",Название Канала
            parts = line.split(',', 1)
            if len(parts) > 1:
                current_name = parts[1].strip()
            else:
                current_name = "Без названия"
        
        elif line.startswith('#'):
            # Игнорируем другие теги типа #EXTGRP, чтобы они не сбили нас
            continue
            
        else:
            # Если строка не начинается с #, мы считаем её ссылкой (URL)
            url = line
            name = current_name if current_name else "Канал без названия"
            
            channels.append({'name': name, 'url': url})
            
            # Сбрасываем имя, чтобы следующая ссылка не получила это же имя
            # (если вдруг в плейлисте идет URL без EXTINF)
            current_name = None
            
    return channels

async def fetch_playlist(session, url, index):
    """Скачивает плейлист и возвращает (index, channels)."""
    try:
        print(f"  Скачивание [{index}]: {url}")
        async with session.get(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                print(f"    X Ошибка {index}: Код {response.status}")
                return index, []
            
            # Используем errors='replace', чтобы не упасть на кривой кодировке
            content = await response.text(encoding='utf-8', errors='replace')
            channels = parse_channels_robust(content)
            
            if not channels:
                print(f"    ! Предупреждение {index}: Плейлист пуст или не распознан.")
            else:
                print(f"    V Успех {index}: найдено {len(channels)} каналов.")
                
            return index, channels
            
    except Exception as e:
        print(f"    X Сбой {index}: {e}")
        return index, []

async def main():
    print("--- Запуск СТРОГОЙ сборки (Правильный порядок + Надежный парсер) ---")
    
    urls = load_source_urls()
    if not urls:
        print("Файл sources.txt пуст!")
        return

    tasks = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Создаем задачи для скачивания. index начинается с 1
        for i, url in enumerate(urls, 1):
            task = asyncio.create_task(fetch_playlist(session, url, i))
            tasks.append(task)
        
        # Ждем завершения всех загрузок
        results = await asyncio.gather(*tasks)

    # Важный момент: результаты могут вернуться в разнобой.
    # Нам нужно отсортировать их по индексу (1, 2, 3...), чтобы сохранить порядок.
    results.sort(key=lambda x: x[0])

    # Запись в файл
    total_written = 0
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n") # Пишем заголовок один раз
        
        for index, channels in results:
            group_title = f"Плейлист - {index}"
            
            for ch in channels:
                # Мы сами формируем строку #EXTINF заново, принудительно ставя нашу группу
                # Удаляем запятые из имени, чтобы не ломать формат M3U (на всякий случай)
                safe_name = ch['name'].replace('\n', ' ').strip()
                
                # Формат: #EXTINF:-1 group-title="Плейлист - N",Название
                f.write(f'#EXTINF:-1 group-title="{group_title}",{safe_name}\n')
                f.write(f"{ch['url']}\n")
                total_written += 1

    print(f"\nГотово! Сохранено в {OUTPUT_FILE}")
    print(f"Всего каналов: {total_written}")
    print(f"Обработано источников: {len(urls)}")

if __name__ == '__main__':
    asyncio.run(main())
