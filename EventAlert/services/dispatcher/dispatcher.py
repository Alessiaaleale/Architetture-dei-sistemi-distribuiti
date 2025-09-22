import time
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient
import redis
import json
import logging
from notifica_utils import invia_notifica

logging.basicConfig(level=logging.INFO)

def wait_for_kafka_and_topic(topic, retries=30, delay=1):
    '''
    Attende che Kafka e il topic specificato siano pronti.
    '''
    for i in range(retries):
        try:
            admin = KafkaAdminClient(bootstrap_servers='kafka:9092')
            topics = admin.list_topics()
            if topic in topics:
                logging.info(f" Topic '{topic}' disponibile.")
                return
            else:
                logging.info(f" Topic '{topic}' non ancora disponibile. Tentativo {i+1}/{retries}")
        except Exception as e:
            logging.warning(f"Kafka non pronto: {e}")
        time.sleep(delay)
    raise Exception(f" Timeout: il topic '{topic}' non è disponibile dopo {retries} tentativi.")

# Attesa che Kafka e il topic 'event_created' siano pronti
wait_for_kafka_and_topic('event_created')

# Connessione a Redis
redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

# Connessione a Kafka
consumer = KafkaConsumer(
    'event_created',
    bootstrap_servers='kafka:9092',
    group_id='dispatcher-group',
    enable_auto_commit=False,
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

for message in consumer:
    event = message.value
    event_id = event["id_evento"]
    interesse = event.get("interesse")

    if not interesse:
        logging.warning("Evento ricevuto senza interesse. Ignorato.")
        continue

    lock_key = f"evento_lock:{event_id}"
    if not redis_client.set(lock_key, "1", nx=True, ex=300):
        logging.info(f"Evento già in elaborazione o gestito: {event_id}. Ignorato.")
        continue

    logging.info(f" Nuovo evento ricevuto: {event}")
    redis_client.sadd("eventi_gestiti", event_id)

    user_emails = redis_client.smembers(f"interesse:{interesse}")
    for email in user_emails:
        key = f"notifiche_inviate:{email}"
        if redis_client.sismember(key, event_id):
            logging.info(f" Notifica già inviata a {email} per evento {event_id}. Ignorata.")
            continue

        invia_notifica(email, event)
        redis_client.sadd(key, event_id)

    consumer.commit()
