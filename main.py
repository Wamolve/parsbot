import random
import requests
from bs4 import BeautifulSoup
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

# Токен вашей группы ВКонтакте (вставьте сюда ваш актуальный токен)
VK_TOKEN = "4f4b3087ffe983731d3c9bbefde89cf90bcff80a55595299c438bf2cfc88c77b6cbb7b1a1031349182e86"

# URL страницы абитуриента 2227887
TARGET_URL = "https://abiturient.unn.ru/list/abit.php?id=281474976968093"


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
        response = requests.get(url, headers=headers, timeout=10)
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
            # Проверяем, выделено ли направление желтым цветом (текущий проход по конкурсу)
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


def format_message(data):
    """Форматирует спарсенные данные в удобное текстовое сообщение для ВК."""
    if isinstance(data, str):
        return data  # Возвращаем текст ошибки, если парсинг не удался

    msg = "📊 *Статистика заявлений абитуриента 2227887:*\n\n"

    for item in data:
        # Если направление выделено цветом, добавляем пометку
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
            f" 📈 Текущее положение в списке: {item['position']}\n\n"
        )
    return msg


def main():
    # Авторизация в VK API
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()
        longpoll = VkLongPoll(vk_session)
        print("Бот успешно запущен и слушает сообщения...")
    except Exception as e:
        print(f"Ошибка авторизации ВКонтакте: {e}")
        return

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            user_msg = event.text.lower().strip()

            if user_msg in ["старт", "привет", "статус", "2227887", "обновить"]:
                # Отправляем предварительное сообщение (random_id на 31 бит)
                vk.messages.send(
                    user_id=event.user_id,
                    message="Запрашиваю актуальные данные с сайта ННГУ...",
                    random_id=random.getrandbits(31)
                )

                # Парсинг данных
                parsed_data = parse_applicant_data(TARGET_URL)
                response_message = format_message(parsed_data)

                # Отправка результата (random_id на 31 бит)
                vk.messages.send(
                    user_id=event.user_id,
                    message=response_message,
                    random_id=random.getrandbits(31)
                )
            else:
                # Ответ-подсказка (random_id на 31 бит)
                vk.messages.send(
                    user_id=event.user_id,
                    message="Отправьте слово 'статус' или 'обновить', чтобы получить данные по абитуриенту 2227887.",
                    random_id=random.getrandbits(31)
                )


if __name__ == "__main__":
    main()