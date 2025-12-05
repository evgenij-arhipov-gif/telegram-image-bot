FROM python:3.10-slim

WORKDIR /app

# Создаем папку для данных
RUN mkdir -p /data

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]
