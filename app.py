from flask import Flask, request, jsonify
import logging
import os
import tempfile
import shutil
import platform
import sys
import subprocess
import json
from flask_swagger_ui import get_swaggerui_blueprint
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dictionary to store project_id to container_id mappings
project_containers = {}

# Get the base Docker image from environment variable
USER_CONTAINER_TEMPLATE = os.environ.get("USER_CONTAINER_TEMPLATE", "username/USER_CONTAINER_TEMPLATE_NOT_FOUND:latest")
logger.info(f"Using base Docker image: { USER_CONTAINER_TEMPLATE}")

# Set up Swagger configuration
SWAGGER_URL = '/api/docs'  # URL for exposing Swagger UI
API_URL = '/static/swagger.json'  # Our API url (can of course be a local resource)

# Call factory function to create our blueprint
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={  # Swagger UI config overrides
        'app_name': "Docker Container Management API"
    }
)

# Register blueprint at URL
app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

# Create an APISpec
spec = APISpec(
    title="Docker Container Management API",
    version="1.0.0",
    openapi_version="3.0.2",
    plugins=[FlaskPlugin(), MarshmallowPlugin()],
)

# Define and register schemas
spec.components.schema("Error", {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "message": {"type": "string"}
    }
})

spec.components.schema("Container", {
    "type": "object",
    "properties": {
        "container_id": {"type": "string"},
        "status": {"type": "string"},
        "created": {"type": "string", "format": "date-time"}
    }
})

spec.components.schema("ContainerList", {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "containers": {
            "type": "object",
            "additionalProperties": {"$ref": "#/components/schemas/Container"}
        }
    }
})

spec.components.schema("ContainerStatus", {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "project_id": {"type": "string"},
        "container_id": {"type": "string"},
        "container_status": {"type": "string"},
        "created": {"type": "string", "format": "date-time"}
    }
})

spec.components.schema("DockerStatus", {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "message": {"type": "string"},
        "version": {"type": "string"},
        "api_version": {"type": "string"},
        "method": {"type": "string"}
    }
})

spec.components.schema("ContainerCreate", {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "environment": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        },
        "ports": {
            "type": "object",
            "additionalProperties": {"type": "integer"}
        },
        "volumes": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        }
    }
})


# Utility functions to interact with Docker CLI directly instead of using the Python SDK
def run_docker_command(command):
    """Run a Docker CLI command and return the output."""
    try:
        # Run docker command and capture output
        logger.info(f"Running Docker command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return {
            "success": True,
            "output": result.stdout.strip(),
            "error": result.stderr.strip()
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"Docker command failed: {e}")
        logger.error(f"Command output: {e.stdout}")
        logger.error(f"Command error: {e.stderr}")
        return {
            "success": False,
            "output": e.stdout.strip(),
            "error": e.stderr.strip()
        }
    except Exception as e:
        logger.error(f"Error running docker command: {str(e)}")
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }


def check_docker_running():
    """Check if Docker daemon is running."""
    result = run_docker_command(["docker", "info"])
    return result["success"]


def get_docker_version():
    """Get Docker version info."""
    result = run_docker_command(["docker", "version", "--format", "json"])
    if result["success"]:
        try:
            return json.loads(result["output"])
        except json.JSONDecodeError:
            return {"Version": "Unknown", "ApiVersion": "Unknown"}
    return {"Version": "Unknown", "ApiVersion": "Unknown"}


def ensure_base_image_exists():
    """Ensure the base Docker image exists, pulling it if necessary."""
    # Check if image exists locally
    check_image = run_docker_command(["docker", "image", "inspect",  USER_CONTAINER_TEMPLATE])
    if not check_image["success"]:
        # Image doesn't exist locally, try to pull it
        logger.info(f"Base image not found locally. Pulling { USER_CONTAINER_TEMPLATE} from registry...")
        pull_result = run_docker_command(["docker", "pull",  USER_CONTAINER_TEMPLATE])
        if not pull_result["success"]:
            logger.error(f"Failed to pull base image: {pull_result['error']}")
            return False
        logger.info(f"Successfully pulled image { USER_CONTAINER_TEMPLATE}")
    else:
        logger.info(f"Using existing base image { USER_CONTAINER_TEMPLATE}")
    return True


