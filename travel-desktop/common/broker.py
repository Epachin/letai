"""RPC через RabbitMQ: три независимые очереди, один синхронный клиент."""
import json
import logging
import time
from uuid import uuid4

import pika

from . import config
from .validation import InputError

log = logging.getLogger(__name__)


def connection():
    credentials = pika.PlainCredentials(config.RABBIT_USER, config.RABBIT_PASSWORD)
    return pika.BlockingConnection(pika.ConnectionParameters(
        host=config.RABBIT_HOST, port=config.RABBIT_PORT,
        credentials=credentials, heartbeat=30, blocked_connection_timeout=8,
        connection_attempts=1, socket_timeout=3,
    ))


def rpc(queue, payload, timeout=30):
    """Возвращает JSON ответа сервиса либо возбуждает TimeoutError/ConnectionError."""
    with connection() as con:
        channel = con.channel()
        channel.queue_declare(queue=queue, durable=True)
        callback_queue = channel.queue_declare(queue="", exclusive=True).method.queue
        correlation = uuid4().hex
        response = None

        def on_response(_ch, _method, props, body):
            nonlocal response
            if props.correlation_id == correlation:
                response = json.loads(body.decode("utf-8"))

        channel.basic_consume(queue=callback_queue, on_message_callback=on_response, auto_ack=True)
        channel.basic_publish(exchange="", routing_key=queue,
                              body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                              properties=pika.BasicProperties(
                                  reply_to=callback_queue, correlation_id=correlation,
                                  content_type="application/json", delivery_mode=2,
                              ))
        deadline = time.monotonic() + timeout
        while response is None and time.monotonic() < deadline:
            con.process_data_events(time_limit=min(.25, max(.01, deadline - time.monotonic())))
        if response is None:
            raise TimeoutError("Микросервис не ответил. Проверьте запуск всех процессов.")
        return response


def serve(queue, handler):
    """Запускает один независимый рабочий процесс; восстанавливает связь с брокером."""
    while True:
        try:
            with connection() as con:
                ch = con.channel()
                ch.queue_declare(queue=queue, durable=True)
                ch.basic_qos(prefetch_count=1)

                def on_request(channel, method, props, body):
                    try:
                        request = json.loads(body.decode("utf-8"))
                        if not isinstance(request, dict):
                            raise InputError("Ожидался JSON-объект")
                        result = handler(request)
                    except (InputError, ValueError) as exc:
                        result = {"status": "error", "error": str(exc)}
                    except Exception:
                        log.exception("Ошибка в обработчике %s", queue)
                        result = {"status": "error", "error": "Внутренняя ошибка микросервиса"}
                    try:
                        if props.reply_to:
                            channel.basic_publish(exchange="", routing_key=props.reply_to,
                                body=json.dumps(result, ensure_ascii=False).encode("utf-8"),
                                properties=pika.BasicProperties(correlation_id=props.correlation_id,
                                                                content_type="application/json"))
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                    except pika.exceptions.AMQPError:
                        log.exception("Не удалось ответить клиенту")
                        raise

                ch.basic_consume(queue=queue, on_message_callback=on_request)
                log.info("Сервис готов, очередь %s", queue)
                ch.start_consuming()
        except (pika.exceptions.AMQPError, OSError) as exc:
            log.warning("RabbitMQ недоступен (%s), повтор через 3 секунды", exc)
            time.sleep(3)
