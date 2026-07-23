import json
import os
import random
import threading
import time
import requests
from bs4 import BeautifulSoup
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

# ================= КОНФИГУРАЦИЯ =================
# Токен вашей группы ВКонтакте
VK_TOKEN = "4f4b3087ffe983731d3c9bbefde89cf90bcff80a55595299c438bf2cfc88c77b6cbb7b1a1031349182e86"

# Ваш цифровой ID ВКонтакте (куда будут приходить автоматические уведомления)
# Его можно узнать, например, отправив любое сообщение запущенному боту — он выведет его в консоль.
ADMIN_VK_ID = 588085501  # Замените на ваш числовой ID

# Интервал проверки в секундах (1800 секунд = 30 минут)
CHECK_INTERVAL = 1800

# URL страницы абитуриента 2227887
TARGET_URL = "https://abiturient.unn.ru/list/abit.php?id=281474976968093"
# ================================================

STATE_FILE = "last_state.json"
state_lock = threading.Lock()


def load_state():
    """Загружает сохраненное ранее состояние из файла."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка при загрузке состояния: {e}")
            return {}
    return {}


def save_state(state):
    """Сохраняет текущее состояние в файл."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка при сохранении состояния: {e}")


def parse_applicant_data(url):
    """Парсит страницу абитуриента и возвращает список словарей с направлениями."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"Ошибка при запросе к сайту: статус {response.status_code}"
    except Exception as e:
        return f"Не удалось подключиться к сайту: {e}"

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", {"id": "jtable"})

    if not table:
        return "Таблица со статистикой не найдена на странице."

    tbody = table.find("tbody")
    if not tbody:
        return "Строки таблицы не найдены."

    rows = tbody.find_all("tr")
    results = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 11:
            style_attr = row.get("style", "")
            is_recommended = "#e2e51e" in style_attr

            num = cols[0].text.strip()
            direction = cols[1].text.strip()
            faculty = cols[2].text.strip()
            form = cols[3].text.strip()
            fin_source = cols[4].text.strip()
            priority = cols[5].text.strip()
            score = cols[6].text.strip()
            places = cols[7].text.strip()
            status = cols[8].text.strip()
            if_consent = cols[9].text.strip()
            position = cols[10].text.strip()

            results.append(
                {
                    "num": num,
                    "direction": direction,
                    "faculty": faculty,
                    "form": form,
                    "fin_source": fin_source,
                    "priority": priority,
                    "score": score,
                    "places": places,
                    "status": status,
                    "if_consent": if_consent,
                    "position": position,
                    "is_recommended": is_recommended,
                }
            )

    return results


def check_for_updates(current_data, last_state):
    """Сравнивает текущие данные со старыми и находит изменения."""
    changes = []
    new_state = {}

    for item in current_data:
        dir_name = item["direction"]
        pos = item["position"]
        consent = item["if_consent"]

        new_state[dir_name] = {"position": pos, "if_consent": consent}

        # Если это направление уже проверялось ранее
        if dir_name in last_state:
            old_pos = last_state[dir_name].get("position")
            old_consent = last_state[dir_name].get("if_consent")

            pos_changed = old_pos != pos
            consent_changed = old_consent != consent

            if pos_changed or consent_changed:
                changes.append(
                    {
                        "direction": dir_name,
                        "old_pos": old_pos,
                        "new_pos": pos,
                        "old_consent": old_consent,
                        "new_consent": consent,
                    }
                )

    return changes, new_state


def format_changes_message(changes):
    """Форматирует сообщение об изменениях в положении."""
    msg = "⚠️ *Внимание! Изменилось ваше положение в списках!*\n\n"
    for c in changes:
        msg += f"📘 *{c['direction']}*\n"
        if c["old_pos"] != c["new_pos"]:
            msg += f"  • Положение в списке: {c['old_pos']} ➡️ {c['new_pos']}\n"
        if c["old_consent"] != c["new_consent"]:
            msg += f"  • Если подам согласие: {c['old_consent']} ➡️ {c['new_consent']}\n"
        msg += "\n"
    return msg


def format_status_message(data):
    """Форматирует полную сводку по запросу."""
    if isinstance(data, str):
        return data

    msg = "📊 *Текущая статистика поданных заявлений:*\n\n"
    for item in data:
        recom_tag = (
            "⭐ *[ПРОХОДИТ ПРИ ПОДАЧЕ СОГЛАСИЯ]*"
            if item["is_recommended"]
            else ""
        )
        msg += (
            f"🔹 *№ {item['num']}: {item['direction']}* {recom_tag}\n"
            f" 🏛 Факультет: {item['faculty']}\n"
            f" 📋 Форма обучения: {item['form']} ({item['fin_source']})\n"
            f" 🎯 Приоритет: {item['priority']}\n"
            f" 📝 Сумма баллов: {item['score']}\n"
            f" 👥 Мест в плане набора: {item['places']}\n"
            f" ⚡ Статус: {item['status']}\n"
            f" 🟢 Положение, если подаст согласие: {item['if_consent']}\n"
            f" 📈 Текущее
