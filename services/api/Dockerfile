FROM python:3.10-slim
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" psycopg2-binary python-multipart \
    sqlalchemy "python-jose[cryptography]" passlib[bcrypt] \
    google-auth requests
COPY . /app
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
