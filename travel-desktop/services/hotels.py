"""Микросервис №2: каталог реальных отелей OSM и локальные бронирования."""
from datetime import datetime, timedelta, timezone
import time
from uuid import uuid4

from common.db import now, reading, rows, transaction, upsert_user
from common.validation import InputError, email, name, parse_day, positive_int, require
from services.hotel_provider import CITY_CENTERS, search_osm_hotels


class HotelService:
    def __init__(self):
        self.next_online_attempt = 0.0

    def handle(self, request):
        action = request.get("action")
        if action == "cities":
            return {"status": "ok", "cities": sorted(CITY_CENTERS)}

        if action == "search":
            city = require(request.get("city"), "город", 80)
            check_in = parse_day(request.get("check_in"), "заезд")
            check_out = parse_day(request.get("check_out"), "выезд")
            nights = (check_out - check_in).days
            if not 1 <= nights <= 30:
                raise InputError("Выберите срок проживания от 1 до 30 ночей")
            guests = positive_int(request.get("guests", 1), "гостей", 4)
            if city not in CITY_CENTERS:
                raise InputError("Выберите город из списка")
            with reading() as con:
                cached = con.execute("SELECT fetched_at FROM hotel_lookup_cache WHERE city=?",
                                     (city,)).fetchone()
                cached_count = con.execute("SELECT COUNT(*) FROM hotels WHERE city=? AND source='osm'",
                                           (city,)).fetchone()[0]
            use_cached = bool(cached and cached_count and
                datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"]) < timedelta(hours=24))
            warning = ""
            if not use_cached:
                if time.monotonic() >= self.next_online_attempt:
                    try:
                        found = search_osm_hotels(city)
                        if not found:
                            raise ValueError("Не найдено объектов с названиями")
                        with transaction() as con:
                            con.executemany("""INSERT INTO hotels
                                (id,city,name,district,rating,nightly_price,amenities,description,
                                 source,address,website,latitude,longitude)
                                VALUES (:id,:city,:name,:district,:rating,:nightly_price,:amenities,
                                        :description,:source,:address,:website,:latitude,:longitude)
                                ON CONFLICT(id) DO UPDATE SET
                                  name=excluded.name,city=excluded.city,district=excluded.district,
                                  rating=excluded.rating,nightly_price=excluded.nightly_price,
                                  amenities=excluded.amenities,description=excluded.description,
                                  source=excluded.source,address=excluded.address,
                                  website=excluded.website,latitude=excluded.latitude,
                                  longitude=excluded.longitude""", found)
                            con.execute("""INSERT INTO hotel_lookup_cache(city,fetched_at,item_count)
                                VALUES(?,?,?) ON CONFLICT(city) DO UPDATE SET
                                fetched_at=excluded.fetched_at,item_count=excluded.item_count""",
                                (city, now(), len(found)))
                        cached_count = len(found)
                    except (OSError, ValueError, TimeoutError):
                        self.next_online_attempt = time.monotonic() + 600
                        warning = "Онлайн-каталог не ответил. Показан справочник существующих гостиниц."
                else:
                    warning = "Онлайн-каталог временно недоступен. Показан сохранённый справочник."
            with reading() as con:
                if cached_count:
                    hotels = rows(con.execute("""SELECT * FROM hotels WHERE city=? AND source='osm'
                        ORDER BY rating DESC,name LIMIT 60""", (city,)))
                    source = "openstreetmap"
                else:
                    hotels = rows(con.execute("""SELECT * FROM hotels WHERE city=? AND source='catalog'
                        ORDER BY rating DESC,nightly_price""", (city,)))
                    source = "verified_catalog"
            for hotel in hotels:
                hotel["total_price"] = hotel["nightly_price"] * nights
                hotel["nights"] = nights
                hotel["estimated_price"] = True  # Ни один из источников не даёт онлайн-тарифов.
                hotel["demo"] = source != "openstreetmap"
            return {"status": "ok", "hotels": hotels, "guests": guests,
                    "source": source, "warning": warning, "demo": source != "openstreetmap"}

        if action == "book":
            user_id = require(request.get("user_id"), "пользователь", 80)
            hotel_id = require(request.get("hotel_id"), "отель", 50)
            guest_name = name(request.get("guest_name"), "имя гостя")
            mail = email(request.get("email"))
            guests = positive_int(request.get("guests", 1), "гостей", 4)
            check_in = parse_day(request.get("check_in"), "заезд")
            check_out = parse_day(request.get("check_out"), "выезд")
            nights = (check_out - check_in).days
            if not 1 <= nights <= 30:
                raise InputError("Выберите срок проживания от 1 до 30 ночей")
            booking_id = uuid4().hex[:12].upper()
            with transaction() as con:
                hotel = con.execute("SELECT * FROM hotels WHERE id=?", (hotel_id,)).fetchone()
                if not hotel:
                    raise InputError("Отель не найден")
                total = hotel["nightly_price"] * nights
                upsert_user(con, user_id, guest_name, mail)
                con.execute("""INSERT INTO hotel_bookings
                    (id,user_id,hotel_id,guest_name,email,check_in,check_out,guests,price,status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                    booking_id, user_id, hotel_id, guest_name, mail,
                    check_in.isoformat(), check_out.isoformat(), guests, total,
                    "pending_payment", now(),
                ))
            return {"status": "ok", "booking_id": booking_id, "price": total, "demo": True}

        if action == "list":
            user_id = require(request.get("user_id"), "пользователь", 80)
            with reading() as con:
                bookings = rows(con.execute("""SELECT b.id, b.guest_name, b.email,
                    b.check_in,b.check_out,b.guests,b.price,b.status,b.created_at,
                    h.name AS hotel_name,h.city,h.rating
                    FROM hotel_bookings b JOIN hotels h ON b.hotel_id=h.id
                    WHERE b.user_id=? ORDER BY b.created_at DESC""", (user_id,)))
            return {"status": "ok", "bookings": bookings}

        if action == "cancel":
            user_id = require(request.get("user_id"), "пользователь", 80)
            booking_id = require(request.get("booking_id"), "номер брони", 40)
            with transaction() as con:
                row = con.execute("SELECT status FROM hotel_bookings WHERE id=? AND user_id=?",
                                  (booking_id, user_id)).fetchone()
                if not row:
                    raise InputError("Бронь не найдена")
                if row["status"] == "cancelled":
                    return {"status": "ok", "booking_id": booking_id}
                con.execute("UPDATE hotel_bookings SET status='cancelled' WHERE id=?", (booking_id,))
                con.execute("UPDATE payments SET status='refunded_demo' WHERE booking_kind='hotel' AND booking_id=?", (booking_id,))
            return {"status": "ok", "booking_id": booking_id, "refund_demo": True}

        raise InputError("Неизвестное действие микросервиса отелей")
