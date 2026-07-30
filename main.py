import json
import os
import random
import threading
import time
import requests
from bs4 import BeautifulSoup
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

# --- Selenium ---
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

TARGET_URLS = [
    "https://abit.susu.ru/rating/?type=green&id=163",
    "https://abit.susu.ru/rating/?type=green&id=170",
    "https://abit.susu.ru/rating/?type=green&id=180",
    "https://abit.susu.ru/rating/?type=green&id=148",
    "https://abit.susu.ru/rating/?type=green&id=150",
]

MY_SCORE = 228
# ================================================

STATE_FILE = "last_state.json"
state_lock = threading.Lock()
driver = None

# ---------- Функции состояния (были в оригинале) ----------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки состояния: {e}")
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения состояния: {e}")

# ---------- Selenium драйвер ----------
def get_driver():
    global driver
    if driver is None:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# ---------- Парсинг ----------
def parse_applicant_data_with_selenium(url):
    try:
        driver = get_driver()
        driver.get(url)
        wait = WebDriverWait(driver, 20)
        tbody = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody")))
        table_html = tbody.get_attribute("outerHTML")
        soup = BeautifulSoup(table_html, "html.parser")
        rows = soup.find_all("tr")
        results = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 8:
                results.append({
                    "position": cols[0].text.strip(),
                    "reg_num": cols[1].text.strip() if len(cols) > 1 else "",
                    "place_type": cols[2].text.strip() if len(cols) > 2 else "",
                    "score": cols[3].text.strip() if len(cols) > 3 else "",
                })
        return results
    except Exception as e:
        return f"Ошибка при парсинге {url}: {e}"

def find_my_position(data):
    for item in data:
        if isinstance(item, dict) and item.get("score", "").isdigit():
            if int(item["score"]) == MY_SCORE:
                return item
    return None

def check_for_updates(current_data, last_state, url):
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
    if not changes:
        return None
    msg = "⚠️ *Внимание! Изменилась ваша позиция!*\n\n"
    for c in changes:
        msg += f"🔗 Направление: {c['url']}\n"
        msg += f"   • Баллы: {c['score']}\n"
        msg += f"   • Позиция: {c['old_pos']} ➡️ {c['new_pos']}\n\n"
    return msg

def format_status_message(all_data):
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

# ---------- Фоновый поток ----------
def background_checker(vk):
    print("Фоновый поток мониторинга запущен.")
    while True:
        try:
            with state_lock:
                last_state = load_state()
                all_changes = []
                all_new_state = {}
                for url in TARGET_URLS:
                    parsed = parse_applicant_data_with_selenium(url)
                    if isinstance(parsed, str):
                        print(f"Ошибка для {url}: {parsed}")
                        all_new_state[url] = parsed
                        continue
                    changes, new_state = check_for_updates(parsed, last_state, url)
                    all_changes.extend(changes)
                    all_new_state.update(new_state)
                if last_state and all_changes:
                    notif = format_changes_message(all_changes)
                    if notif:
                        vk.messages.send(
                            user_id=ADMIN_VK_ID,
                            message=notif,
                            random_id=random.getrandbits(31)
                        )
                        print("Уведомление отправлено.")
                elif not last_state:
                    print("Первый запуск: состояние сохранено.")
                save_state(all_new_state)
        except Exception as e:
            print(f"Исключение в фоновом потоке: {e}")
        time.sleep(CHECK_INTERVAL)

# ---------- Основной цикл ----------
def main():
    global driver
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()
        longpoll = VkLongPoll(vk_session)
        print("Бот запущен и слушает сообщения...")
    except Exception as e:
        print(f"Ошибка авторизации ВК: {e}")
        return

    checker_thread = threading.Thread(target=background_checker, args=(vk,), daemon=True)
    checker_thread.start()

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            user_msg = event.text.lower().strip()
            print(f"Сообщение от {event.user_id}: {event.text}")
            if user_msg in ["старт", "привет", "статус", "обновить"]:
                vk.messages.send(
                    user_id=event.user_id,
                    message="Запрашиваю данные со всех направлений...",
                    random_id=random.getrandbits(31)
                )
                all_data = {}
                for url in TARGET_URLS:
                    parsed = parse_applicant_data_with_selenium(url)
                    if isinstance(parsed, str):
                        all_data[url] = parsed
                    else:
                        entry = find_my_position(parsed)
                        all_data[url] = entry if entry else {"position": "Не найден", "score": str(MY_SCORE)}
                response = format_status_message(all_data)
                vk.messages.send(
                    user_id=event.user_id,
                    message=response,
                    random_id=random.getrandbits(31)
                )
                # Сохраняем состояние для каждого URL
                with state_lock:
                    last_state = load_state()
                    new_state = {}
                    for url in TARGET_URLS:
                        parsed = parse_applicant_data_with_selenium(url)
                        if not isinstance(parsed, str):
                            _, ns = check_for_updates(parsed, last_state, url)
                            new_state.update(ns)
                    save_state(new_state)
            else:
                vk.messages.send(
                    user_id=event.user_id,
                    message="Отправьте 'статус' или 'обновить'.",
                    random_id=random.getrandbits(31)
                )

if __name__ == "__main__":
    main()
