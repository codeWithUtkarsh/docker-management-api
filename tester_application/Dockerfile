FROM python:3.9-slim

WORKDIR /app

# Copy requirements first to leverage Docker caching
COPY ../requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY .. .

# Default port to expose
EXPOSE 8081

# Set a default PROJECT_ID, but this will be overridden by -e flag
ENV PROJECT_ID=default-project

# Command to run the app
CMD ["python", "tester_app.py"]