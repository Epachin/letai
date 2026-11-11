"""Адаптер публичного Travelpayouts Aviasales Data API.

Эндпоинт возвращает найденные ранее цены из кэша поисков, а не билеты,
которые можно выписать через наш микросервис.
"""
import hashlib
import json
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from common.validation import InputError

PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AIRLINES = {
    "SU": "Аэрофлот", "DP": "Победа", "FV": "Россия", "S7": "S7 Airlines",
    "U6": "Уральские авиалинии", "UT": "ЮТэйр", "N4": "Nordwind",
    "WZ": "Red Wings", "5N": "Smartavia", "R3": "Якутия",
}


def search_prices(origin, destination, day, token, return_day=None):
    """Вернуть найденные цены. Пустая выдача API никогда не заменяется локальным каталогом."""
    if not token:
        raise InputError("Не указан TRAVELPAYOUTS_TOKEN")
    query = {
        "origin": origin, "destination": destination,
        "departure_at": day, "one_way": "false" if return_day else "true", "direct": "false",
        "sorting": "price", "currency": "rub", "limit": "30",
        "page": "1", "market": "ru",
    }
    if return_day:
        query["return_at"] = return_day
    params = urlencode(query)
    request = Request(f"{PRICES_URL}?{params}", headers={
        "X-Access-Token": token,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "SkyWay-Academic/1.0",
    })
    try:
        with urlopen(request, timeout=9) as response:
            body = json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise InputError("Travelpayouts отклонил токен или доступ к API") from exc
        if exc.code == 429:
            raise InputError("Travelpayouts ограничил число запросов. Повторите позже") from exc
        raise InputError(f"Ошибка сервиса авиапредложений (HTTP {exc.code})") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise InputError("Не удалось связаться с Travelpayouts. Проверьте интернет") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise InputError("Travelpayouts вернул некорректные данные") from exc

    if not isinstance(body, dict) or body.get("success") is not True:
        raise InputError("Travelpayouts не смог выполнить поиск. Попробуйте другую дату")
    raw_offers = body.get("data", [])
    if not isinstance(raw_offers, list):
        raise InputError("Неожиданный формат ответа Travelpayouts")
    if str(body.get("currency", "rub")).lower() != "rub":
        raise InputError("Travelpayouts вернул цены не в рублях")

    offers = []
    for item in raw_offers:
        if not isinstance(item, dict):
            continue
        try:
            departure_text = str(item["departure_at"]).replace("Z", "+00:00")
            departure = datetime.fromisoformat(departure_text)
            if departure.date().isoformat() != day:
                continue
            if item.get("origin", origin) != origin or item.get("destination", destination) != destination:
                continue
            price = int(item["price"])
            duration = int(item.get("duration_to") or item.get("duration"))
            transfers = int(item.get("transfers", 0))
            if price <= 0 or duration <= 0 or transfers < 0:
                continue
            back_at = ""
            back_duration = 0
            if return_day:
                raw_back = str(item.get("return_at") or "").replace("Z", "+00:00")
                if not raw_back:
                    continue
                parsed_back = datetime.fromisoformat(raw_back)
                if parsed_back.date().isoformat() != return_day:
                    continue
                back_at = parsed_back.isoformat(timespec="minutes")
                back_duration = int(item.get("duration_back") or 0)
            airline_code = str(item.get("airline") or "").upper().strip()
            flight_number = str(item.get("flight_number") or "").strip()
            if not airline_code:
                continue
            airline_title = AIRLINES.get(airline_code, airline_code)
            airline = f"{airline_title} · {airline_code}{flight_number}" if flight_number else airline_title
            raw_link = str(item.get("link") or "")
            link = urljoin("https://www.aviasales.ru", raw_link) if raw_link.startswith("/") else ""
            if link and urlparse(link).hostname != "www.aviasales.ru":
                link = ""
            offer_key = (f"{origin}|{destination}|{departure.isoformat()}|{back_at}|"
                         f"{airline}|{price}|{transfers}")
            offer_id = "TP-" + hashlib.sha256(offer_key.encode("utf-8")).hexdigest()[:20].upper()
            # Разница часовых поясов аэропортов из Data API неизвестна.
            # Поле arrival нужно для хранения, UI показывает только время вылета и длительность.
            arrival = departure + timedelta(minutes=duration)
            offers.append({
                "id": offer_id, "origin": origin, "destination": destination,
                "airline": airline, "airline_name": airline_title,
                "departure": departure.isoformat(timespec="minutes"),
                "arrival": arrival.isoformat(timespec="minutes"),
                "duration_min": duration, "price": price, "currency": "RUB",
                "transfers": transfers, "link": link, "demo": False,
                "return_departure": back_at,
                "return_airline": "", "return_duration_min": back_duration,
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(offers, key=lambda offer: offer["price"])
