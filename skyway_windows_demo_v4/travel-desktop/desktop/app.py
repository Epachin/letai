"""Десктопная витрина бронирования. Веб-браузер не нужен."""
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QDate, QRectF, QSettings, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from common.catalog import CITIES
from common.config import FLIGHTS_QUEUE, HOTELS_QUEUE, PAYMENTS_QUEUE
from common.broker import rpc


def label(text, kind=""):
    obj = QLabel(str(text))
    obj.setWordWrap(True)
    if kind:
        obj.setObjectName(kind)
    return obj


def button(text, primary=False):
    obj = QPushButton(text)
    if primary:
        obj.setObjectName("primary")
    obj.setCursor(Qt.PointingHandCursor)
    return obj


def panel(layout=None, kind="panel"):
    frame = QFrame()
    frame.setObjectName(kind)
    if layout is not None:
        frame.setLayout(layout)
    return frame


def vbox(*widgets, spacing=12):
    result = QVBoxLayout()
    result.setSpacing(spacing)
    for item in widgets:
        result.addWidget(item)
    return result


def scrollable():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setAlignment(Qt.AlignTop)
    layout.setContentsMargins(6, 8, 6, 20)
    layout.setSpacing(13)
    scroll.setWidget(body)
    return scroll, layout


class RequestJob(QThread):
    finished_result = Signal(object, object)

    def __init__(self, queue, payload):
        super().__init__()
        self.queue = queue
        self.payload = payload

    def run(self):
        try:
            result = rpc(self.queue, self.payload)
            self.finished_result.emit(result, None)
        except Exception as exc:
            self.finished_result.emit(None, str(exc))


