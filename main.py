import json
import os
import random
import threading
import time
import requests
from bs4 import BeautifulSoup
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

# --- Selenium 相关导入 ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= КОНФИГУРАЦИЯ =================
VK_TOKEN = "4f4b3087ffe983731d3c9bbefde89cf90bcff80a55595299c438bf2cfc88c77b6cbb7b1a1031349182e86"
ADMIN_VK_ID = 588085501
CHECK_INTERVAL = 1800

# --- Новые URL для парсинга ---
TARGET_URLS = [
    "https://abit.susu.ru/rating/?type=green&id=163",
    "https://abit.susu.ru/rating/?type=green&id=170",
    "https://abit.susu.ru/rating/?type=green&id=180",
    "https://abit.susu.ru/rating/?type=green&id=148",
    "https://abit.susu.ru/rating/?type=green&id=150",
]

# Ваш суммарный балл для поиска в таблице
MY_SCORE = 228
# ================================================

STATE_FILE = "last_state.json"
state_lock = threading.Lock()
driver = None  # Глобальный драйвер Selenium

def get_driver():
    """Инициализирует и возвращает драйвер Selenium."""
    global driver
    if driver is None:
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Запуск в фоновом режиме
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def parse_applicant_data_with_selenium(url):
    """
    Использует Selenium для загрузки страницы, ожидает появления таблицы
    и парсит строки с абитуриентами.
    Возвращает список словарей или сообщение об ошибке.
    """
    try:
        driver = get_driver()
        driver.get(url)
        
        # Ожидаем появления тела таблицы (tbody)
        wait = WebDriverWait(driver, 20)
        tbody = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody")))
        
        # Получаем HTML таблицы после рендеринга
        table_html = tbody.get_attribute("outerHTML")
        soup = BeautifulSoup(table_html, "html.parser")
        rows = soup.find_all("tr")
        
        results = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 8:  # Минимальное количество колонок
                # Извлекаем данные из колонок
                # Индексы могут варьироваться, ориентируемся на структуру:
                # 0: Позиция, 1: Рег. номер, 2: Тип места, 3: Сумма оценок, ...
                position = cols[0].text.strip()
                reg_num = cols[1].text.strip() if len(cols) > 1 else ""
                place_type = cols[2].text.strip() if len(cols) > 2 else ""
                score = cols[3].text.strip() if len(cols) > 3 else ""
                # ... остальные поля по необходимости
                
                results.append({
                    "position": position,
                    "reg_num": reg_num,
                    "place_type": place_type,
                    "score": score,
                    # Можно добавить другие поля
                })
        return results
    except Exception as e:
        return f"Ошибка при парсинге {url}: {e}"

def find_my_position(data, my_score=MY_SCORE):
    """
    Ищет в данных абитуриента с указанным баллом.
    Возвращает словарь с информацией о позиции или None.
    """
    for item in data:
        if isinstance(item, dict) and item.get("score", "").isdigit():
            if int(item["score"]) == my_score:
                return item
    return None

def check_for_updates(current_data, last_state, url):
    """Сравнивает текущие данные со старыми для конкретного URL."""
    changes = []
    new_state = {}
    
    my_entry = find_my_position(current_data)
    if my_entry:
        new_state[url] = my_entry
        if url in last_state:
            old_entry = last_state[url]
            if old_entry.get("position") != my_entry.get("position"):
                changes.append({
                    "url": url,
                    "old_pos": old_entry.get("position"),
                    "new_pos": my_entry.get("position"),
                    "score": my_entry.get("score")
                })
    else:
        new_state[url] = {"position": "Не найден", "score": str(MY_SCORE)}
        if url in last_state and last_state[url].get("position") != "Не найден":
            changes.append({
                "url": url,
                "old_pos": last_state[url].get("position"),
                "new_pos": "Не найден",
                "score": str(MY_SCORE)
            })
    return changes, new_state

