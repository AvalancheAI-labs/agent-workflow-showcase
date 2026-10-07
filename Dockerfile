FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt constraints.txt .
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY . .
ENV BRAIN_ROOT=/app/data
EXPOSE 8095
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8095"]
