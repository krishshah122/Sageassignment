FROM python:3.12-slim

WORKDIR /srv
COPY backend/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY backend /srv
ENV PYTHONPATH=/srv

CMD ["python", "-m", "app.temporal.worker"]
