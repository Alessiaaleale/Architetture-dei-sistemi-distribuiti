from flask import Flask, request, jsonify, url_for, redirect, render_template, send_from_directory
from flask_cors import CORS
from cassandra.cluster import Cluster
from datetime import date, datetime
import uuid
import redis
from kafka import KafkaProducer
import json

app = Flask(__name__)
CORS(app)

redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

def get_db_session():
    cluster = Cluster(['cassandra'])
    session = cluster.connect()
    session.set_keyspace('eventalert')
    return session

def to_py_date(cass_date) -> date:
    if isinstance(cass_date, date):
        return cass_date
    try:
        return date(cass_date.year, cass_date.month, cass_date.day)
    except Exception:
        return datetime.strptime(str(cass_date), "%Y-%m-%d").date()

def combine_event_datetime(row) -> datetime:
    d = to_py_date(row.data_evento)
    raw = str(row.ora_evento).strip()
    try:
        tm = datetime.strptime(raw[:5], "%H:%M").time()
    except ValueError:
        tm = datetime.strptime(raw, "%H:%M:%S").time()
    return datetime.combine(d, tm)

def parse_client_now(arg_now: str | None) -> datetime:
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

@app.route('/')
def redirect_to_login():
    return redirect(url_for('index'))

# REGISTRAZIONE
@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()

    required_fields = ['nome', 'cognome', 'email', 'ruolo', 'eta', 'password']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Dati mancanti'}), 400

    if data['ruolo'] not in ['admin', 'utente']:
        return jsonify({'error': 'Ruolo non valido'}), 400

    email = data['email']
    eta = data['eta']
    interessi = data.get('interessi', [])
    password = data['password']

    session = get_db_session()

    # Controllo duplicato email
    existing_user = session.execute(
        "SELECT email FROM users WHERE email = %s",
        (email,)
    ).one()

    if existing_user:
        return jsonify({'error': 'Email già presente nel database'}), 400

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

