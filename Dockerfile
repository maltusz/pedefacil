FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    pkg-config \
    gcc \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libglib2.0-0 \
    libcairo2 \
    libmariadb3 \
    libmariadb-dev-compat \
    mariadb-client \
    nginx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY nginx.conf /etc/nginx/sites-available/default
RUN ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000 8080

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
