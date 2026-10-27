import logging
from common.broker import serve
from common.config import PAYMENTS_QUEUE
from common.db import init
from services.payments import PaymentService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [payments] %(message)s")
    init()
    serve(PAYMENTS_QUEUE, PaymentService().handle)
