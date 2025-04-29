#!/bin/bash
# Script to build and push a Docker image to Docker Hub
# Usage: ./push-to-dockerhub.sh [REPOSITORY_NAME]

# Get Repository name from argument or use default
REPOSITORY_NAME=${1:-"per_user_container_template"}

# Set variables
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_NAME="per_user_container_template"

echo "=== Docker Push to Docker Hub Script ==="
echo "Repository: $REPOSITORY_NAME"
echo "Image Tag: $IMAGE_TAG"
echo "===============================\n"

# Check if Docker is installed and running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running or not installed"
  exit 1
fi

# Step 1: Check if user is logged in to Docker Hub
echo "Step 1: Checking Docker Hub credentials..."
DOCKER_CONFIG_FILE="$HOME/.docker/config.json"

if [ ! -f "$DOCKER_CONFIG_FILE" ]; then
  echo "Docker config file not found at $DOCKER_CONFIG_FILE"
  echo "You need to login to Docker Hub first."
  echo "Run 'docker login' and try again."
  exit 1
fi

# Check if the config file contains auth token
if ! grep -q "auth" "$DOCKER_CONFIG_FILE"; then
  echo "No authentication found in Docker config."
  echo "You need to login to Docker Hub first."
  echo "Run 'docker login' and try again."
  exit 1
fi

# Try to get the username
DOCKERHUB_USERNAME=$(docker info 2>/dev/null | grep Username | awk '{print $2}')

if [ -z "$DOCKERHUB_USERNAME" ]; then
  echo "Could not determine Docker Hub username from Docker config."
  echo "Please specify your Docker Hub username:"
  read -r DOCKERHUB_USERNAME

  if [ -z "$DOCKERHUB_USERNAME" ]; then
    echo "No username provided. Exiting."
    exit 1
  fi
fi

echo "Using Docker Hub username: $DOCKERHUB_USERNAME"
DOCKERHUB_REPOSITORY="${DOCKERHUB_USERNAME}/${REPOSITORY_NAME}"

# Step 2: Create a Dockerfile if it doesn't exist
echo "Step 2: Checking for Dockerfile..."
if [ ! -f "Dockerfile" ]; then
  echo "Dockerfile not found, creating a default one."
  cat > Dockerfile << 'EOF'
FROM python:3.9-slim

WORKDIR /app

# Install Flask
RUN pip install --no-cache-dir flask

# Create a simple app.py file
RUN echo 'from flask import Flask\nimport os\nimport time\n\napp = Flask(__name__)\n\n# Get project ID from environment variable\nproject_id = os.environ.get("PROJECT_ID", "unknown")\n\n@app.route("/")\ndef hello():\n    return f"Hello from container for project {project_id}!"\n\n@app.route("/status")\ndef status():\n    return {\n        "status": "running",\n        "project_id": project_id,\n        "timestamp": time.time()\n    }\n\nif __name__ == "__main__":\n    print(f"Starting container for project {project_id}")\n    app.run(host="0.0.0.0", port=8081)' > /app/app.py

# Default port to expose
EXPOSE 8081

# Set a default PROJECT_ID, but this will be overridden by -e flag
ENV PROJECT_ID=default-project

# Command to run the app
CMD ["python", "app.py"]
EOF
  echo "Dockerfile created."
else
  echo "Using existing Dockerfile."
fi

# Step 3: Build the Docker image
echo "Step 3: Building Docker image..."
docker build -t "${IMAGE_NAME}" .

if [ $? -ne 0 ]; then
  echo "Error: Docker build failed"
  exit 1
fi
echo "Docker image built successfully: ${IMAGE_NAME}"

# Step 4: Tag the Docker image for Docker Hub
echo "Step 4: Tagging Docker image for Docker Hub..."
docker tag "${IMAGE_NAME}" "${DOCKERHUB_REPOSITORY}:${IMAGE_TAG}"
docker tag "${IMAGE_NAME}" "${DOCKERHUB_REPOSITORY}:latest"

if [ $? -ne 0 ]; then
  echo "Error: Failed to tag Docker image"
  exit 1
fi
echo "Image tagged successfully"

# Step 5: Push the Docker image to Docker Hub
echo "Step 5: Pushing image to Docker Hub..."
docker push "${DOCKERHUB_REPOSITORY}:${IMAGE_TAG}"
docker push "${DOCKERHUB_REPOSITORY}:latest"

if [ $? -ne 0 ]; then
  echo "Error: Failed to push image to Docker Hub"
  echo "This might be due to authentication issues or repository permissions."
  echo "Ensure you have created the repository on Docker Hub and have permission to push to it."
  exit 1
fi

echo -e "\nSuccess! Docker image has been pushed to Docker Hub"
echo "Repository: ${DOCKERHUB_REPOSITORY}"
echo "Tags: ${IMAGE_TAG}, latest"
echo "Full image URL: ${DOCKERHUB_REPOSITORY}:${IMAGE_TAG}"
echo "You can pull this image using: docker pull ${DOCKERHUB_REPOSITORY}:${IMAGE_TAG}"
echo "You can run this image using: docker run -d -p 8081:8081 -e PROJECT_ID=your-project-id ${DOCKERHUB_REPOSITORY}:latest"