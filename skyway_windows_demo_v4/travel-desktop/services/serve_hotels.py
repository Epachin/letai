import logging
from common.broker import serve
from common.config import HOTELS_QUEUE
from common.db import init
from services.hotels import HotelService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [hotels] %(message)s")
    init()
    serve(HOTELS_QUEUE, HotelService().handle)