def run_container(project_id, environment=None, ports=None, volumes=None, command=None):
    """Run a Docker container from the base image."""
    if environment is None:
        environment = {}
    if ports is None:
        ports = {}
    if volumes is None:
        volumes = {}

    # Add project ID to environment
    # Make sure it's a string since Docker expects string values for env vars
    environment['PROJECT_ID'] = str(project_id)

    # Ensure the base image is available
    if not ensure_base_image_exists():
        return {
            "success": False,
            "error": f"Failed to ensure base image { USER_CONTAINER_TEMPLATE} exists"
        }

    # Create a container name based on project_id
    container_name = f"project-{project_id}"

    # Start with base command
    run_cmd = ["docker", "run", "-d", "--name", container_name]

    # Add environment variables
    for key, value in environment.items():
        # Make sure both key and value are strings
        run_cmd.extend(["-e", f"{str(key)}={str(value)}"])

    # Add port mappings
    for container_port, host_port in ports.items():
        run_cmd.extend(["-p", f"{host_port}:{container_port}"])

    # Add volume mappings
    for host_path, container_path in volumes.items():
        if isinstance(container_path, dict):  # Handle dict format from Docker SDK
            container_path = container_path.get("bind", "")
        run_cmd.extend(["-v", f"{host_path}:{container_path}"])

    # Add labels
    run_cmd.extend([
        "--label", f"project_id={project_id}",
        "--label", "managed_by=agent_name_tbd"
    ])

    # Add restart policy
    run_cmd.extend(["--restart", "unless-stopped"])

    # Add image tag
    run_cmd.append( USER_CONTAINER_TEMPLATE)

    # Add command if specified
    if command:
        # If command is just a string, treat it as is
        if isinstance(command, str):
            run_cmd.append(command)
        # If command is a list, extend run_cmd with it
        elif isinstance(command, list):
            run_cmd.extend(command)

    # Log the entire docker run command for debugging
    logger.info(f"Running container with command: {' '.join(run_cmd)}")

    # Run the container
    result = run_docker_command(run_cmd)
    if not result["success"]:
        return {
            "success": False,
            "error": f"Failed to run container: {result['error']}"
        }

    # Get container ID from output
    container_id = result["output"].strip()

    # Verify the container is actually running
    status_result = get_container_status(container_id)
    if not status_result["success"] or status_result["status"] != "running":
        logger.warning(f"Container created but not running: {container_id}")
        logger.warning(f"Container status: {status_result}")

    return {
        "success": True,
        "container_id": container_id
    }


def get_container_status(container_id):
    """Get status of a Docker container."""
    # Use docker inspect to get container info
    result = run_docker_command(["docker", "inspect", container_id])
    if not result["success"]:
        return {
            "success": False,
            "error": f"Failed to get container status: {result['error']}"
        }

    try:
        container_info = json.loads(result["output"])
        if not container_info or len(container_info) == 0:
            return {
                "success": False,
                "error": "Container not found"
            }

        container_data = container_info[0]

        # Extract environment variables for debugging
        config = container_data.get("Config", {})
        env_vars = config.get("Env", [])

        # Log environment variables for debugging
        logger.info(f"Container {container_id} environment variables: {env_vars}")

        return {
            "success": True,
            "status": container_data.get("State", {}).get("Status", "unknown"),
            "created": container_data.get("Created", ""),
            "id": container_id,
            "env": env_vars  # Include env vars in the response for debugging
        }
    except json.JSONDecodeError:
        return {
            "success": False,
            "error": "Failed to parse container info"
        }


def stop_and_remove_container(container_id):
    """Stop and remove a Docker container."""
    # Stop the container
    stop_result = run_docker_command(["docker", "stop", container_id])
    if not stop_result["success"]:
        return {
            "success": False,
            "error": f"Failed to stop container: {stop_result['error']}"
        }

    # Remove the container
    rm_result = run_docker_command(["docker", "rm", container_id])
    if not rm_result["success"]:
        return {
            "success": False,
            "error": f"Failed to remove container: {rm_result['error']}"
        }

    return {
        "success": True
    }


def start_container(container_id):
    """Start a stopped Docker container."""
    result = run_docker_command(["docker", "start", container_id])
    return result["success"]


@app.route('/api/status', methods=['GET'])
def get_docker_status():
    """Check if Docker daemon is accessible.
    ---
    get:
        summary: Check Docker daemon status
        description: Checks if the Docker daemon is running and accessible
        responses:
            200:
                description: Docker daemon is accessible
                content:
                    application/json:
                        schema: DockerStatus
            500:
                description: Docker daemon is not accessible
                content:
                    application/json:
                        schema: Error
    """
    if not check_docker_running():
        return jsonify({
            "status": "error",
            "message": "Could not connect to Docker daemon. Please ensure Docker is running."
        }), 500

    version_info = get_docker_version()

    # Also check if base image is available
    base_image_available = ensure_base_image_exists()

    return jsonify({
        "status": "success",
        "message": "Docker daemon is accessible",
        "version": version_info.get("Server", {}).get("Version", "Unknown"),
        "api_version": version_info.get("Server", {}).get("ApiVersion", "Unknown"),
        "method": "Docker CLI",
        "base_image":  USER_CONTAINER_TEMPLATE,
        "base_image_available": base_image_available
    }), 200


