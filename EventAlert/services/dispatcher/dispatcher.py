from kafka import KafkaConsumer
import redis
import json
import logging

logging.basicConfig(level=logging.INFO)

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