# CREAZIONE EVENTO
@app.route('/create_event', methods=['POST'])
def create_event():
    producer = KafkaProducer(
        bootstrap_servers='kafka:9092',
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    data = request.get_json()
    required_fields = ['interesse', 'data_evento', 'ora_evento', 'luogo_evento', 'descrizione']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Dati mancanti'}), 400

    session = get_db_session()

    interesse = data['interesse']
    data_evento = datetime.strptime(data['data_evento'], "%Y-%m-%d").date()
    ora_evento = data['ora_evento']
    luogo_evento = data['luogo_evento']
    descrizione = data['descrizione']
    origine =  data.get('email',)
    data_pubblicazione = date.today()

    id_evento = f"{interesse}{data_evento}{ora_evento.replace(':', '')}_{str(uuid.uuid4())[:8]}"

    existing = session.execute(
        "SELECT id_evento FROM events WHERE id_evento = %s",
        (id_evento,)
    ).one()
    if existing:
        return jsonify({'error': 'Evento già esistente'}), 400

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
        producer.send("event_created", {
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

# LOGIN
@app.route('/index', methods=['POST'])
def login_user():
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

# EVENTI ADMIN 
@app.route('/eventi_admin', methods=['GET'])
def eventi_admin():
    email = request.args.get('email')
    client_now = request.args.get('now')
    if not email:
        return jsonify({'error': 'Email non specificata'}), 400

    session = get_db_session()

    user_row = session.execute("SELECT ruolo, interessi FROM users WHERE email = %s", [email]).one()
    if not user_row:
        return jsonify({'error': 'Utente non trovato'}), 404

    if user_row.ruolo == "admin":
        rows = session.execute("""
            SELECT id_evento, interesse, data_pubblicazione, data_evento,
                   ora_evento, luogo_evento, descrizione, origine
            FROM events
            WHERE origine=%s ALLOW FILTERING
        """, [email])

        eventi = []
        for row in rows:
            eventi.append({
                "id_evento": row.id_evento,
                "interesse": row.interesse,
                "data_pubblicazione": str(row.data_pubblicazione),
                "data_evento": str(row.data_evento),
                "ora_evento": row.ora_evento,
                "luogo_evento": row.luogo_evento,
                "descrizione": row.descrizione,
                "origine": row.origine
            })
        return jsonify({"eventi": eventi})

    else:
        now = parse_client_now(client_now)
        interessi = user_row.interessi
        eventi = []

        for interesse in interessi:
            rows = session.execute("SELECT * FROM events WHERE interesse = %s ALLOW FILTERING", [interesse])
            for row in rows:
                evento_dt = combine_event_datetime(row)
                if evento_dt >= now:
                    eventi.append((evento_dt, row_to_dict(row)))

        eventi.sort(key=lambda x: x[0])
        return jsonify({'eventi': [e[1] for e in eventi]})

@app.route('/eventi_admin_creati', methods=['GET'])
def eventi_admin_creati():
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email non specificata"}), 400

    session = get_db_session()
    rows = session.execute("""
        SELECT id_evento, interesse, data_pubblicazione, data_evento,
               ora_evento, luogo_evento, descrizione, origine
        FROM events
        WHERE origine = %s ALLOW FILTERING
    """, [email])

    eventi = []
    for row in rows:
        eventi.append({
            "id_evento": row.id_evento,
            "interesse": row.interesse,
            "data_pubblicazione": str(row.data_pubblicazione),
            "data_evento": str(row.data_evento),
            "ora_evento": row.ora_evento,
            "luogo_evento": row.luogo_evento,
            "descrizione": row.descrizione,
            "origine": row.origine
        })

    return jsonify(eventi)

# EVENTI UTENTE 
@app.route('/main_utente')
def main_utente():
    email = request.args.get('email')
    if not email:
        return "Email non specificata", 400

    session = get_db_session()

    query_user = session.execute("SELECT interessi FROM users WHERE email = %s", [email])
    user = query_user.one()
    if not user:
        return "Utente non trovato", 404

    interessi = user.interessi
    eventi = []

    for interesse in interessi:
        rows = session.execute("SELECT * FROM events WHERE interesse = %s ALLOW FILTERING", [interesse])
        eventi.extend(rows)

    return render_template("main_utente.html", eventi=eventi, email=email)

@app.route('/eventi_utente', methods=['GET'])
def eventi_utente():
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

    eventi.sort(key=lambda x: x[0])
    return jsonify({'eventi': [e[1] for e in eventi]})


@app.route('/account', methods=['GET'])
def get_account():
    email = request.args.get('email')
    if not email:
        return jsonify({'error': 'Email mancante'}), 400

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
    data = request.get_json()
    email = data.get("email")
    interessi = data.get("interessi")

    if not email or interessi is None:
        return jsonify({"error": "Email o interessi mancanti"}), 400

    session = get_db_session()
    session.execute(
        "UPDATE users SET interessi = %s WHERE email = %s",
        [interessi, email]
    )

    return jsonify({"message": "Interessi aggiornati con successo!"})

@app.route('/partecipa_evento', methods=['POST'])
def partecipa_evento():
    data = request.get_json()
    email = data.get("email")
    id_evento = data.get("id_evento")

    if not email or not id_evento:
        return jsonify({"error": "Email o id_evento mancanti"}), 400

    session = get_db_session()
    session.execute(
        "INSERT INTO partecipazioni (email, id_evento) VALUES (%s, %s)",
        [email, id_evento]
    )

    return jsonify({"message": "Partecipazione registrata con successo!"})

@app.route('/eventi_partecipati', methods=['GET'])
def eventi_partecipati():
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
    data = request.get_json()
    email = data.get("email")
    id_evento = data.get("id_evento")

    if not email or not id_evento:
        return jsonify({"error": "Email o id_evento mancanti"}), 400

    session = get_db_session()
    session.execute(
        "DELETE FROM partecipazioni WHERE email=%s AND id_evento=%s",
        [email, id_evento]
    )

    return jsonify({"message": "Partecipazione annullata con successo!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)