@app.route('/api/containers/<project_id>', methods=['POST'])
def create_or_run_container(project_id):
    """Create a new container for a project_id or run an existing one.
    ---
    post:
        summary: Create or run a container
        description: Creates a new container for a project ID or runs an existing one
        parameters:
            - in: path
              name: project_id
              schema:
                type: string
              required: true
              description: The ID of the project
        requestBody:
            content:
                application/json:
                    schema: ContainerCreate
        responses:
            200:
                description: Container is already running or was restarted
                content:
                    application/json:
                        schema: ContainerStatus
            201:
                description: Container was created
                content:
                    application/json:
                        schema: ContainerStatus
            500:
                description: Error occurred
                content:
                    application/json:
                        schema: Error
    """
    try:
        # Check if Docker daemon is running
        if not check_docker_running():
            return jsonify({
                "status": "error",
                "message": "Could not connect to Docker daemon. Please ensure Docker is running."
            }), 500

        # Ensure base image exists
        if not ensure_base_image_exists():
            return jsonify({
                "status": "error",
                "message": f"Base Docker image { USER_CONTAINER_TEMPLATE} not available. Check your registry access."
            }), 500

        # Check if container already exists for this project
        if project_id in project_containers:
            container_id = project_containers[project_id]

            # Check container status
            status_result = get_container_status(container_id)

            if status_result["success"]:
                # If container exists but is not running, start it
                if status_result["status"] != "running":
                    logger.info(f"Starting existing container for project {project_id}")
                    if start_container(container_id):
                        # Get updated status
                        new_status = get_container_status(container_id)

                        return jsonify({
                            "status": "success",
                            "message": f"Container for project {project_id} restarted",
                            "container_id": container_id,
                            "container_status": new_status.get("status", "unknown"),
                            "environment": new_status.get("env", [])
                        }), 200
                    else:
                        # If starting fails, we'll create a new one
                        logger.warning(f"Failed to start container {container_id}. Creating a new one.")
                else:
                    # Container already running
                    logger.info(f"Container for project {project_id} is already running")
                    return jsonify({
                        "status": "success",
                        "message": f"Container for project {project_id} is already running",
                        "container_id": container_id,
                        "container_status": status_result.get("status", "unknown"),
                        "environment": status_result.get("env", [])
                    }), 200
            else:
                # Container doesn't exist or can't be inspected, we'll create a new one
                logger.warning(f"Container {container_id} for project {project_id} not found. Creating a new one.")

        # Get container configuration from request
        data = request.get_json(silent=True) or {}

        # Log request data for debugging
        logger.info(f"Received container creation request for project {project_id}: {data}")

        environment = data.get('environment', {})
        volumes = data.get('volumes', {})
        ports = data.get('ports', {})
        command = data.get('command')

        # Make sure environment is a dictionary
        if not isinstance(environment, dict):
            logger.warning(f"Environment is not a dictionary: {environment}, using empty dict instead")
            environment = {}

        # Ensure PROJECT_ID is set in environment
        environment['PROJECT_ID'] = str(project_id)

        # Log environment variables that will be used
        logger.info(f"Environment variables for container: {environment}")

        # Run the container using the base image
        run_result = run_container(
            project_id=project_id,
            environment=environment,
            ports=ports,
            volumes=volumes,
            command=command
        )

        if not run_result["success"]:
            return jsonify({
                "status": "error",
                "message": run_result["error"]
            }), 500

        # Store the container ID
        container_id = run_result["container_id"]
        project_containers[project_id] = container_id

        # Get container status to verify it's running properly
        status_result = get_container_status(container_id)

        logger.info(f"Created new container {container_id} for project {project_id}")
        return jsonify({
            "status": "success",
            "message": f"Container created for project {project_id}",
            "project_id": project_id,
            "container_id": container_id,
            "base_image":  USER_CONTAINER_TEMPLATE,
            "container_status": status_result.get("status", "unknown") if status_result["success"] else "unknown",
            "environment": status_result.get("env", []) if status_result["success"] else []
        }), 201

    except Exception as e:
        logger.error(f"Error creating container: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500


@app.route('/api/containers/<project_id>', methods=['DELETE'])
def stop_container(project_id):
    """Stop and remove a container for a project_id.
    ---
    delete:
        summary: Stop and remove a container
        description: Stops and removes a container for a project ID
        parameters:
            - in: path
              name: project_id
              schema:
                type: string
              required: true
              description: The ID of the project
        responses:
            200:
                description: Container was stopped and removed
                content:
                    application/json:
                        schema:
                            type: object
                            properties:
                                status:
                                    type: string
                                message:
                                    type: string
            404:
                description: Container not found
                content:
                    application/json:
                        schema: Error
            500:
                description: Error occurred
                content:
                    application/json:
                        schema: Error
    """
    try:
        # Check if Docker daemon is running
        if not check_docker_running():
            return jsonify({
                "status": "error",
                "message": "Could not connect to Docker daemon. Please ensure Docker is running."
            }), 500

        if project_id not in project_containers:
            return jsonify({
                "status": "error",
                "message": f"No container found for project {project_id}"
            }), 404

        container_id = project_containers[project_id]

        # Stop and remove the container
        result = stop_and_remove_container(container_id)

        if result["success"]:
            # Remove from our dictionary
            del project_containers[project_id]

            logger.info(f"Container for project {project_id} stopped and removed")
            return jsonify({
                "status": "success",
                "message": f"Container for project {project_id} stopped and removed"
            }), 200
        else:
            # If there was an error but it's possibly because the container doesn't exist
            if "No such container" in result["error"]:
                del project_containers[project_id]
                return jsonify({
                    "status": "warning",
                    "message": f"Container for project {project_id} not found in Docker, but record cleaned"
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": result["error"]
                }), 500

    except Exception as e:
        logger.error(f"Error stopping container: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500


@app.route('/api/containers', methods=['GET'])
def list_containers():
    """List all containers being managed by this API.
    ---
    get:
        summary: List all containers
        description: Lists all containers being managed by this API
        responses:
            200:
                description: List of containers
                content:
                    application/json:
                        schema: ContainerList
            500:
                description: Error occurred
                content:
                    application/json:
                        schema: Error
    """
    try:
        # Check if Docker daemon is running
        if not check_docker_running():
            return jsonify({
                "status": "error",
                "message": "Could not connect to Docker daemon. Please ensure Docker is running."
            }), 500

        result = {}
        for project_id, container_id in project_containers.items():
            container_status = get_container_status(container_id)

            if container_status["success"]:
                result[project_id] = {
                    "container_id": container_id,
                    "base_image":  USER_CONTAINER_TEMPLATE,
                    "status": container_status["status"],
                    "created": container_status["created"],
                    "environment": container_status.get("env", [])
                }
            else:
                result[project_id] = {
                    "container_id": container_id,
                    "base_image":  USER_CONTAINER_TEMPLATE,
                    "status": "not_found",
                    "error": "Container exists in records but not in Docker"
                }

        return jsonify({
            "status": "success",
            "containers": result
        }), 200

    except Exception as e:
        logger.error(f"Error listing containers: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500


@app.route('/api/containers/<project_id>', methods=['GET'])
def get_container_status_endpoint(project_id):
    """Get status of a specific container.
    ---
    get:
        summary: Get container status
        description: Gets the status of a container for a project ID
        parameters:
            - in: path
              name: project_id
              schema:
                type: string
              required: true
              description: The ID of the project
        responses:
            200:
                description: Container status
                content:
                    application/json:
                        schema: ContainerStatus
            404:
                description: Container not found
                content:
                    application/json:
                        schema: Error
            500:
                description: Error occurred
                content:
                    application/json:
                        schema: Error
    """
    try:
        # Check if Docker daemon is running
        if not check_docker_running():
            return jsonify({
                "status": "error",
                "message": "Could not connect to Docker daemon. Please ensure Docker is running."
            }), 500

        if project_id not in project_containers:
            return jsonify({
                "status": "error",
                "message": f"No container found for project {project_id}"
            }), 404

        container_id = project_containers[project_id]

        container_status = get_container_status(container_id)

        if container_status["success"]:
            return jsonify({
                "status": "success",
                "project_id": project_id,
                "container_id": container_id,
                "base_image":  USER_CONTAINER_TEMPLATE,
                "container_status": container_status["status"],
                "created": container_status["created"],
                "environment": container_status.get("env", [])  # Include environment for debugging
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"Container for project {project_id} exists in records but not in Docker"
            }), 404

    except Exception as e:
        logger.error(f"Error getting container status: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500

# Create a route to serve the OpenAPI spec
@app.route("/static/swagger.json")
def create_swagger_spec():
    """Serve the swagger specification file."""
    for endpoint in app.view_functions:
        if endpoint == 'static' or endpoint.startswith('swagger'):
            continue
        view_func = app.view_functions[endpoint]
        spec.path(view=view_func)
    return jsonify(spec.to_dict())


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5002)
