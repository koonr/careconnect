# Use lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from buffering logs
ENV PYTHONUNBUFFERED=1

# Install system deps (optional but useful)
RUN apt-get update && apt-get install -y gcc

# Copy files
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port
EXPOSE 8080

# Run app using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
