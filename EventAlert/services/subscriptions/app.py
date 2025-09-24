from flask import Flask, request, jsonify
from flask_cors import CORS
from cassandra.cluster import Cluster
from datetime import date, datetime, time
import socket
import redis
from kafka import KafkaProducer
import json

app = Flask(__name__)
CORS(app)

redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

def get_db_session():
    ''' 
    Connessione a Cassandra 
    '''
    cluster = Cluster(['cassandra'])
    session = cluster.connect()
    session.set_keyspace('eventalert')
    return session

def to_py_date(cass_date) -> date:
    ''' 
    Converte una data Cassandra in una data Python 
    '''
    if isinstance(cass_date, date):
        return cass_date
    try:
        return date(cass_date.year, cass_date.month, cass_date.day)
    except Exception:
        return datetime.strptime(str(cass_date), "%Y-%m-%d").date()

def combine_event_datetime(row) -> datetime:
    ''' 
    Combina data_evento e ora_evento in un singolo datetime
    '''
    d = to_py_date(row.data_evento)
    # accetta 'HH:MM' o 'HH:MM:SS' 
    raw = str(row.ora_evento).strip()
    try:
        tm = datetime.strptime(raw[:5], "%H:%M").time()
    except ValueError:
        tm = datetime.strptime(raw, "%H:%M:%S").time()
    return datetime.combine(d, tm)

def parse_client_now(arg_now: str | None) -> datetime:
    ''' 
     Parsa la stringa 'now' dal client in un datetime
     '''
    if not arg_now:
        return datetime.now()
    candidates = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(arg_now, fmt)
            return dt
        except ValueError:
            continue
    return datetime.now()

def row_to_dict(row) -> dict:
    '''
    Converte una riga Cassandra in un dizionario
    '''
    return {
        'id_evento': row.id_evento,
        'interesse': row.interesse,
        'data_pubblicazione': str(row.data_pubblicazione) if hasattr(row, "data_pubblicazione") else None,
        'data_evento': str(row.data_evento),
        'ora_evento': row.ora_evento,
        'luogo_evento': row.luogo_evento,
        'origine': row.origine,
        'descrizione': row.descrizione
    }

def check_service(host, port):
    ''' 
    Controlla se un servizio è raggiungibile sulla porta specificata
    '''
    try:
        socket.create_connection((host, port), timeout=2)
        return True
    except Exception:
        return False

@app.route('/')
def health_check():
    '''
    Endpoint di health check per tutti i servizi
    '''
    status = {
        'cassandra': check_service('cassandra', 9042),
        'redis': check_service('redis', 6379),
        'kafka': check_service('kafka', 9092),
        'zookeeper': check_service('zookeeper', 2181),
        'frontend': check_service('frontend', 80),      
    }
    return jsonify(status)

