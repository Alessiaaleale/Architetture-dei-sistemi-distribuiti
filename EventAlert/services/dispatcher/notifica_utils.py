import logging

def invia_notifica(email, event):
    '''
    Invia una notifica associata a un evento via email.
    '''
    try:
        logging.info(f"Notifica inviata a {email} per evento {event['id_evento']}")
    except Exception as e:
        logging.warning(f"Invio fallito per {email}: {e}")