"""Явно демонстрационные предложения, не расписание авиакомпаний и не наличие номеров."""
from datetime import datetime, timedelta

CITIES = {
    "MOW": "Москва", "LED": "Санкт-Петербург", "AER": "Сочи",
    "KZN": "Казань", "SVX": "Екатеринбург", "KGD": "Калининград",
    "VVO": "Владивосток", "OVB": "Новосибирск",
}

# Маршрут, компания, HH:MM, длительность, базовая цена. Все записи — примеры.
FLIGHTS = [
    ("MOW", "LED", "Аэрофлот", "07:30", 90, 6200),
    ("MOW", "LED", "Победа", "12:10", 95, 3600),
    ("MOW", "LED", "Россия", "19:45", 90, 4900),
    ("LED", "MOW", "Аэрофлот", "08:20", 90, 6100),
    ("LED", "MOW", "Победа", "18:30", 95, 3800),
    ("MOW", "AER", "Аэрофлот", "06:15", 170, 10200),
    ("MOW", "AER", "S7 Airlines", "14:20", 175, 8700),
    ("AER", "MOW", "S7 Airlines", "10:00", 175, 9100),
    ("MOW", "KZN", "Аэрофлот", "09:00", 95, 5900),
    ("KZN", "MOW", "ЮТэйр", "13:15", 100, 5400),
    ("MOW", "SVX", "Уральские авиалинии", "11:05", 165, 10500),
    ("SVX", "MOW", "Уральские авиалинии", "15:50", 160, 10300),
    ("LED", "KGD", "Россия", "11:40", 115, 7200),
    ("KGD", "LED", "Россия", "16:30", 110, 7300),
    ("MOW", "OVB", "S7 Airlines", "09:55", 245, 14200),
    ("OVB", "MOW", "S7 Airlines", "18:05", 260, 14800),
    ("MOW", "VVO", "Аэрофлот", "20:45", 500, 24700),
    ("VVO", "MOW", "Аэрофлот", "08:20", 520, 25900),
]

# Справочник существующих гостиниц для работы при недоступности Overpass.
# Названия и адреса сверены с официальными сайтами отелей в октябре 2026 года.
# ЦЕНЫ ЗДЕСЬ НЕ ОТ ОТЕЛЕЙ: это только ориентировочные суммы для учебной системы.
# Формат: ID, город, название, адрес, категория (звёзды), расчётная цена,
#         сведения, описание, адрес, официальный сайт.
HOTELS = [
    ("verified-mow-smolenskaya", "Москва", "AZIMUT Сити Отель Смоленская Москва",
     "ул. Смоленская, 8", 4, 7100, "Условия проживания уточняйте у отеля",
     "Рядом с Арбатом и Смоленской площадью.", "ул. Смоленская, 8",
     "https://azimuthotels.com/ru/moscow/azimut-hotel-smolenskaya"),
    ("verified-mow-olympic", "Москва", "AZIMUT Сити Отель Олимпик Москва",
     "Олимпийский проспект, 18/1", 4, 6900, "Условия проживания уточняйте у отеля",
     "Отель в Мещанском районе Москвы.", "Олимпийский проспект, 18/1",
     "https://azimuthotels.com/ru"),
    ("verified-led-corinthia", "Санкт-Петербург", "Коринтия Санкт-Петербург",
     "Невский проспект, 57", 5, 11100, "Условия проживания уточняйте у отеля",
     "Гостиница на Невском проспекте.", "Невский проспект, 57",
     "https://www.corinthia.com/en-gb/st-petersburg/"),
    ("verified-led-azimut", "Санкт-Петербург", "AZIMUT Сити Отель Санкт-Петербург",
     "Лермонтовский проспект, 43/1", 4, 6200, "Условия проживания уточняйте у отеля",
     "Гостиница в Адмиралтейском районе.", "Лермонтовский проспект, 43/1",
     "https://azimuthotels.com/ru"),
    ("verified-aer-swissotel", "Сочи", "Swissôtel Resort Сочи Камелия",
     "Курортный проспект, 89", 5, 12800, "Условия проживания уточняйте у отеля",
     "Курортная гостиница у Чёрного моря.", "Курортный проспект, 89",
     "https://swiss-resort.com/"),
    ("verified-kzn-mirage", "Казань", "Отель Мираж",
     "ул. Московская, 5", 5, 7900, "Условия проживания уточняйте у отеля",
     "Отель в центре Казани.", "ул. Московская, 5",
     "https://mirage-hotel.ru/"),
    ("verified-svx-novotel", "Екатеринбург", "Novotel Екатеринбург Центр",
     "ул. Энгельса, 7", 4, 6800, "Условия проживания уточняйте у отеля",
     "Гостиница в центре Екатеринбурга.", "ул. Энгельса, 7",
     "https://novotel-ekb.ru/"),
    ("verified-kgd-radisson", "Калининград", "Radisson Blu Калининград",
     "площадь Победы, 10", 4, 8200, "Условия проживания уточняйте у отеля",
     "Гостиница на площади Победы.", "площадь Победы, 10",
     "https://www.radissonhotels.com/ru-ru/hotels/radisson-blu-kaliningrad"),
    ("verified-vvo-lotte", "Владивосток", "LOTTE HOTEL VLADIVOSTOK",
     "ул. Семёновская, 29", 5, 10900, "Условия проживания уточняйте у отеля",
     "Отель в центральной части Владивостока.", "ул. Семёновская, 29",
     "https://app.lottehotel.com/vladivostok-hotel/en"),
    ("verified-vvo-azimut", "Владивосток", "AZIMUT Сити Отель Владивосток",
     "ул. Набережная, 10", 4, 6800, "Условия проживания уточняйте у отеля",
     "Гостиница с видом на Амурский залив.", "ул. Набережная, 10",
     "https://azimuthotels.com/ru/vladivostok/azimut-hotel-vladivostok"),
    ("verified-ovb-doubletree", "Новосибирск", "DoubleTree by Hilton Novosibirsk",
     "ул. Каменская, 7/1", 4, 7900, "Условия проживания уточняйте у отеля",
     "Гостиница рядом с театром «Глобус».", "ул. Каменская, 7/1",
     "https://www.hilton.com/en/hotels/ovbdtdi-doubletree-novosibirsk/"),
]


def demo_flights(origin: str, destination: str, day: str):
    departure_day = datetime.strptime(day, "%Y-%m-%d")
    results = []
    for i, (start, end, airline, hhmm, duration, price) in enumerate(FLIGHTS):
        if (start, end) != (origin, destination):
            continue
        departure = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")
        arrival = departure + timedelta(minutes=duration)
        # Детерминированная цена: повторный запрос возвращает тот же результат.
        factor = 1 + ((departure_day.toordinal() + i) % 7) * 0.025
        results.append({
            "id": f"{origin}{destination}-{day.replace('-', '')}-{i:02d}",
            "origin": origin, "destination": destination, "airline": airline,
            "departure": departure.isoformat(timespec="minutes"),
            "arrival": arrival.isoformat(timespec="minutes"),
            "duration_min": duration, "price": int(round(price * factor / 10) * 10),
            "currency": "RUB", "demo": True,
        })
    return sorted(results, key=lambda flight: flight["price"])
