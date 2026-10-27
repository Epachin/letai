import logging
from common.broker import serve
from common.config import FLIGHTS_QUEUE
from common.db import init
from services.flights import FlightService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [flights] %(message)s")
    init()
    serve(FLIGHTS_QUEUE, FlightService().handle)
