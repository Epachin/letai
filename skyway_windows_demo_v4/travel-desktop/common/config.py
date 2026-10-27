"""Единые настройки всех процессов; файлов .env автоматически не читает."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_db = Path(os.getenv("TRAVEL_DB_PATH", "data/travel.sqlite3"))
DB_PATH = _db if _db.is_absolute() else ROOT / _db

RABBIT_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBIT_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBIT_USER = os.getenv("RABBITMQ_USER", "guest")
RABBIT_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")

FLIGHTS_QUEUE = "travel.flights.requests"
HOTELS_QUEUE = "travel.hotels.requests"
PAYMENTS_QUEUE = "travel.payments.requests"

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_SSL = os.getenv("SMTP_SSL", "true" if SMTP_PORT == 465 else "false").lower() == "true"
SMTP_TLS = os.getenv("SMTP_TLS", "false" if SMTP_SSL else "true").lower() == "true"

# Передаётся только через окружение запуска микросервиса, не хранится в коде.
TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "").strip()

# Источник сведений о реальных гостиницах (без цен на номера).
HOTEL_OSM_URL = os.getenv("HOTEL_OSM_URL", "https://overpass.private.coffee/api/interpreter").strip()
