FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
COPY forexFactoryScrapper.py .
COPY flask_server.py .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 45869
CMD ["python", "flask_server.py"]
