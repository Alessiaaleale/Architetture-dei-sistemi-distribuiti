import json
import uuid
from datetime import datetime, date
from cassandra.cluster import Cluster
from kafka import KafkaProducer

KEYSPACE = "eventalert"
JSON_FILE = "eventi.json"  # Assicurati che il file sia nella stessa directory

def get_db_session():
    cluster = Cluster(['cassandra'])
    session = cluster.connect()
    session.set_keyspace(KEYSPACE)
    return session

def main():
    # Kafka setup
    producer = KafkaProducer(
        bootstrap_servers='kafka:9092',
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

    # Cassandra session
    session = get_db_session()

    # Carica eventi dal file JSON
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        eventi = json.load(f)

    for evento in eventi:
        try:
            interesse = evento['interesse']
            data_evento = datetime.strptime(evento['data_evento'], "%Y-%m-%d").date()
            ora_evento = evento['ora_evento']
            luogo_evento = evento['luogo_evento']
            descrizione = evento['descrizione']
            data_pubblicazione = datetime.strptime(evento['data_pubblicazione'], "%Y-%m-%d").date()
            origine = evento['origine']

            id_evento = f"{data_evento.strftime('%Y%m%d')}_{ora_evento.replace(':', '')}_{luogo_evento.replace(' ', '_')}_{origine}_{interesse}"
            # Verifica se l'evento esiste già
            existing = session.execute(
                "SELECT id_evento FROM events WHERE id_evento = %s", (id_evento,)
            ).one()

            if existing:
                print(f"❌ Evento già esistente: {id_evento}")
                continue

            # Inserimento in Cassandra
            session.execute("""
                INSERT INTO events (
                    id_evento, interesse, data_pubblicazione, data_evento,
                    ora_evento, luogo_evento, origine, descrizione
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                id_evento, interesse, data_pubblicazione, data_evento,
                ora_evento, luogo_evento, origine, descrizione
            ))

            # Invio su Kafka
            producer.send("event_created", {
                "id_evento": id_evento,
                "interesse": interesse,
                "luogo_evento": luogo_evento,
                "data_evento": data_evento.strftime("%Y-%m-%d"),
                "ora_evento": ora_evento,
                "origine": origine,
                "descrizione": descrizione
            })

            print(f"✅ Evento inserito e inviato: {id_evento}")

        except Exception as e:
            print(f"⚠️ Errore con evento {evento}: {str(e)}")

    producer.flush()

if __name__ == "__main__":
    main()