@app.route('/register', methods=['POST'])
def register_user():
    '''
    Endpoint per la registrazione di un nuovo utente
    '''
    data = request.get_json()

    required_fields = ['nome', 'cognome', 'email', 'ruolo', 'eta', 'password', 'interessi']
    for field in required_fields:
        if field not in data or (isinstance(data[field], str) and not data[field].strip()) or (isinstance(data[field], list) and not data[field]):
            return jsonify({'error': f'Dato mancante o vuoto: {field}'}), 400

    if data['ruolo'] not in ['admin', 'utente']:
        return jsonify({'error': 'Ruolo non valido'}), 400

    email = data['email']
    eta = data['eta']
    interessi = data['interessi']
    password = data['password']

    session = get_db_session()

    # Controllo duplicato email
    existing_user = session.execute(
        "SELECT email FROM users WHERE email = %s",
        (email,)
    ).one()

    if existing_user:
        return jsonify({'error': 'Email presente nel database'}), 400

    try:
        session.execute(
            """
            INSERT INTO users (email, nome, cognome, eta, ruolo, interessi, password)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (email, data['nome'], data['cognome'], eta, data['ruolo'], interessi, password)
        )
        for interesse in interessi:
            redis_client.sadd(f"interesse:{interesse}", email)
        return jsonify({'message': 'Utente registrato con successo'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/create_event', methods=['POST'])
def create_event():
    '''
    Endpoint per la creazione di un nuovo evento
    '''
    producer = KafkaProducer(
        bootstrap_servers='kafka:9092',
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all'
    )
    data = request.get_json()
    required_fields = ['interesse', 'data_evento', 'ora_evento', 'luogo_evento', 'descrizione','ruolo']
    for field in required_fields:
        if field not in data or (isinstance(data[field], str) and not data[field].strip()) or (isinstance(data[field], list) and not data[field]):
            return jsonify({'error': f'Dato mancante o vuoto: {field}'}), 400
        
    if data['ruolo'].lower() != 'admin':
        return jsonify({'error': 'Permessi mancanti per questa azione'}), 403

    try:
        ora_evento_obj = datetime.strptime(data['ora_evento'], "%H:%M").time()
    except ValueError:
        return jsonify({'error': 'Formato ora non valido. Usa HH:MM'}), 400

    if not (time(0, 0) <= ora_evento_obj <= time(23, 59)):
        return jsonify({'error': 'Orario non valido. Deve essere tra 00:00 e 23:59'}), 400
    
    try:
        data_evento = datetime.strptime(data['data_evento'], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({'error': 'Data non valida. Assicurati che il giorno e il mese siano corretti (formato YYYY-MM-DD)'}), 400

    if data_evento < date.today():
        return jsonify({'error': 'La data dell\'evento non deve essere precedente ad oggi'}), 400

    session = get_db_session()

    interesse = data['interesse']
    data_evento = datetime.strptime(data['data_evento'], "%Y-%m-%d").date()
    ora_evento = data['ora_evento']
    luogo_evento = data['luogo_evento']
    descrizione = data['descrizione']
    origine = "admin"
    data_pubblicazione = date.today()

    id_evento = f"{data_evento.strftime('%Y%m%d')}_{ora_evento.replace(':', '')}_{luogo_evento.replace(' ', '_')}_{origine}_{interesse}"

    existing = session.execute(
        "SELECT id_evento FROM events WHERE id_evento = %s",
        (id_evento,)
    ).one()
    if existing:
        return jsonify({'error': 'Evento esistente'}), 400

    try:
        session.execute(
            """
            INSERT INTO events (id_evento, interesse, data_pubblicazione, data_evento,
            ora_evento, luogo_evento, origine, descrizione)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (id_evento, interesse, data_pubblicazione, data_evento,
             ora_evento, luogo_evento, origine, descrizione)
        )
        producer.send("event_created", key=id_evento.encode('utf-8'), value={
            "id_evento": id_evento,
            "interesse": interesse,
            "luogo_evento": luogo_evento,
            "data_evento": data_evento.strftime("%Y-%m-%d"),
            "ora_evento": ora_evento,
            "origine": origine,
            "descrizione": descrizione
        })
        producer.flush()
        return jsonify({'message': 'Evento creato con successo'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/index', methods=['POST'])
def login_user():
    '''
    Endpoint per il login dell'utente
    '''
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'Email e password obbligatorie'}), 400

    session = get_db_session()
    user = session.execute(
        "SELECT password, ruolo FROM users WHERE email = %s",
        (email,)
    ).one()

    if not user:
        return jsonify({'error': 'Utente non trovato'}), 404

    if user.password != password:
        return jsonify({'error': 'Password errata'}), 401

    # Redirect alla pagina in base al ruolo
    if user.ruolo == 'admin':
        return jsonify({
            'redirect': f'main_admin.html?email={email}',
            'ruolo': 'admin',
            'email': email
        })
    elif user.ruolo == 'utente':
        return jsonify({
            'redirect': f'main_utente.html?email={email}',
            'ruolo': 'utente',
            'email': email
        })
    else:
        return jsonify({'error': 'Ruolo non riconosciuto'}), 400

@app.route('/eventi_utente', methods=['GET'])
def eventi_utente():
    '''
    Endpoint per ottenere eventi basati sugli interessi dell'utente
    ''' 
    email = request.args.get('email')
    client_now = request.args.get('now')  
    if not email:
        return jsonify({'error': 'Email non specificata'}), 400

    session = get_db_session()
    query_user = session.execute("SELECT interessi FROM users WHERE email = %s", [email])
    user = query_user.one()
    if not user:
        return jsonify({'error': 'Utente non trovato'}), 404

    now = parse_client_now(client_now)
    interessi = user.interessi
    if not interessi or not isinstance(interessi, list):
        return jsonify({'error': "Nessun interesse associato all'utente"}), 404
    eventi = []

    for interesse in interessi:
        rows = session.execute("SELECT * FROM events WHERE interesse = %s ALLOW FILTERING", [interesse])
        for row in rows:
            evento_dt = combine_event_datetime(row)
            if evento_dt >= now:
                eventi.append((evento_dt, {
                    'id_evento': row.id_evento,
                    'interesse': row.interesse,
                    'data_pubblicazione': str(row.data_pubblicazione),
                    'data_evento': str(row.data_evento),
                    'ora_evento': row.ora_evento,
                    'luogo_evento': row.luogo_evento,
                    'origine': row.origine,
                    'descrizione': row.descrizione
                }))

    if not eventi:
        return jsonify({'message': 'Nessun evento disponibile per gli interessi dell\'utente'}), 200
    
    eventi.sort(key=lambda x: x[0])
    return jsonify({'eventi': [e[1] for e in eventi]})

