
from datetime import date, timedelta
from common.broker import rpc

# Дата вылета через 20 дней
flight_date = (date.today() + timedelta(days=20)).isoformat()

# Отправка запроса в RabbitMQ
response = rpc(
    "travel.flights.requests",
    {
        "action": "search",
        "origin": "MOW",
        "destination": "LED",
        "date": flight_date
    }
)

print("Статус:", response.get("status"))
print("Источник:", response.get("source"))

if response.get("status") == "ok":
    flights = response.get("flights", [])
    print("Найдено рейсов:", len(flights))

    for flight in flights[:5]:
        print(
            flight["airline"],
            flight["departure"],
            flight["price"], "руб."
        )
else:
    print("Ошибка:", response.get("error"))
