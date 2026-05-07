import json
import logging
from confluent_kafka import Producer, Consumer, KafkaError

logger = logging.getLogger(__name__)


class KafkaProducer:
    def __init__(self, bootstrap_servers: str):
        self._producer = Producer({"bootstrap.servers": bootstrap_servers})

    def publish(self, topic: str, message: dict, key: str | None = None) -> None:
        self._producer.produce(
            topic,
            key=key.encode() if key else None,
            value=json.dumps(message).encode(),
            callback=self._delivery_report,
        )
        self._producer.flush()

    @staticmethod
    def _delivery_report(err, msg):
        if err:
            logger.error("Kafka delivery failed | topic=%s error=%s", msg.topic(), err)
        else:
            logger.debug("Kafka delivered | topic=%s partition=%d offset=%d",
                         msg.topic(), msg.partition(), msg.offset())


class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str]):
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        self._consumer.subscribe(topics)

    def consume(self, handler, poll_timeout: float = 1.0):
        logger.info("Consumer started, topics=%s", self._consumer.assignment())
        try:
            while True:
                msg = self._consumer.poll(poll_timeout)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("Consumer error: %s", msg.error())
                    continue
                try:
                    data = json.loads(msg.value().decode())
                    handler(data)
                except Exception as exc:
                    logger.exception("Handler raised exception: %s", exc)
                finally:
                    self._consumer.commit(message=msg)
        finally:
            self._consumer.close()
