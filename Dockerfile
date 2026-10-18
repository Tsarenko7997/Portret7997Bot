FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Kyiv
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py portrait.py render.py ./
COPY assets/ ./assets/
CMD ["python", "bot.py"]
