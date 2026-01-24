# Dockerfile alternativo dentro de la carpeta server
FROM python:3.11-slim

WORKDIR /app

# Copiar archivos
COPY . .

# Instalar dependencias
RUN pip install --no-cache-dir Flask==3.0.0 flask-cors==4.0.0

# Exponer puerto
EXPOSE 5000

# Variables de entorno
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=5000

# Ejecutar servidor
CMD ["python", "app.py"]