class HotelArt(QWidget):
    """Небольшая встроенная иллюстрация отеля без сетевых изображений."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(112, 100)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 112, 100)
        gradient.setColorAt(0, QColor("#d5e8ff"))
        gradient.setColorAt(1, QColor("#8dc4ff"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(0, 0, 112, 100), 15, 15)
        painter.setBrush(QColor("#f0f7ff"))
        painter.drawRoundedRect(QRectF(25, 27, 64, 64), 4, 4)
        painter.setBrush(QColor("#3274c8"))
        painter.drawRect(QRectF(22, 21, 70, 8))
        painter.setBrush(QColor("#a4d2ff"))
        for x in (34, 54, 74):
            for y in (39, 57):
                painter.drawRoundedRect(QRectF(x, y, 11, 12), 2, 2)
        painter.setBrush(QColor("#347ac5"))
        painter.drawRoundedRect(QRectF(54, 75, 13, 16), 2, 2)
        painter.end()


class SeatSelectionDialog(QDialog):
    """Схема для пожелания пассажира, без привязки к настоящему борту."""

    def __init__(self, parent, selected=""):
        super().__init__(parent)
        self.setWindowTitle("Выбор предпочтительного места")
        self.setMinimumWidth(430)
        self.selected = selected
        main = QVBoxLayout(self)
        main.addWidget(label("Выберите удобное место", "heading"))
        main.addWidget(label(
            "Это пожелание для вашей заявки. Расположение и свободные места "
            "в настоящем самолёте могут отличаться; место не закрепляется авиакомпанией.", "small"))
        seats = QGridLayout()
        for column, letter in enumerate("ABCDEF"):
            seats.addWidget(label(letter, "small"), 0, column + (1 if column >= 3 else 0))
        for number in range(1, 9):
            for column, letter in enumerate("ABCDEF"):
                seat = f"{number}{letter}"
                item = QPushButton(seat)
                item.setCheckable(True)
                item.setChecked(seat == self.selected)
                item.clicked.connect(lambda _=False, s=seat: self.set_seat(s))
                seats.addWidget(item, number, column + (1 if column >= 3 else 0))
            seats.addWidget(label(str(number), "small"), number, 3)
        main.addLayout(seats)
        self.chosen = label("Пожелание: " + (self.selected or "не выбрано"), "subheading")
        main.addWidget(self.chosen)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText("Сохранить пожелание")
        actions.button(QDialogButtonBox.Cancel).setText("Назад")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        main.addWidget(actions)

    def set_seat(self, seat):
        self.selected = seat
        self.chosen.setText("Пожелание: " + seat)
        for button_ in self.findChildren(QPushButton):
            if button_.isCheckable():
                button_.setChecked(button_.text() == seat)


class FlightForm(QDialog):
    def __init__(self, parent, flight, email):
        super().__init__(parent)
        self.setWindowTitle("Данные пассажира")
        self.setMinimumWidth(520)
        form = QFormLayout()
        form.setSpacing(12)
        self.first = QLineEdit()
        self.last = QLineEdit()
        self.middle = QLineEdit()
        self.middle.setPlaceholderText("Если есть в документе")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("+7 999 123-45-67")
        self.gender = QComboBox()
        self.gender.addItem("Не указан", "")
        self.gender.addItem("Мужской", "male")
        self.gender.addItem("Женский", "female")
        self.document_type = QComboBox()
        self.document_type.addItem("Паспорт РФ", "passport")
        self.document_type.addItem("Загранпаспорт", "international_passport")
        self.birth = QDateEdit()
        self.birth.setDisplayFormat("dd.MM.yyyy")
        self.birth.setCalendarPopup(True)
        self.birth.setDate(QDate.currentDate().addYears(-20))
        self.birth.setMaximumDate(QDate.currentDate().addDays(-1))
        self.passport = QLineEdit()
        self.passport.setPlaceholderText("Номер документа, 6–16 символов")
        self.country = QLineEdit("Россия")
        self.email = QLineEdit(email)
        for caption, field in (("E-mail", self.email), ("Телефон", self.phone),
                               ("Фамилия", self.last), ("Имя", self.first),
                               ("Отчество", self.middle), ("Дата рождения", self.birth),
                               ("Пол", self.gender), ("Гражданство", self.country),
                               ("Документ", self.document_type),
                               ("Номер документа", self.passport)):
            form.addRow(caption + ":", field)
        self.seat_preference = ""
        self.seat_btn = button("Выбрать место")
        self.seat_btn.clicked.connect(self.select_seat)
        form.addRow("Место:", self.seat_btn)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText("Продолжить")
        actions.button(QDialogButtonBox.Cancel).setText("Отмена")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        main = QVBoxLayout(self)
        main.setContentsMargins(18, 14, 18, 14)
        main.setSpacing(8)
        main.addWidget(label("✈  " + flight["airline"] + "  •  " + flight["departure"].replace("T", " "), "heading"))
        if flight.get("return_departure"):
            back = flight["return_departure"].replace("T", " ")
            carrier = flight.get("return_airline") or "уточняется у перевозчика"
            main.addWidget(label(f"Обратный рейс: {back}  •  {carrier}", "subheading"))
        # Прокручивается содержимое анкеты, а кнопки всегда остаются видимыми.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        fields = QVBoxLayout(body)
        fields.setContentsMargins(4, 4, 12, 4)
        fields.setSpacing(10)
        fields.addWidget(label("Контактные данные и данные пассажира", "subheading"))
        fields.addWidget(label("Номер документа сохраняется только в маскированном виде.", "small"))
        fields.addLayout(form)
        fields.addWidget(label("Возврат и обмен", "subheading"))
        fields.addWidget(label(
            "Правила тарифа и право на возврат необходимо проверить у авиакомпании "
            "перед фактической покупкой билета.", "small"))
        fields.addWidget(label("Дополнительные услуги", "subheading"))
        fields.addWidget(label(
            "Страхование, платная регистрация и покупка мест у авиакомпаний "
            "не подключены. Здесь можно сохранить только предпочтение по месту.", "small"))
        fields.addStretch()
        area.setWidget(body)
        main.addWidget(area, 1)
        main.addWidget(actions)
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 720
        self.resize(560, min(690, max(380, available_height - 90)))

    def select_seat(self):
        picker = SeatSelectionDialog(self, self.seat_preference)
        if picker.exec() == QDialog.Accepted:
            self.seat_preference = picker.selected
            self.seat_btn.setText("Место: " + self.seat_preference if self.seat_preference else "Выбрать место")

    def values(self):
        return {"first_name": self.first.text(), "last_name": self.last.text(),
                "middle_name": self.middle.text(), "phone": self.phone.text(),
                "gender": self.gender.currentData(),
                "document_type": self.document_type.currentData(),
                "seat_preference": self.seat_preference,
                "birth_date": self.birth.date().toString("yyyy-MM-dd"),
                "passport_number": self.passport.text(),
                "passport_country": self.country.text(), "email": self.email.text()}


class HotelForm(QDialog):
    def __init__(self, parent, hotel, email, check_in, check_out, guests):
        super().__init__(parent)
        self.setWindowTitle("Бронирование отеля")
        self.setMinimumWidth(410)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Имя и фамилия гостя")
        self.email = QLineEdit(email)
        form = QFormLayout()
        form.addRow("Имя гостя:", self.name)
        form.addRow("E-mail:", self.email)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText("Создать бронь")
        actions.button(QDialogButtonBox.Cancel).setText("Отмена")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        main = QVBoxLayout(self)
        main.addWidget(label("🏨  " + hotel["name"], "heading"))
        main.addWidget(label(f"{check_in} — {check_out}  •  {guests} гост.  •  {hotel['total_price']:,} ₽"))
        if hotel.get("estimated_price"):
            main.addWidget(label(
                "Стоимость ориентировочная. Заявка сохраняется в ЛетимДешево и не является "
                "подтверждением номера со стороны отеля.", "small"))
        main.addLayout(form)
        main.addWidget(actions)


class CheckoutDialog(QDialog):
    """Подтверждение заказа перед передачей в сервис оплаты."""

    def __init__(self, parent, kind, booking_id, amount, email):
        super().__init__(parent)
        self.setWindowTitle("Оплата заказа")
        self.setMinimumWidth(440)
        main = QVBoxLayout(self)
        main.setContentsMargins(26, 24, 26, 24)
        main.setSpacing(16)
        main.addWidget(label("Оплата заказа", "heading"))
        main.addWidget(label("Авиабилет" if kind == "flight" else "Бронирование отеля", "badge"))
        main.addWidget(label(f"Бронирование №{booking_id}", "subheading"))
        main.addWidget(label(f"{amount:,} ₽".replace(",", " "), "price"))
        main.addWidget(label("Выберите способ оплаты:", "small"))
        self.method = QComboBox()
        self.method.addItem("Банковская карта", "card")
        self.method.addItem("СБП", "sbp")
        main.addWidget(self.method)
        if kind == "hotel":
            main.addWidget(label(
                "Операция сохраняется в ЛетимДешево. Для подтверждения размещения "
                "необходимо связаться с самой гостиницей.", "small"))
        main.addWidget(label("Подтверждение будет отправлено на адрес:", "small"))
        main.addWidget(label(email))
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText("Оплатить")
        actions.button(QDialogButtonBox.Cancel).setText("Назад")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        main.addWidget(actions)


class SuccessDialog(QDialog):
    """Отдельное окно, открывающееся после ответа сервиса оплаты."""

    def __init__(self, parent, result, show_bookings=True):
        super().__init__(parent)
        self.setWindowTitle("Оплата подтверждена")
        self.setMinimumWidth(500)
        self.go_bookings = False
        main = QVBoxLayout(self)
        main.setContentsMargins(38, 28, 38, 28)
        main.setSpacing(16)
        check = label("✓")
        check.setAlignment(Qt.AlignCenter)
        check.setStyleSheet("font-size: 58px; color: #168653; font-weight: 800;")
        main.addWidget(check)
        heading = label("Оплата успешно подтверждена", "heading")
        heading.setAlignment(Qt.AlignCenter)
        main.addWidget(heading)
        if result.get("booking_id"):
            booking = label(f"Бронирование №{result['booking_id']}", "subheading")
            booking.setAlignment(Qt.AlignCenter)
            main.addWidget(booking)
        summary = result.get("summary") or {}
        if summary.get("title"):
            route = label(summary["title"])
            route.setAlignment(Qt.AlignCenter)
            main.addWidget(route)
        if summary.get("dates"):
            dates = label(summary["dates"], "small")
            dates.setAlignment(Qt.AlignCenter)
            main.addWidget(dates)
        if summary.get("description"):
            detail = label(summary["description"], "small")
            detail.setAlignment(Qt.AlignCenter)
            main.addWidget(detail)
        order = label(f"Номер операции: {result['payment_id']}")
        order.setAlignment(Qt.AlignCenter)
        main.addWidget(order)
        method_text = {"card": "Банковская карта", "sbp": "СБП"}.get(result.get("method"))
        if method_text:
            method_label = label(f"Способ оплаты: {method_text}", "small")
            method_label.setAlignment(Qt.AlignCenter)
            main.addWidget(method_label)
        amount = label(f"Сумма заказа: {result['amount']:,} ₽".replace(",", " "), "subheading")
        amount.setAlignment(Qt.AlignCenter)
        main.addWidget(amount)
        if result.get("mail_status") == "sent":
            mail_text = f"Письмо отправлено на {result.get('mail_to', 'указанную почту')}"
        else:
            mail_text = "Подтверждение сохранено, но письмо пока не отправлено. Проверьте настройки SMTP."
        mail_label = label(mail_text, "small")
        mail_label.setAlignment(Qt.AlignCenter)
        main.addWidget(mail_label)
        actions = QHBoxLayout()
        close = button("Закрыть")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        if show_bookings:
            history = button("Мои бронирования", True)
            history.clicked.connect(self.open_bookings)
            actions.addWidget(history)
        main.addLayout(actions)

    def open_bookings(self):
        self.go_bookings = True
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЛетимДешево — авиабилеты и отели")
        self.resize(1190, 790)
        self.setMinimumSize(880, 620)
        self.jobs = set()
        self.settings = QSettings("StudentTravelDemo", "ЛетимДешево")
        self.user_id = self.settings.value("user_id") or uuid.uuid4().hex
        self.settings.setValue("user_id", self.user_id)
        self.email = self.settings.value("email", "")
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        top = panel(kind="header")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(28, 13, 28, 10)
        top_layout.addWidget(label("✈  ЛетимДешево", "logo"))
        top_layout.addStretch()
        payments_history = button("История оплат")
        payments_history.setObjectName("headerAction")
        payments_history.clicked.connect(self.load_payments)
        top_layout.addWidget(payments_history)
        top_layout.addWidget(label("Путешествия начинаются здесь", "headerText"))
        main.addWidget(top)

        self.tabs = QTabWidget()
        main.addWidget(self.tabs)
        self.tabs.addTab(self.build_flights(), "✈  Авиабилеты")
        self.tabs.addTab(self.build_hotels(), "▧  Отели")
        bottom = QLabel("ЛетимДешево · Авиабилеты и отели")
        bottom.setAlignment(Qt.AlignCenter)
        bottom.setObjectName("small")
        bottom.setContentsMargins(0, 8, 0, 10)
        main.addWidget(bottom)

    def invoke(self, queue, payload, on_success, control=None):
        if control:
            control.setEnabled(False)
        job = RequestJob(queue, payload)
        self.jobs.add(job)

        def complete(result, error):
            if control:
                control.setEnabled(True)
            if error:
                if queue == FLIGHTS_QUEUE and payload.get("action") == "search":
                    self.clear_results(self.flight_results, "Поиск не выполнен. Проверьте подключение и повторите запрос.")
                QMessageBox.warning(self, "Нет связи с сервисом", error)
            elif result.get("status") != "ok":
                if queue == FLIGHTS_QUEUE and payload.get("action") == "search":
                    self.clear_results(self.flight_results, "Поиск не выполнен. Проверьте запрос и повторите.")
                QMessageBox.warning(self, "Проверка данных", result.get("error", "Неизвестная ошибка"))
            else:
                on_success(result)
        def cleanup():
            self.jobs.discard(job)
            job.deleteLater()

        job.finished_result.connect(complete)
        job.finished.connect(cleanup)
        job.start()

    def build_flights(self):
        page, content = scrollable()
        content.addWidget(label("Куда полетим?", "heading"))
        content.addWidget(label("Выбирайте направления, сравнивайте варианты и управляйте бронированиями.", "subheading"))
        form = QGridLayout()
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(14)
        self.origin = QComboBox()
        self.destination = QComboBox()
        for code, city in CITIES.items():
            self.origin.addItem(f"{city} ({code})", code)
            self.destination.addItem(f"{city} ({code})", code)
        self.destination.setCurrentIndex(1)
        self.flight_day = QDateEdit(QDate.currentDate().addDays(20))
        self.flight_day.setCalendarPopup(True)
        self.flight_day.setDisplayFormat("dd.MM.yyyy")
        self.flight_day.setMinimumDate(QDate.currentDate())
        self.return_check = QCheckBox("Обратно")
        self.return_day = QDateEdit(QDate.currentDate().addDays(27))
        self.return_day.setCalendarPopup(True)
        self.return_day.setDisplayFormat("dd.MM.yyyy")
        self.return_day.setEnabled(False)
        self.flight_day.dateChanged.connect(self.sync_return_day)
        self.return_check.toggled.connect(self.return_day.setEnabled)
        self.sync_return_day()
        self.search_btn = button("Найти билеты", True)
        self.search_btn.clicked.connect(self.search_flights)
        self.bookings_btn = button("Мои авиаброни")
        self.bookings_btn.clicked.connect(self.load_flight_bookings)
        for index, (name_, widget) in enumerate((("Откуда", self.origin), ("Куда", self.destination), ("Дата вылета", self.flight_day))):
            form.addWidget(label(name_, "small"), 0, index)
            form.addWidget(widget, 1, index)
            form.setColumnStretch(index, 1)
        form.addWidget(self.return_check, 0, 3)
        form.addWidget(self.return_day, 1, 3)
        form.setColumnStretch(3, 1)
        form.addWidget(self.search_btn, 2, 2)
        form.addWidget(self.bookings_btn, 2, 3)
        content.addWidget(panel(form))
        airline_row = QHBoxLayout()
        airline_row.addWidget(label("Авиакомпания:"))
        self.airline_filter = QComboBox()
        self.airline_filter.addItem("Все авиакомпании", "")
        self.airline_filter.setMinimumWidth(210)
        self.airline_filter.currentIndexChanged.connect(self.render_flights)
        airline_row.addWidget(self.airline_filter)
        airline_row.addStretch()
        self.airline_filter_panel = panel(airline_row)
        self.airline_filter_panel.setVisible(False)
        content.addWidget(self.airline_filter_panel)
        self.flight_results = QVBoxLayout()
        self.flight_results.setSpacing(12)
        content.addLayout(self.flight_results)
        content.addStretch()
        self.clear_results(self.flight_results, "Найдите рейс — здесь появятся варианты перелёта.")
        return page

    def sync_return_day(self, *_):
        earliest = self.flight_day.date().addDays(1)
        self.return_day.setMinimumDate(earliest)
        if self.return_day.date() < earliest:
            self.return_day.setDate(earliest)

    def clear_results(self, layout, placeholder):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                old = item.widget()
                old.hide()
                old.setParent(None)
                old.deleteLater()
            elif item.layout():
                nested = item.layout()
                while nested.count():
                    child = nested.takeAt(0)
                    if child.widget():
                        old = child.widget()
                        old.hide()
                        old.setParent(None)
                        old.deleteLater()
        if placeholder:
            layout.addWidget(label(placeholder, "subheading"))

    def search_flights(self):
        origin, destination = self.origin.currentData(), self.destination.currentData()
        if origin == destination:
            QMessageBox.information(self, "Направление", "Выберите два разных города")
            return
        payload = {"action": "search", "origin": origin, "destination": destination,
                   "date": self.flight_day.date().toString("yyyy-MM-dd")}
        if self.return_check.isChecked():
            payload["return_date"] = self.return_day.date().toString("yyyy-MM-dd")
        self.clear_results(self.flight_results, "Ищем рейсы…")
        self.invoke(FLIGHTS_QUEUE, payload, self.show_flights, self.search_btn)

    def show_flights(self, result):
        self.flight_source = result.get("source", "local")
        self.flight_offers = result["flights"]
        self.airline_filter.blockSignals(True)
        self.airline_filter.clear()
        self.airline_filter.addItem("Все авиакомпании", "")
        for carrier in sorted({f.get("airline_name", f["airline"].split(" · ")[0])
                               for f in self.flight_offers}):
            self.airline_filter.addItem(carrier, carrier)
        self.airline_filter.setCurrentIndex(0)
        self.airline_filter.blockSignals(False)
        self.airline_filter_panel.setVisible(bool(self.flight_offers))
        self.render_flights()

    def render_flights(self, *_):
        if not hasattr(self, "flight_offers"):
            return
        self.clear_results(self.flight_results, "")
        carrier = self.airline_filter.currentData() or ""
        flights = [f for f in self.flight_offers
                   if not carrier or f.get("airline_name", f["airline"].split(" · ")[0]) == carrier]
        self.flight_results.addWidget(label(f"Найдено вариантов: {len(flights)}", "heading"))
        if self.flight_source == "travelpayouts":
            self.flight_results.addWidget(label(
                "Цены из истории поисков Aviasales — перед покупкой требуется проверка доступности и стоимости.",
                "small"))
        else:
            self.flight_results.addWidget(label("Источник: локальный каталог ЛетимДешево", "small"))
        if not flights:
            self.flight_results.addWidget(label(
                "Предложений по выбранному направлению, датам или авиакомпании не найдено."))
            return
        for flight in flights:
            row = QHBoxLayout()
            row.setContentsMargins(19, 14, 19, 14)
            row.setSpacing(14)
            details = QVBoxLayout()
            stops = int(flight.get("transfers", 0))
            transfer_text = "без пересадок" if not stops else f"пересадок: {stops}"
            details.addWidget(label(f"{flight['airline']}  •  {transfer_text}", "badge"))
            details.addWidget(label(f"Вылет {flight['departure'][11:16]}", "heading"))
            details.addWidget(label(f"{CITIES[flight['origin']]} → {CITIES[flight['destination']]}  •  {flight['duration_min']} мин", "subheading"))
            if flight.get("return_departure"):
                back = flight["return_departure"].replace("T", " ")[:16]
                back_airline = flight.get("return_airline")
                suffix = f"  •  {back_airline}" if back_airline else ""
                details.addWidget(label(f"Обратно {CITIES[flight['destination']]} → {CITIES[flight['origin']]}: {back}{suffix}", "subheading"))
            row.addLayout(details, 3)
            price = QVBoxLayout()
            price.addWidget(label(f"{flight['price']:,} ₽".replace(",", " "), "price"))
            scope = "туда и обратно" if flight.get("return_departure") else "в одну сторону"
            prefix = "найденная цена" if not flight.get("demo", True) else "цена"
            price.addWidget(label(f"{prefix}, {scope}", "small"))
            row.addLayout(price, 1)
            btn = button("Выбрать", True)
            btn.clicked.connect(lambda _=False, f=flight: self.book_flight(f))
            row.addWidget(btn)
            if flight.get("link"):
                check_btn = button("Проверить цену")
                check_btn.clicked.connect(
                    lambda _=False, url=flight["link"]: QDesktopServices.openUrl(QUrl(url)))
                row.addWidget(check_btn)
            self.flight_results.addWidget(panel(row, "offer"))

    def book_flight(self, flight):
        dialog = FlightForm(self, flight, self.email)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.values()
        self.email = data["email"]
        self.settings.setValue("email", self.email)
        self.invoke(FLIGHTS_QUEUE, {"action": "book", "user_id": self.user_id,
                    "flight_id": flight["id"], **data},
                    lambda result: self.offer_payment("flight", result))

    def offer_payment(self, kind, result):
        booking_id = result["booking_id"]
        dialog = CheckoutDialog(self, kind, booking_id, result["price"], self.email)
        if dialog.exec() == QDialog.Accepted:
            self.invoke(PAYMENTS_QUEUE,
                        {"action": "pay", "kind": kind, "booking_id": booking_id,
                         "user_id": self.user_id, "method": dialog.method.currentData()},
                        lambda response: self.payment_completed(response, kind))
        else:
            QMessageBox.information(self, "Сохранено", "Бронь ожидает подтверждения. Она доступна в истории.")

    def payment_completed(self, result, kind=None):
        dialog = SuccessDialog(self, result, show_bookings=kind is not None)
        dialog.exec()
        if dialog.go_bookings and kind == "flight":
            self.tabs.setCurrentIndex(0)
            self.load_flight_bookings()
        elif dialog.go_bookings and kind == "hotel":
            self.tabs.setCurrentIndex(1)
            self.load_hotel_bookings()

    def load_payments(self):
        self.invoke(PAYMENTS_QUEUE, {"action": "list", "user_id": self.user_id},
                    self.show_payments)

    def show_payments(self, result):
        history = result["payments"]
        if not history:
            QMessageBox.information(self, "История оплат", "Операций пока нет.")
            return
        lines = []
        for payment in history[:20]:
            kind = "Авиабилет" if payment["booking_kind"] == "flight" else "Отель"
            state = "Заказ отменён" if payment["status"] == "refunded_demo" else "Подтверждено"
            mail = "отправлено" if payment["mail_status"] == "sent" else "в очереди"
            method = {"card": "Карта", "sbp": "СБП"}.get(payment.get("method"), "—")
            lines.append(f"{kind} · {payment['booking_id']}\n"
                         f"{payment['amount']:,} ₽ · {method} · {state} · письмо {mail}")
        QMessageBox.information(self, "История оплат", "\n\n".join(lines))

    def load_flight_bookings(self):
        self.airline_filter_panel.setVisible(False)
        self.clear_results(self.flight_results, "Загружаем бронирования…")
        self.invoke(FLIGHTS_QUEUE, {"action": "list", "user_id": self.user_id},
                    self.show_flight_bookings, self.bookings_btn)

    def show_flight_bookings(self, result):
        self.clear_results(self.flight_results, "")
        self.flight_results.addWidget(label("Мои авиабронирования", "heading"))
        flights = result["bookings"]
        if not flights:
            self.flight_results.addWidget(label("Пока броней нет. Найдите билет и оформите его."))
        for booking in flights:
            title = (f"№ {booking['id']}  •  {booking['airline']}  •  "
                     f"{CITIES[booking['origin']]} → {CITIES[booking['destination']]}")
            subtitle = (f"{booking['departure'].replace('T', ' ')}  •  "
                        f"{booking['first_name']} {booking['last_name']}  •  "
                        f"{booking['price']:,} ₽")
            if booking.get("return_departure"):
                subtitle += (f"  •  Обратно: "
                             f"{booking['return_departure'].replace('T', ' ')[:16]}")
            if booking.get("seat_preference"):
                subtitle += f"  •  Предпочтительное место: {booking['seat_preference']}"
            self.flight_results.addWidget(self.booking_card(title, subtitle, booking, "flight"))

    def booking_card(self, title, subtitle, booking, kind):
        row = QHBoxLayout()
        row.setContentsMargins(18, 13, 18, 13)
        details = QVBoxLayout()
        details.addWidget(label(title))
        details.addWidget(label(subtitle, "subheading"))
        statuses = {"paid_demo": "Подтверждено", "pending_payment": "Ожидает подтверждения",
                    "cancelled": "Отменено"}
        details.addWidget(label(statuses.get(booking["status"], booking["status"]), "badge"))
        row.addLayout(details, 1)
        if booking["status"] == "pending_payment":
            pay = button("Подтвердить", True)
            pay.clicked.connect(lambda _=False, b=booking, k=kind: self.confirm_existing_booking(k, b))
            row.addWidget(pay)
        if booking["status"] != "cancelled":
            cancel = button("Отменить")
            cancel.setObjectName("danger")
            cancel.clicked.connect(lambda _=False, b=booking: self.cancel_booking(kind, b["id"]))
            row.addWidget(cancel)
        return panel(row, "offer")

    def confirm_existing_booking(self, kind, booking):
        dialog = CheckoutDialog(self, kind, booking["id"], booking["price"],
                                booking.get("email", self.email))
        if dialog.exec() == QDialog.Accepted:
            self.invoke(PAYMENTS_QUEUE,
                {"action": "pay", "kind": kind, "booking_id": booking["id"],
                 "user_id": self.user_id, "method": dialog.method.currentData()},
                lambda result: self.payment_completed(result, kind))

    def cancel_booking(self, kind, booking_id):
        answer = QMessageBox.question(self, "Отмена брони", "Отменить бронирование?",
                                      QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        queue = FLIGHTS_QUEUE if kind == "flight" else HOTELS_QUEUE
        refresh = self.load_flight_bookings if kind == "flight" else self.load_hotel_bookings
        self.invoke(queue, {"action": "cancel", "booking_id": booking_id,
                            "user_id": self.user_id}, lambda _result: refresh())

    def build_hotels(self):
        page, content = scrollable()
        content.addWidget(label("Отели для вашего путешествия", "heading"))
        content.addWidget(label("Находите гостиницы на карте, сравнивайте расположение и планируйте проживание.", "subheading"))
        grid = QGridLayout()
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(12)
        self.hotel_city = QComboBox()
        for city in sorted(set(CITIES.values())):
            self.hotel_city.addItem(city)
        self.hotel_city.setCurrentText("Санкт-Петербург")
        self.check_in = QDateEdit(QDate.currentDate().addDays(20))
        self.check_out = QDateEdit(QDate.currentDate().addDays(24))
        for field in (self.check_in, self.check_out):
            field.setCalendarPopup(True)
            field.setDisplayFormat("dd.MM.yyyy")
            field.setMinimumDate(QDate.currentDate())
        self.guests = QSpinBox()
        self.guests.setRange(1, 4)
        self.guests.setValue(2)
        self.hotels_btn = button("Найти отели", True)
        self.hotels_btn.clicked.connect(self.search_hotels)
        self.hotel_bookings_btn = button("Мои отели")
        self.hotel_bookings_btn.clicked.connect(self.load_hotel_bookings)
        inputs = (("Город", self.hotel_city), ("Заезд", self.check_in),
                  ("Выезд", self.check_out), ("Гостей", self.guests))
        for idx, (title, field) in enumerate(inputs):
            grid.addWidget(label(title, "small"), 0, idx)
            grid.addWidget(field, 1, idx)
            grid.setColumnStretch(idx, 1)
        grid.addWidget(self.hotels_btn, 1, 4)
        grid.addWidget(self.hotel_bookings_btn, 1, 5)
        content.addWidget(panel(grid))
        filters = QHBoxLayout()
        filters.addWidget(label("Категория отеля:"))
        self.hotel_stars = QComboBox()
        self.hotel_stars.addItem("Любая", 0)
        for stars in range(1, 6):
            self.hotel_stars.addItem("★" * stars, stars)
        filters.addWidget(self.hotel_stars)
        filters.addWidget(label("Сортировка:"))
        self.hotel_sort = QComboBox()
        self.hotel_sort.addItem("Категория: по убыванию", "stars")
        self.hotel_sort.addItem("Цена: сначала дешевле", "price")
        self.hotel_sort.addItem("Название", "name")
        filters.addWidget(self.hotel_sort)
        filters.addStretch()
        self.hotel_filters_panel = panel(filters)
        self.hotel_filters_panel.setVisible(False)
        content.addWidget(self.hotel_filters_panel)
        self.hotel_stars.currentIndexChanged.connect(self.render_hotels)
        self.hotel_sort.currentIndexChanged.connect(self.render_hotels)
        self.hotel_results = QVBoxLayout()
        self.hotel_results.setSpacing(12)
        content.addLayout(self.hotel_results)
        self.clear_results(self.hotel_results, "Задайте даты и нажмите «Найти отели».")
        content.addStretch()
        return page

    def search_hotels(self):
        check_in = self.check_in.date().toString("yyyy-MM-dd")
        check_out = self.check_out.date().toString("yyyy-MM-dd")
        payload = {"action": "search", "city": self.hotel_city.currentText(),
                   "check_in": check_in, "check_out": check_out, "guests": self.guests.value()}
        self.clear_results(self.hotel_results, "Ищем варианты размещения…")
        self.invoke(HOTELS_QUEUE, payload, lambda response: self.show_hotels(response, payload),
                    self.hotels_btn)

    def show_hotels(self, result, query):
        self.hotel_offers = result["hotels"]
        self.hotel_query = query
        self.hotel_source = result.get("source", "local")
        self.hotel_warning = result.get("warning", "")
        self.hotel_filters_panel.setVisible(bool(self.hotel_offers))
        self.render_hotels()

    def render_hotels(self, *_):
        if not hasattr(self, "hotel_offers"):
            return
        self.clear_results(self.hotel_results, "")
        hotels = list(self.hotel_offers)
        minimum = self.hotel_stars.currentData() or 0
        if minimum:
            hotels = [h for h in hotels if h["rating"] >= minimum]
        sort = self.hotel_sort.currentData()
        if sort == "price":
            hotels.sort(key=lambda h: h["nightly_price"])
        elif sort == "name":
            hotels.sort(key=lambda h: h["name"].lower())
        else:
            hotels.sort(key=lambda h: (-h["rating"], h["name"].lower()))
        self.hotel_results.addWidget(label(f"Отелей найдено: {len(hotels)}", "heading"))
        if self.hotel_source == "openstreetmap":
            self.hotel_results.addWidget(label(
                "Сведения о гостиницах: © участники OpenStreetMap (ODbL). "
                "Категория — количество звёзд, указанное в справочнике, не оценка гостей. "
                "Цены ориентировочные, наличие номеров не проверяется.", "small"))
        else:
            self.hotel_results.addWidget(label(
                "Показан сохранённый справочник существующих отелей с адресами и "
                "официальными сайтами. Текущие тарифы и наличие номеров необходимо уточнять "
                "в самих гостиницах.", "small"))
        if self.hotel_warning:
            self.hotel_results.addWidget(label(self.hotel_warning, "small"))
        if not hotels:
            self.hotel_results.addWidget(label("Для этого города пока нет подходящих вариантов."))
        for hotel in hotels:
            row = QHBoxLayout()
            row.setContentsMargins(16, 16, 16, 16)
            row.setSpacing(18)
            row.addWidget(HotelArt())
            info = QVBoxLayout()
            info.addWidget(label(hotel["name"], "heading"))
            stars = "★" * int(hotel["rating"]) if hotel["rating"] else "Категория не указана"
            info.addWidget(label(stars + "  •  " + hotel["district"], "star"))
            info.addWidget(label(hotel["description"], "subheading"))
            info.addWidget(label(hotel["amenities"], "small"))
            if hotel.get("website") or hotel.get("address"):
                links = QHBoxLayout()
                map_button = button("На карте")
                if hotel.get("latitude") is not None:
                    map_url = (f"https://www.openstreetmap.org/?mlat={hotel['latitude']}&"
                               f"mlon={hotel['longitude']}#map=17/{hotel['latitude']}/{hotel['longitude']}")
                else:
                    map_url = "https://www.openstreetmap.org/search?query=" + quote(
                        f"{hotel['city']}, {hotel['address']}")
                map_button.clicked.connect(
                    lambda _=False, url=map_url: QDesktopServices.openUrl(QUrl(url)))
                links.addWidget(map_button)
                if hotel.get("website"):
                    site_button = button("Сайт отеля")
                    site_button.clicked.connect(
                        lambda _=False, url=hotel["website"]: QDesktopServices.openUrl(QUrl(url)))
                    links.addWidget(site_button)
                links.addStretch()
                info.addLayout(links)
            row.addLayout(info, 1)
            aside = QVBoxLayout()
            prefix = "≈ " if hotel.get("estimated_price") else ""
            aside.addWidget(label(prefix + f"{hotel['total_price']:,} ₽".replace(",", " "), "price"))
            aside.addWidget(label(f"за {hotel['nights']} ноч.", "small"))
            if hotel.get("estimated_price"):
                aside.addWidget(label("Оценка, не тариф отеля", "small"))
            reserve = button("Оформить заявку", True)
            reserve.clicked.connect(lambda _=False, h=hotel, q=self.hotel_query: self.book_hotel(h, q))
            aside.addWidget(reserve)
            row.addLayout(aside)
            self.hotel_results.addWidget(panel(row, "offer"))

    def book_hotel(self, hotel, query):
        dialog = HotelForm(self, hotel, self.email, query["check_in"],
                           query["check_out"], query["guests"])
        if dialog.exec() != QDialog.Accepted:
            return
        self.email = dialog.email.text()
        self.settings.setValue("email", self.email)
        self.invoke(HOTELS_QUEUE, {"action": "book", "user_id": self.user_id,
                    "hotel_id": hotel["id"], "guest_name": dialog.name.text(),
                    "email": dialog.email.text(), "check_in": query["check_in"],
                    "check_out": query["check_out"], "guests": query["guests"]},
                    lambda result: self.offer_payment("hotel", result))

    def load_hotel_bookings(self):
        self.hotel_filters_panel.setVisible(False)
        self.clear_results(self.hotel_results, "Загружаем проживание…")
        self.invoke(HOTELS_QUEUE, {"action": "list", "user_id": self.user_id},
                    self.show_hotel_bookings, self.hotel_bookings_btn)

    def show_hotel_bookings(self, result):
        self.clear_results(self.hotel_results, "")
        self.hotel_results.addWidget(label("Мои бронирования отелей", "heading"))
        if not result["bookings"]:
            self.hotel_results.addWidget(label("Бронирований пока нет."))
        for booking in result["bookings"]:
            title = f"№ {booking['id']}  •  {booking['hotel_name']} ({booking['city']})"
            subtitle = (f"{booking['check_in']} — {booking['check_out']}  •  "
                        f"{booking['guest_name']}  •  {booking['price']:,} ₽")
            self.hotel_results.addWidget(self.booking_card(title, subtitle, booking, "hotel"))

    def closeEvent(self, event):
        # Позволяем запросам завершиться и не удаляем QThread до остановки работы.
        if self.jobs:
            QMessageBox.information(self, "Подождите", "Дождитесь завершения запроса")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("лЕТИМдЕШЕВО Demo")
    stylesheet = Path(__file__).with_name("style.qss").read_text(encoding="utf-8")
    app.setStyleSheet(stylesheet)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