def format_changes_message(changes):
    """Форматирует сообщение об изменениях."""
    if not changes:
        return None
    msg = "⚠️ *Внимание! Изменилась ваша позиция!*\n\n"
    for c in changes:
        msg += f"🔗 Направление: {c['url']}\n"
        msg += f"   • Баллы: {c['score']}\n"
        msg += f"   • Позиция: {c['old_pos']} ➡️ {c['new_pos']}\n\n"
    return msg

def format_status_message(all_data):
    """Форматирует текущий статус по всем направлениям."""
    msg = "📊 *Текущая статистика по вашим направлениям:*\n\n"
    for url, data in all_data.items():
        msg += f"🔗 {url}\n"
        if isinstance(data, dict):
            pos = data.get("position", "Н/Д")
            score = data.get("score", "Н/Д")
            msg += f"   • Ваши баллы: {score}\n"
            msg += f"   • Позиция в списке: {pos}\n"
        else:
            msg += f"   • Ошибка: {data}\n"
        msg += "\n"
    return msg

def background_checker(vk):
    """Фоновая проверка с интервалом CHECK_INTERVAL."""
    print("Фоновый поток мониторинга запущен.")
    while True:
        try:
            with state_lock:
                last_state = load_state()
                all_changes = []
                all_new_state = {}
                
                for url in TARGET_URLS:
                    parsed_data = parse_applicant_data_with_selenium(url)
                    if isinstance(parsed_data, str):
                        print(f"Ошибка для {url}: {parsed_data}")
                        all_new_state[url] = parsed_data
                        continue
                    
                    changes, new_state = check_for_updates(parsed_data, last_state, url)
                    all_changes.extend(changes)
                    all_new_state.update(new_state)
                
                if last_state and all_changes:
                    notification = format_changes_message(all_changes)
                    if notification:
                        vk.messages.send(
                            user_id=ADMIN_VK_ID,
                            message=notification,
                            random_id=random.getrandbits(31),
                        )
                        print("Уведомление об изменениях отправлено.")
                elif not last_state:
                    print("Первый запуск: базовое состояние сохранено.")
                
                save_state(all_new_state)
        except Exception as e:
            print(f"Исключение в фоновом потоке: {e}")
        
        time.sleep(CHECK_INTERVAL)

def main():
    global driver
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()
        longpoll = VkLongPoll(vk_session)
        print("Бот запущен и слушает сообщения...")
    except Exception as e:
        print(f"Ошибка авторизации ВКонтакте: {e}")
        return

    # Запускаем фоновую проверку
    checker_thread = threading.Thread(target=background_checker, args=(vk,), daemon=True)
    checker_thread.start()

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            user_msg = event.text.lower().strip()
            print(f"Сообщение от {event.user_id}: {event.text}")
            
            if user_msg in ["старт", "привет", "статус", "обновить"]:
                vk.messages.send(
                    user_id=event.user_id,
                    message="Запрашиваю актуальные данные со всех направлений...",
                    random_id=random.getrandbits(31),
                )
                
                all_data = {}
                for url in TARGET_URLS:
                    parsed_data = parse_applicant_data_with_selenium(url)
                    if isinstance(parsed_data, str):
                        all_data[url] = parsed_data
                    else:
                        my_entry = find_my_position(parsed_data)
                        all_data[url] = my_entry if my_entry else {"position": "Не найден", "score": str(MY_SCORE)}
                
                response_message = format_status_message(all_data)
                vk.messages.send(
                    user_id=event.user_id,
                    message=response_message,
                    random_id=random.getbits(31),
                )
                
                # Сохраняем состояние
                with state_lock:
                    _, new_state = check_for_updates(parsed_data, {}, url)  # Упрощенно
                    save_state(new_state)
            else:
                vk.messages.send(
                    user_id=event.user_id,
                    message="Отправьте 'статус' или 'обновить' для получения данных.",
                    random_id=random.getbits(31),
                )

if __name__ == "__main__":
    main()
