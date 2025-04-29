from flask import Flask
import os
import time

app = Flask(__name__)

# Get project ID from environment variable
project_id = os.environ.get('PROJECT_ID', 'unknown')

@app.route('/')
def hello():
    return f"Hello from container for project {project_id}!"

@app.route('/status')
def status():
    return {
        "status": "running",
        "project_id": project_id,
        "timestamp": time.time()
    }

if __name__ == '__main__':
    print(f"Starting container for project {project_id}")
    app.run(host='0.0.0.0', port=8081)