"""Микросервис №1: поиск рейсов + мои авиабронирования."""
from datetime import date
from hashlib import sha256
import re
from uuid import uuid4

from common import config
from common.catalog import CITIES, demo_flights
from common.db import now, reading, rows, transaction, upsert_user
from common.validation import InputError, email, name, parse_day, passport_mask, require
from services.flight_provider import search_prices


def local_roundtrip(origin, destination, day, return_day):
    """Две стороны маршрута локального каталога с общей ценой."""
    forward = demo_flights(origin, destination, day)
    backward = demo_flights(destination, origin, return_day)
    offers = []
    for flight in forward:
        for back in backward:
            combined = dict(flight)
            combined["id"] = "RT-" + sha256(
                (flight["id"] + "|" + back["id"]).encode("utf-8")).hexdigest()[:20].upper()
            combined["price"] = flight["price"] + back["price"]
            combined["airline_name"] = flight["airline"]
            combined["return_airline"] = back["airline"]
            combined["return_departure"] = back["departure"]
            combined["return_duration_min"] = back["duration_min"]
            offers.append(combined)
    return sorted(offers, key=lambda f: f["price"])[:30]


class FlightService:
    def handle(self, request):
        action = request.get("action")
        if action == "search":
            origin = require(request.get("origin"), "откуда", 3).upper()
            destination = require(request.get("destination"), "куда", 3).upper()
            if origin not in CITIES or destination not in CITIES or origin == destination:
                raise InputError("Выберите два разных города из списка")
            day = parse_day(request.get("date")).isoformat()
            return_day = ""
            if request.get("return_date"):
                return_day = parse_day(request["return_date"]).isoformat()
                if return_day <= day:
                    raise InputError("Дата обратного вылета должна быть позже даты вылета")
            using_api = bool(config.TRAVELPAYOUTS_TOKEN)
            offers = (search_prices(origin, destination, day, config.TRAVELPAYOUTS_TOKEN,
                                    return_day=return_day or None)
                      if using_api else
                      local_roundtrip(origin, destination, day, return_day) if return_day else
                      demo_flights(origin, destination, day))
            for offer in offers:
                offer.setdefault("return_departure", "")
                offer.setdefault("return_airline", "")
                offer.setdefault("return_duration_min", 0)
                offer.setdefault("airline_name", offer["airline"].split(" · ")[0])
            with transaction() as con:
                con.executemany("""INSERT OR IGNORE INTO flight_offers
                    (id,origin,destination,airline,departure,arrival,duration_min,price,currency,demo,
                     return_departure,return_airline,return_duration_min)
                    VALUES (:id,:origin,:destination,:airline,:departure,:arrival,:duration_min,:price,:currency,:demo,
                            :return_departure,:return_airline,:return_duration_min)""", offers)
            return {"status": "ok", "flights": offers, "demo": not using_api,
                    "source": "travelpayouts" if using_api else "local",
                    "return_date": return_day}

        if action == "book":
            user_id = require(request.get("user_id"), "пользователь", 80)
            offer_id = require(request.get("flight_id"), "рейс", 80)
            first_name = name(request.get("first_name"), "имя")
            last_name = name(request.get("last_name"), "фамилия")
            birth_date = parse_day(request.get("birth_date"), "дата рождения", future=False)
            if not date(1900, 1, 1) <= birth_date < date.today():
                raise InputError("Некорректная дата рождения")
            document = passport_mask(request.get("passport_number"))
            country = require(request.get("passport_country"), "страна выдачи", 60)
            mail = email(request.get("email"))
            phone = str(request.get("phone") or "").strip()
            if phone and (not re.fullmatch(r"[+\d ()-]{10,24}", phone) or
                          not 10 <= len(re.sub(r"\D", "", phone)) <= 15):
                raise InputError("Телефон указывается в международном формате")
            middle_name = str(request.get("middle_name") or "").strip()
            if middle_name:
                middle_name = name(middle_name, "отчество")
            gender = str(request.get("gender") or "")
            if gender not in ("", "male", "female"):
                raise InputError("Некорректный пол пассажира")
            document_type = str(request.get("document_type") or "passport")
            if document_type not in ("passport", "international_passport"):
                raise InputError("Некорректный тип документа")
            seat_preference = str(request.get("seat_preference") or "").upper()
            if seat_preference and not re.fullmatch(r"(?:[1-9]|[12][0-9]|30)[ABCDEF]", seat_preference):
                raise InputError("Некорректное пожелание по месту")
            booking_id = uuid4().hex[:12].upper()
            with transaction() as con:
                offer = con.execute("SELECT * FROM flight_offers WHERE id=?", (offer_id,)).fetchone()
                if not offer:
                    raise InputError("Рейс не найден. Выполните поиск заново")
                if offer["departure"][:10] < date.today().isoformat():
                    raise InputError("Нельзя забронировать прошедший рейс")
                upsert_user(con, user_id, f"{first_name} {last_name}", mail)
                con.execute("""INSERT INTO flight_bookings
                    (id,user_id,offer_id,first_name,last_name,birth_date,passport_mask,
                    passport_country,email,phone,gender,document_type,middle_name,
                    seat_preference,price,status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    booking_id, user_id, offer_id, first_name, last_name,
                    birth_date.isoformat(), document, country, mail,
                    phone, gender, document_type, middle_name, seat_preference, offer["price"],
                    "pending_payment", now(),
                ))
            return {"status": "ok", "booking_id": booking_id, "price": offer["price"], "demo": True}

        if action == "list":
            user_id = require(request.get("user_id"), "пользователь", 80)
            with reading() as con:
                bookings = rows(con.execute("""SELECT b.id, b.email, b.first_name, b.last_name,
                    b.passport_mask, b.phone, b.gender, b.document_type,
                    b.middle_name, b.seat_preference, b.price, b.status, b.created_at, o.airline,
                    o.origin, o.destination, o.departure, o.arrival,
                    o.return_departure, o.return_airline
                    FROM flight_bookings b JOIN flight_offers o ON b.offer_id=o.id
                    WHERE b.user_id=? ORDER BY b.created_at DESC""", (user_id,)))
            return {"status": "ok", "bookings": bookings}

        if action == "cancel":
            user_id = require(request.get("user_id"), "пользователь", 80)
            booking_id = require(request.get("booking_id"), "номер брони", 40)
            with transaction() as con:
                row = con.execute("SELECT status FROM flight_bookings WHERE id=? AND user_id=?",
                                  (booking_id, user_id)).fetchone()
                if not row:
                    raise InputError("Бронь не найдена")
                if row["status"] == "cancelled":
                    return {"status": "ok", "booking_id": booking_id}
                con.execute("UPDATE flight_bookings SET status='cancelled' WHERE id=?", (booking_id,))
                con.execute("UPDATE payments SET status='refunded_demo' WHERE booking_kind='flight' AND booking_id=?", (booking_id,))
            return {"status": "ok", "booking_id": booking_id, "refund_demo": True}

        raise InputError("Неизвестное действие микросервиса авиабилетов")
