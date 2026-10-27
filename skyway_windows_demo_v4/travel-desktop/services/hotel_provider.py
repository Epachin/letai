"""Получение настоящих объектов размещения из OpenStreetMap (Overpass API).

Overpass не сообщает цены, наличие комнат и условия бронирования.
Вызов выполняется только по запросу пользователя; повторные запросы кэширует HotelService.
"""
import json
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from common import config


# Центры поддерживаемых городов, приблизительные координаты в WGS84.
CITY_CENTERS = {
    "Москва": (55.7558, 37.6173),
    "Санкт-Петербург": (59.9343, 30.3351),
    "Сочи": (43.5855, 39.7231),
    "Казань": (55.7961, 49.1064),
    "Екатеринбург": (56.8389, 60.6057),
    "Калининград": (54.7104, 20.4522),
    "Владивосток": (43.1155, 131.8855),
    "Новосибирск": (55.0084, 82.9357),
}


def hotel_from_osm(item, city):
    tags = item.get("tags") or {}
    hotel_name = str(tags.get("name:ru") or tags.get("name") or "").strip()
    if not hotel_name:
        return None
    kind = str(item.get("type") or "")
    osm_id = item.get("id")
    if kind not in ("node", "way", "relation") or not isinstance(osm_id, int):
        return None
    coordinates = item.get("center") or item
    lat, lon = coordinates.get("lat"), coordinates.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    street = str(tags.get("addr:street") or "").strip()
    house = str(tags.get("addr:housenumber") or "").strip()
    address = ", ".join(part for part in (street, house) if part) or city
    raw_stars = str(tags.get("stars") or "").strip().split(";")[0]
    try:
        stars = int(raw_stars)
    except ValueError:
        stars = 0
    if stars not in range(1, 6):
        stars = 0
    amenities = []
    if tags.get("internet_access") in ("wlan", "yes"):
        amenities.append("Wi-Fi")
    if tags.get("wheelchair") == "yes":
        amenities.append("Доступная среда")
    if tags.get("parking") == "yes":
        amenities.append("Парковка")
    if tags.get("swimming_pool") == "yes":
        amenities.append("Бассейн")
    website = str(tags.get("website") or tags.get("contact:website") or "").strip()
    if urlparse(website).scheme not in ("https", "http"):
        website = ""
    # Это только ориентир для интерфейса студенческого проекта, не тариф отеля.
    nightly_estimate = {0: 4500, 1: 2700, 2: 3400, 3: 4600, 4: 7400, 5: 12200}[stars]
    return {
        "id": f"osm-{kind[0]}-{osm_id}", "city": city, "name": hotel_name[:180],
        "district": address[:180], "rating": stars, "nightly_price": nightly_estimate,
        "amenities": ", ".join(amenities) if amenities else "Уточните удобства у гостиницы",
        "description": f"Адрес: {address}"[:300], "address": address[:250],
        "website": website[:450], "latitude": float(lat), "longitude": float(lon),
        "source": "osm",
    }


def search_osm_hotels(city):
    """Не более одного запроса на город; ответ из Overpass до 60 именованных объектов."""
    if city not in CITY_CENTERS:
        raise ValueError("Город не поддерживается")
    lat, lon = CITY_CENTERS[city]
    query = (f'[out:json][timeout:9];'
             f'nwr["tourism"="hotel"]["name"](around:6500,{lat},{lon});'
             'out center 40;')
    # GET поддерживается Overpass и реже блокируется прокси, чем POST.
    url = config.HOTEL_OSM_URL + "?" + urlencode({"data": query})
    req = Request(url,
                  headers={"User-Agent": "SkyWayCourseProject/1.0 (hotel lookup; educational)",
                           "Accept": "application/json"}, method="GET")
    with urlopen(req, timeout=11) as response:
        body = response.read(1_500_001)
    if len(body) > 1_500_000:
        raise ValueError("Слишком большой ответ каталога гостиниц")
    parsed = json.loads(body.decode("utf-8"))
    if "elements" not in parsed or not isinstance(parsed["elements"], list):
        raise ValueError("Некорректный ответ каталога гостиниц")
    hotels = [hotel_from_osm(item, city) for item in parsed["elements"]]
    return sorted((h for h in hotels if h), key=lambda h: (-h["rating"], h["name"]))[:60]
