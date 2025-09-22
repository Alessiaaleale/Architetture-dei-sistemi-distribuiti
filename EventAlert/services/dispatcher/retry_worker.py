import logging
import time
import redis
import json
from notifica_utils import invia_notifica

logging.basicConfig(level=logging.INFO)
redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

def retry_worker():
    '''
    Worker che gestisce i ritentativi di invio delle notifiche fallite.
    '''
    while True:
        raw = redis_client.lpop("failed_notifications")
        if raw:
            payload = json.loads(raw)
            retry_count = payload.get("retry_count", 0)
            email = payload["email"]
            event = payload["evento"]
            event_id = event["id_evento"]
            id_unico = payload.get("id_unico", f"{email}_{event_id}")

            if redis_client.sismember("notifiche_inviate_global", id_unico):
                logging.info(f"[Ritentativo] Notifica già gestita: {id_unico}. Ignorata.")
                continue

            try:
                invia_notifica(email, event)
                redis_client.sadd(f"notifiche_inviate:{email}", event_id)
                redis_client.sadd("notifiche_inviate_global", id_unico)
                logging.info(f" [Ritentativo] Notifica inviata a {email} per evento {event_id}")
            except Exception as e:
                retry_count += 1
                if retry_count < 3:
                    payload["retry_count"] = retry_count
                    payload["id_unico"] = id_unico
                    redis_client.rpush("failed_notifications", json.dumps(payload))
                    logging.warning(f" Ritentativo {retry_count} fallito per {email}")
                else:
                    logging.error(f" Notifica eliminata dopo 3 fallimenti: {email} → {event_id}")
        time.sleep(5)

if __name__ == "__main__":
    retry_worker()
