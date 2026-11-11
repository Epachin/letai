"""Микросервис №3: подтверждение заказов без подключения эквайринга."""
import smtplib
import ssl
from email.message import EmailMessage
from uuid import uuid4

from common import config
from common.catalog import CITIES
from common.db import now, reading, rows, transaction
from common.validation import InputError, require

METHODS = {"card": "Банковская карта", "sbp": "СБП"}


def booking_summary(con, kind, booking_id):
    """Краткая информация о заказе для письма и экрана результата."""
    if kind == "flight":
        item = con.execute("""SELECT o.origin,o.destination,o.airline,o.departure,
            o.return_departure,b.seat_preference FROM flight_bookings b
            JOIN flight_offers o ON b.offer_id=o.id WHERE b.id=?""", (booking_id,)).fetchone()
        title = (f"{CITIES.get(item['origin'], item['origin'])} → "
                 f"{CITIES.get(item['destination'], item['destination'])}")
        dates = f"Вылет: {item['departure'].replace('T', ' ')[:16]}"
        if item["return_departure"]:
            dates += f" · Обратно: {item['return_departure'].replace('T', ' ')[:16]}"
        description = item["airline"]
        if item["seat_preference"]:
            description += f" · Пожелание по месту: {item['seat_preference']}"
        return {"title": title, "dates": dates, "description": description}
    item = con.execute("""SELECT h.name,h.city,h.source,b.check_in,b.check_out
        FROM hotel_bookings b JOIN hotels h ON b.hotel_id=h.id
        WHERE b.id=?""", (booking_id,)).fetchone()
    return {"title": f"{item['name']} · {item['city']}",
            "dates": f"Проживание: {item['check_in']} — {item['check_out']}",
            "description": ("Заявка ЛетимДешево — отель не подтверждал наличие номера"
                            if item["source"] == "osm" else "Отель")}


class PaymentService:
    def handle(self, request):
        action = request.get("action")
        if action == "pay":
            kind = require(request.get("kind"), "тип брони", 10)
            if kind not in ("flight", "hotel"):
                raise InputError("Некорректный тип бронирования")
            booking_id = require(request.get("booking_id"), "номер брони", 40)
            user_id = require(request.get("user_id"), "пользователь", 80)
            method = require(request.get("method") or "card", "способ оплаты", 12)
            if method not in METHODS:
                raise InputError("Выберите способ оплаты: банковская карта или СБП")
            table = "flight_bookings" if kind == "flight" else "hotel_bookings"
            with transaction() as con:
                booking = con.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?",
                                      (booking_id, user_id)).fetchone()
                if not booking:
                    raise InputError("Бронирование не найдено")
                if booking["status"] == "cancelled":
                    raise InputError("Отменённую бронь подтвердить нельзя")
                detail = booking_summary(con, kind, booking_id)
                existing = con.execute("SELECT * FROM payments WHERE booking_kind=? AND booking_id=?",
                                       (kind, booking_id)).fetchone()
                if existing and existing["status"] == "paid_demo":
                    saved_mail = con.execute("SELECT recipient,status FROM email_outbox WHERE payment_id=?",
                                             (existing["id"],)).fetchone()
                    return {"status": "ok", "payment_id": existing["id"],
                            "booking_id": booking_id, "amount": existing["amount"],
                            "method": existing["method"], "summary": detail,
                            "demo": True, "already_paid": True,
                            "mail_to": saved_mail["recipient"] if saved_mail else booking["email"],
                            "mail_status": saved_mail["status"] if saved_mail else "queued"}
                if existing:
                    raise InputError("Невозможно повторно подтвердить отменённую бронь")

                payment_id = uuid4().hex[:12].upper()
                con.execute("""INSERT INTO payments
                    (id,booking_kind,booking_id,user_id,amount,status,method,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (
                    payment_id, kind, booking_id, user_id, booking["price"], "paid_demo", method, now(),
                ))
                con.execute(f"UPDATE {table} SET status='paid_demo' WHERE id=?", (booking_id,))
                subject = f"ЛетимДешево — подтверждение оплаты заказа №{booking_id}"
                body = ("Здравствуйте!\n\nОплата прошла успешно. Заказ подтверждён.\n\n"
                        f"Номер бронирования: {booking_id}\n"
                        f"Тип: {'Авиабилет' if kind == 'flight' else 'Отель'}\n"
                        f"{detail['title']}\n{detail['dates']}\n{detail['description']}\n"
                        f"Способ оплаты: {METHODS[method]}\n"
                        f"Сумма заказа: {booking['price']:,} ₽\n"
                        f"Номер операции: {payment_id}\n\n"
                        "Спасибо, что выбрали ЛетимДешево!\n")
                con.execute("""INSERT INTO email_outbox
                    (payment_id,recipient,subject,body,created_at) VALUES (?,?,?,?,?)""",
                    (payment_id, booking["email"], subject, body, now()))

            mail_status = self.try_send(payment_id)
            return {"status": "ok", "payment_id": payment_id, "booking_id": booking_id,
                    "amount": booking["price"], "method": method, "summary": detail,
                    "demo": True, "mail_status": mail_status, "mail_to": booking["email"]}

        if action == "list":
            user_id = require(request.get("user_id"), "пользователь", 80)
            with reading() as con:
                payments = rows(con.execute("""SELECT p.id,p.booking_kind,p.booking_id,
                    p.amount,p.status,p.method,p.created_at,e.status AS mail_status
                    FROM payments p LEFT JOIN email_outbox e ON e.payment_id=p.id
                    WHERE p.user_id=? ORDER BY p.created_at DESC""", (user_id,)))
            return {"status": "ok", "payments": payments}

        if action == "outbox":
            # Локальная диагностика: не выдаёт письма третьих лиц.
            user_id = require(request.get("user_id"), "пользователь", 80)
            with reading() as con:
                outbox = rows(con.execute("""SELECT e.id,e.recipient,e.subject,e.status,e.created_at
                    FROM email_outbox e JOIN payments p ON e.payment_id=p.id
                    WHERE p.user_id=? ORDER BY e.id DESC""", (user_id,)))
            return {"status": "ok", "emails": outbox}

        raise InputError("Неизвестное действие микросервиса оплаты")

    def try_send(self, payment_id):
        if not (config.SMTP_HOST and config.SMTP_FROM):
            return "queued"
        with reading() as con:
            mail = con.execute("SELECT * FROM email_outbox WHERE payment_id=?", (payment_id,)).fetchone()
        if not mail or mail["status"] == "sent":
            return "sent"
        message = EmailMessage()
        message["Subject"] = mail["subject"]
        message["From"] = config.SMTP_FROM
        message["To"] = mail["recipient"]
        message.set_content(mail["body"])
        try:
            if config.SMTP_SSL:
                client = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                          timeout=8, context=ssl.create_default_context())
            else:
                client = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=8)
            with client as smtp:
                if config.SMTP_TLS and not config.SMTP_SSL:
                    smtp.starttls(context=ssl.create_default_context())
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(message)
            status, error = "sent", ""
        except Exception as exc:
            status, error = "queued", str(exc)[:300]
        with transaction() as con:
            con.execute("UPDATE email_outbox SET status=?,error=? WHERE payment_id=?",
                        (status, error, payment_id))
        return status
