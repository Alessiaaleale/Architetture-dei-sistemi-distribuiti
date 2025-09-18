from cassandra.cluster import Cluster
import time

KEYSPACE = "eventalert"

def create_schema(session):
    session.execute(f"""
        CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
        WITH replication = {{ 'class': 'SimpleStrategy', 'replication_factor': '1' }}
    """)
    session.set_keyspace(KEYSPACE)
    session.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            nome TEXT,
            cognome TEXT,
            eta INT,
            ruolo TEXT,
            interessi LIST<TEXT>,
            password TEXT
        )
    """)

    session.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id_evento TEXT PRIMARY KEY,
            interesse TEXT,
            data_pubblicazione DATE,
            data_evento DATE,
            ora_evento TEXT,
            luogo_evento TEXT,
            origine TEXT,
            descrizione TEXT
        )
    """)

    session.execute("""
        CREATE TABLE IF NOT EXISTS partecipazioni (
            email TEXT,
            id_evento TEXT,
            PRIMARY KEY (email, id_evento)
        )
    """)

def main():
    connected = False
    while not connected:
        try:
            cluster = Cluster(['cassandra'])
            session = cluster.connect()
            create_schema(session)
            print("✅ Keyspace e tabella creati correttamente.")
            connected = True
        except Exception as e:
            print(f"⏳ Cassandra non ancora pronta. Riprovo... {str(e)}")
            time.sleep(5)

if __name__== "__main__":
    main()