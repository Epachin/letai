"""Проверки без внешних зависимостей."""
from datetime import date, datetime
import re


class InputError(ValueError):
    pass


def require(value, label, maximum=120):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputError(f"Укажите корректное поле «{label}»")
    return value.strip()


def email(value):
    text = require(value, "электронная почта", 254)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text):
        raise InputError("Укажите корректный адрес электронной почты")
    return text


def name(value, label):
    text = require(value, label, 60)
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё '\-]{0,59}", text):
        raise InputError(f"Некорректное поле «{label}»")
    return text


def parse_day(value, label="дата", future=True):
    try:
        if not isinstance(value, str):
            raise ValueError
        day = date.fromisoformat(value)
    except ValueError:
        raise InputError(f"Некорректное поле «{label}»") from None
    if future and day < date.today():
        raise InputError(f"Поле «{label}» не может быть в прошлом")
    return day


def passport_mask(value):
    text = require(value, "номер документа", 24)
    compact = re.sub(r"[ \-]", "", text).upper()
    if not re.fullmatch(r"[A-ZА-ЯЁ0-9]{6,16}", compact):
        raise InputError("Номер документа: 6–16 букв или цифр")
    # Для учебного проекта полный номер паспорта НЕ сохраняется.
    return "•" * max(0, len(compact) - 4) + compact[-4:]


def positive_int(value, label, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise InputError(f"Некорректное поле «{label}»") from None
    if not 1 <= number <= maximum:
        raise InputError(f"Поле «{label}» должно быть от 1 до {maximum}")
    return number
