FROM python:3.10

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY eventi.json .


CMD ["bash", "-c", "python cassandra_init.py && python load_events.py && python app.py"]