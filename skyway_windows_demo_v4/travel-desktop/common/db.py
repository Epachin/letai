"""Одна SQLite-БД для трёх сервисов на одной машине Windows.

Для коротких транзакций включены WAL, foreign keys и busy_timeout.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3

from .catalog import HOTELS
from .config import DB_PATH


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=20000")
    return con


@contextmanager
def reading():
    con = connect()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transaction():
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


def init():
    with reading() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, display_name TEXT NOT NULL, email TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flight_offers (
            id TEXT PRIMARY KEY, origin TEXT NOT NULL, destination TEXT NOT NULL,
            airline TEXT NOT NULL, departure TEXT NOT NULL, arrival TEXT NOT NULL,
            duration_min INTEGER NOT NULL, price INTEGER NOT NULL,
            currency TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 1,
            return_departure TEXT NOT NULL DEFAULT '',
            return_airline TEXT NOT NULL DEFAULT '',
            return_duration_min INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS hotels (
            id TEXT PRIMARY KEY, city TEXT NOT NULL, name TEXT NOT NULL,
            district TEXT NOT NULL, rating REAL NOT NULL, nightly_price INTEGER NOT NULL,
            amenities TEXT NOT NULL, description TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'catalog',
            address TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '',
            latitude REAL, longitude REAL
        );
        CREATE TABLE IF NOT EXISTS hotel_lookup_cache (
            city TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, item_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flight_bookings (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            offer_id TEXT NOT NULL REFERENCES flight_offers(id),
            first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            birth_date TEXT NOT NULL, passport_mask TEXT NOT NULL,
            passport_country TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '', gender TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT 'passport',
            middle_name TEXT NOT NULL DEFAULT '', seat_preference TEXT NOT NULL DEFAULT '',
            price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending_payment',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hotel_bookings (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            hotel_id TEXT NOT NULL REFERENCES hotels(id),
            guest_name TEXT NOT NULL, email TEXT NOT NULL,
            check_in TEXT NOT NULL, check_out TEXT NOT NULL,
            guests INTEGER NOT NULL, price INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_payment',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, booking_kind TEXT NOT NULL,
            booking_id TEXT NOT NULL, user_id TEXT NOT NULL,
            amount INTEGER NOT NULL, status TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'card',
            created_at TEXT NOT NULL, UNIQUE(booking_kind, booking_id)
        );
        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT UNIQUE NOT NULL,
            recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)
        # Без потери существующих бронирований обновляем БД из прежней версии.
        flight_columns = {column[1] for column in con.execute("PRAGMA table_info(flight_offers)")}
        for column_name, ddl in (
            ("return_departure", "TEXT NOT NULL DEFAULT ''"),
            ("return_airline", "TEXT NOT NULL DEFAULT ''"),
            ("return_duration_min", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column_name not in flight_columns:
                con.execute(f"ALTER TABLE flight_offers ADD COLUMN {column_name} {ddl}")
        payment_columns = {column[1] for column in con.execute("PRAGMA table_info(payments)")}
        if "method" not in payment_columns:
            con.execute("ALTER TABLE payments ADD COLUMN method TEXT NOT NULL DEFAULT 'card'")
        hotel_columns = {column[1] for column in con.execute("PRAGMA table_info(hotels)")}
        for column_name, ddl in (
            ("source", "TEXT NOT NULL DEFAULT 'catalog'"),
            ("address", "TEXT NOT NULL DEFAULT ''"),
            ("website", "TEXT NOT NULL DEFAULT ''"),
            ("latitude", "REAL"),
            ("longitude", "REAL"),
        ):
            if column_name not in hotel_columns:
                con.execute(f"ALTER TABLE hotels ADD COLUMN {column_name} {ddl}")
        booking_columns = {column[1] for column in con.execute("PRAGMA table_info(flight_bookings)")}
        for column_name, ddl in (
            ("phone", "TEXT NOT NULL DEFAULT ''"),
            ("gender", "TEXT NOT NULL DEFAULT ''"),
            ("document_type", "TEXT NOT NULL DEFAULT 'passport'"),
            ("middle_name", "TEXT NOT NULL DEFAULT ''"),
            ("seat_preference", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in booking_columns:
                con.execute(f"ALTER TABLE flight_bookings ADD COLUMN {column_name} {ddl}")
        # Сохраняем старые брони, но скрываем из поиска устаревшие условные отели.
        old_hotel_ids = tuple(f"h{i}" for i in range(1, 12))
        con.execute("""UPDATE hotels SET source='legacy' WHERE source='catalog'
            AND id IN (?,?,?,?,?,?,?,?,?,?,?)""", old_hotel_ids)
        con.executemany("""
            INSERT OR IGNORE INTO hotels
            (id,city,name,district,rating,nightly_price,amenities,description,address,website)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, HOTELS)
        con.commit()


def upsert_user(con, user_id, display_name, email):
    con.execute("""INSERT INTO users(id,display_name,email) VALUES (?,?,?)
        ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,
        email=excluded.email""", (user_id, display_name, email))
