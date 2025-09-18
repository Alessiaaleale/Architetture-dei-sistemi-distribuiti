import time
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient
import redis
import json
import logging

# Configura logging
logging.basicConfig(level=logging.INFO)

# Funzione di attesa per Kafka e topic
def wait_for_kafka_and_topic(topic, retries=30, delay=1):
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

# Attendi che Kafka e il topic siano pronti
wait_for_kafka_and_topic('event_created')

# Connessione a Redis
redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

# Connessione a Kafka
consumer = KafkaConsumer(
    'event_created',
    bootstrap_servers='kafka:9092',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

logging.info("Dispatcher in ascolto sul topic 'event_created'...")

for message in consumer:
    event = message.value
    interesse = event.get("interesse", None)
    if not interesse:
        logging.warning("Evento ricevuto senza interesse. Ignorato.")
        continue

    logging.info(f"Nuovo evento ricevuto: {event}")

    # Recupera gli utenti interessati dal set Redis
    user_emails = redis_client.smembers(f"interesse:{interesse}")
    
    for email in user_emails:
        logging.info(f"Notifica per utente {email}: nuovo evento '{event['id_evento']}' "
             f"({event['interesse']}) → {event.get('descrizione', '')}")