FROM python:3.14-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
CMD ["python3", "main.py"]
