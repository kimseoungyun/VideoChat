FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
WORKDIR /app/backend
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "myproj.asgi:application"]