@app.route('/account', methods=['GET'])
def get_account():
    '''
    Endpoint per ottenere i dettagli dell'account utente
    ''' 
    email = request.args.get("email")
    
    if not email :
        return jsonify({"error": "Email mancante"}), 400

    session = get_db_session()
    row = session.execute("SELECT nome, cognome, email, eta, ruolo, interessi FROM users WHERE email=%s", [email]).one()

    if not row:
        return jsonify({'error': 'Utente non trovato'}), 404

    return jsonify({
        'nome': row.nome,
        'cognome': row.cognome,
        'email': row.email,
        'eta': row.eta,
        'ruolo': row.ruolo,
        'interessi': row.interessi
    })

@app.route('/update_interessi', methods=['PUT'])
def update_interessi():
    '''
    Endpoint per aggiornare gli interessi dell'utente
    '''
    data = request.get_json()
    email = data.get("email")
    interessi = data.get("interessi")

    if not email or interessi is None:
        return jsonify({"error": "Email o interessi mancanti"}), 400
    
    if not isinstance(interessi, list) or len(interessi) == 0:
        return jsonify({"error": "Deve essere selezionato almeno un interesse"}), 400

    session = get_db_session()
    session.execute(
        "UPDATE users SET interessi = %s WHERE email = %s",
        [interessi, email]
    )

    return jsonify({"message": "Interessi aggiornati con successo!"})


@app.route('/partecipa_evento', methods=['POST'])
def partecipa_evento():
    '''
    Endpoint per registrare la partecipazione di un utente a un evento
    ''' 
    data = request.get_json()
    email = data.get("email")
    id_evento = data.get("id_evento")

    if not email or not id_evento:
        return jsonify({"error": "Email o id_evento mancanti"}), 400

    session = get_db_session()

    evento_esistente = session.execute(
            "SELECT id_evento FROM events WHERE id_evento = %s",
            (id_evento,)
        ).one()

    if not evento_esistente:
        return jsonify({"error": "L'evento specificato non esiste"}), 404

    try:
        session.execute(
            "INSERT INTO partecipazioni (email, id_evento) VALUES (%s, %s)",
            [email, id_evento]
        )
        return jsonify({"message": "Partecipazione registrata con successo!"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    

@app.route('/eventi_partecipati', methods=['GET'])
def eventi_partecipati():
    '''
    Endpoint per ottenere gli eventi a cui l'utente ha partecipato
    ''' 
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email mancante"}), 400

    session = get_db_session()
    rows = session.execute("SELECT id_evento FROM partecipazioni WHERE email=%s", [email])

    eventi_ids = [row.id_evento for row in rows]

    eventi = []
    for eid in eventi_ids:
        row = session.execute("SELECT * FROM events WHERE id_evento=%s", [eid]).one()
        if row:
            eventi.append({
                "id_evento": row.id_evento,
                "interesse": row.interesse,
                "data_evento": str(row.data_evento),
                "ora_evento": row.ora_evento,
                "luogo_evento": row.luogo_evento,
                "origine": row.origine,
                "descrizione": row.descrizione
            })

    return jsonify({"eventi": eventi})

@app.route('/annulla_partecipazione', methods=['DELETE'])
def annulla_partecipazione():
    '''
    Endpoint per annullare la partecipazione di un utente a un evento
    '''
    data = request.get_json()
    email = data.get("email")
    id_evento = data.get("id_evento")

    if not email or not id_evento:
        return jsonify({"error": "Email o id_evento mancanti"}), 400

    session = get_db_session()

    evento_esistente = session.execute(
        "SELECT id_evento FROM events WHERE id_evento = %s",
        (id_evento,)
    ).one()

    if not evento_esistente:
        return jsonify({"error": "L'evento specificato non esiste"}), 404

    try:
        session.execute(
            "DELETE FROM partecipazioni WHERE email=%s AND id_evento=%s",
            (email, id_evento)
        )
        return jsonify({"message": "Partecipazione annullata con successo!"}), 200
    except Exception as e:
        return jsonify({"error": f"Errore interno: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)