# EventAlert 

##  Descrizione
**EventAlert** è un sistema di **notifica eventi personalizzati basato su sottoscrizione**.  
Gli utenti possono registrarsi, selezionare i propri interessi (es. musica, sport, musei, cibo) e ricevere notifiche quando vengono creati nuovi eventi corrispondenti.  

Il sistema integra:
- **Frontend HTML**: interfaccia semplice per utenti e amministratori.  
- **Backend Flask + Cassandra**: gestione utenti, eventi e partecipazioni.  
- **Kafka + Redis**: infrastruttura di **messaggistica e matching** tra eventi e interessi utenti.  
- **Dispatcher**: microservizio che “notifica” automaticamente gli utenti interessati quando un nuovo evento viene creato.  

Grazie all’**esternalizzazione delle API tramite Nginx**, il backend è **accessibile come API REST indipendenti**, permettendo lo sviluppo di **client separati** (app mobile, bot, ecc.) senza dipendere dal frontend HTML.

---

##  Scopi del progetto
- **Gestione eventi**: creazione, consultazione e partecipazione ad eventi.  
- **Personalizzazione**: ogni utente riceve solo eventi in base ai propri interessi.  
- **Notifiche automatiche**: un dispatcher intercetta i nuovi eventi e segnala agli utenti interessati.  
- **Architettura a microservizi**: ogni componente è indipendente e orchestrato con Docker Compose.  
- **Backend esternalizzato via API**: possibile integrare client esterni senza usare l’HTML integrato.  

---

##  Suddivisione delle Cartelle 

```text 
EventAlert/
│
├── docker-compose.yaml          # orchestrazione servizi
├── nginx.conf                   # configurazione reverse proxy Nginx
│
├── frontend/                    # pagine HTML
│   ├── index.html                # login
│   ├── register.html             # registrazione
│   ├── main_admin.html           # dashboard admin
│   ├── main_utente.html          # dashboard utente
│   ├── create_event.html         # form creazione evento
│   ├── tickets.html              # visualizzazione biglietti
|   ├── account.html
|   └── Dockerfile           
│
├── services/
│   ├── subscriptions/            # backend principale Flask
│   │   ├── app.py                 # API + logica backend
│   │   ├── cassandra_init.py      # script per inizializzare tabelle Cassandra
│   │   ├── load_events.py         # caricamento eventi esterni + publish Kafka
│   │   ├── eventi.json            # dataset di esempio
│   │   ├── requirements.txt
|   |   └── Dockerfile  
│   │
│   └── dispatcher/               # microservizio consumer Kafka
│       ├── dispatcher.py          # ascolta topic event_created
│       ├── requirements.txt  
│       ├── notifica_utils.py
│       ├── retry_worker.py
│       └── dockerfile

```
--- 

##  Architettura & Tecnologie

### **Database**
- **Cassandra**:  
  - Tabella `users`: dati utente e interessi (email, nome, cognome, età, ruolo, interessi, password.  
  - Tabella `events`: eventi creati (id_evento, interesse, data_pubblicazione, data_evento, ora_evento, luogo_evento, origine, descrizione).  
  - Tabella `partecipazioni`: relazioni utente ↔ evento (email, id_evento).  

### **Messaggistica**
- **Kafka**: topic `event_created` per la pubblicazione dei nuovi eventi.  
- **Redis**: mantiene insiemi di utenti per ogni interesse (`interesse:jazz` → elenco email).  

### **Backend**
- **Flask**:  
  - Espone API REST per utenti, eventi, partecipazioni.  
  - Gestisce interazione con Cassandra, Redis e Kafka. 

### **Microservizi**
1. **Subscriptions**  
   - Gestisce utenti, eventi e partecipazioni.  
   - Fornisce API per login, registrazione, CRUD eventi e iscrizioni.  

2. **Dispatcher**  
   - Consumer Kafka (`event_created`).  
   - Per ogni nuovo evento recupera da Redis gli utenti interessati e simula invio notifica.  

---

##  Esternalizzazione API

Per rendere i microservizi accessibili dall’esterno è stato introdotto un **reverse proxy Nginx**:

- **App HTML** → disponibile su `http://localhost/`  
- **API REST** → raggiungibili su `http://localhost/api/...`  

--- 
## Comandi utili

### Avvio dello stack
```bash
docker compose up -d --build
```
### Inizializzazione di Cassandra
```bash
docker exec -it cassandra python /app/cassandra_init.py
```
### Log di un servizio (es. Dispatcher) 
```bash
docker logs -f dispatcher
```
### Fermare tutti i container e cancellare i volumi
```bash
docker compose down
```
### Visualizzare tutti i container attivi
```bash
docker compose ps
```
### Visualizzare tutte le immagini Docker presenti sul sistema
```bash
docker compose images
```
### Eseguire query sul database Cassandra
```bash
docker exec -it cassandra cqlsh
```
### Eliminare container Docker
```bash
docker rm nome_container
```
### Eliminare immagine Docker
```bash
docker rmi nome_immagine
```
### Eliminare volume
```bash
docker volume rm nome_volume
```
### Eliminare tutti i volumi non utilizzati
```bash
docker volume prune
```
---

## Comandi per testare le API 

### Verificare lo stato del sistema 
```bash
curl http://localhost/api/
```

### Registrazione di un utente 
```bash
curl -X POST http://localhost/api/register -H "Content-Type: application/json" -d '{
    "nome": "Mario",
    "cognome": "Rossi",
    "email": "utente@example.com",
    "ruolo": "utente",
    "eta": 25,
    "password": "password123",
    "interessi": ["pop", "house"]
  }'
```

### Informazioni del profilo dell'utente 
```bash
curl "http://localhost/api/account?email=utente@example.com"
```

### Creazione di un evento 
```bash
curl -X POST http://localhost/api/create_event \
  -H "Content-Type: application/json" \
  -d '{
    "interesse": "pop",
    "data_evento": "2025-10-10",
    "ora_evento": "21:00",
    "luogo_evento": "Roma, Auditorium",
    "descrizione": "Concerto jazz live"
  }'
```

### Aggiornamento degli interessi di un utente 
```bash
curl -X PUT http://localhost/api/update_interessi \
  -H "Content-Type: application/json" \
  -d '{
    "email": "utente@example.com",
    "interessi": ["jazz", "sport"]
  }'
```

### Lista degli eventi di interesse per l'utente 
```bash
curl "http://localhost/api/eventi_utente?email=utente@example.com"
```

### Partecipazione di un utente ad un evento
```bash
curl -X POST http://localhost/api/partecipa_evento \
  -H "Content-Type: application/json" \
  -d '{
    "email": "utente@example.com",
    "id_evento": "ID_EVENTO_GENERATO"
  }'
```

### Lista degli eventi partecipati dall'utente 
```bash
curl "http://localhost/api/eventi_partecipati?email=utente@example.com"
```

### Eliminazione della partecipazione ad un evento da parte di un utente
```bash
curl -X DELETE http://localhost/api/annulla_partecipazione \
  -H "Content-Type: application/json" \
  -d '{
    "email": "utente@example.com",
    "id_evento": "ID_EVENTO_GENERATO"
  }'
```
