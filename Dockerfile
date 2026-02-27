FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# This is the secret sauce for Option 2:
ENV PYTHONPATH=/app 

RUN addgroup --system hbgroup && adduser --system --group hbuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# This copies your local 'src' contents into '/app'
# So inside the container, the file is at /app/heartbeat_backend/hbserver.py
COPY src/ .

RUN mkdir -p /app/logs && chown -R hbuser:hbgroup /app
RUN python manage.py collectstatic --noinput
RUN chown -R hbuser:hbgroup /app/staticfiles
USER hbuser

EXPOSE 8333/tcp
EXPOSE 8333/udp

# We run the script using its path relative to /app
CMD ["python", "heartbeat_backend/hbserver.py", "--production", "--public", "--db", "/data/hbdb.sqlite3"]