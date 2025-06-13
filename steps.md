
Fantastic! Having the base Airflow environment up and running with the official docker-compose.yaml and accessible via the UI is a crucial first step.
Now, let's proceed to customizing this Airflow environment by creating a Dockerfile to include the specific Python libraries your stock data pipeline will need (yfinance, pandas, SQLAlchemy, psycopg2-binary, boto3, timescaledb Python package).
Recap of Goal: We want Airflow's Python environment (where your DAG tasks run) to have these libraries pre-installed, so you don't have to manually install them in running containers.
Part A (Continued): Customizing Airflow Image with a Dockerfile
Step A8: Create requirements-airflow.txt
This file will list the Python packages needed by your Airflow tasks.
Action: In your airflow_stock_dashboard project root (the same level as docker-compose.yaml), create a file named requirements-airflow.txt.
Content for requirements-airflow.txt:
# requirements-airflow.txt
# For fetching stock data
yfinance>=0.2.0 # Check for a recent stable version

# For data manipulation
pandas>=1.5.0,<3.0.0

# For database interaction (PostgreSQL/TimescaleDB)
SQLAlchemy>=1.4.0,<3.0.0
psycopg2-binary>=2.9.0 # PostgreSQL adapter

# For TimescaleDB specific Python interactions (optional but good to have)
# Also ensures compatibility if SQLAlchemy needs it for certain Timescale features
timescaledb>=0.14.0

# For potential AWS S3 interaction later (good to include if planned)
boto3>=1.26.0,<2.0.0

# For .env file loading if a DAG itself ever needed it (less common for DAGs)
# python-dotenv>=1.0.0

# For Parquet file handling (if you plan to use it as an intermediate format)
pyarrow>=10.0.0,<17.0.0
Use code with caution.
Txt
Note on Versions: I've added example version specifiers (>=min_version, <max_version or just >=min_version). It's good practice for reproducibility. You can adjust these or start without them and let pip pick the latest compatible versions.
We don't add apache-airflow here; it comes from the base image.
Step A9: Create the Dockerfile
This file instructs Docker on how to build your custom image.
Action: In your airflow_stock_dashboard project root, create a file named exactly Dockerfile (no extension).
Content for Dockerfile:
# Dockerfile for Custom Airflow Image with Project Dependencies

# 1. Start FROM the official Airflow base image.
#    !!! CRITICAL: Use the EXACT SAME image name and tag as specified in your
#    !!! original docker-compose.yaml (before you modify it to 'build: .').
#    Example: FROM apache/airflow:2.8.1
FROM apache/airflow:2.8.1 # <<< REPLACE with your exact base image from docker-compose.yaml

# 2. OPTIONAL: Set environment variables if needed for the build process itself
#    (Not usually needed for pip installs of these packages)
# ENV PYTHON_VERSION=3.9 # Example, if you needed to align with a specific Python

# 3. Switch to the airflow user (standard in official Airflow images).
#    This ensures packages are installed correctly for the user that runs Airflow tasks.
USER airflow

# 4. Copy your project-specific Python requirements file into the image.
#    The '/opt/airflow/' directory is the typical WORKDIR in official images.
COPY --chown=airflow:airflow requirements-airflow.txt /opt/airflow/requirements-airflow.txt

# 5. Install the Python dependencies using pip.
#    '--user' installs packages into the user's site-packages directory,
#    which is good practice when running as a non-root user within the container
#    and avoids potential conflicts with system-wide packages.
#    '--no-cache-dir' helps keep the final image size smaller.
RUN pip install --no-cache-dir --user -r /opt/airflow/requirements-airflow.txt

# The base Airflow image already has an ENTRYPOINT and CMD defined to run Airflow services.
# We typically don't need to change these unless doing very advanced customizations.
Use code with caution.
Dockerfile
CRITICAL: Replace FROM apache/airflow:2.8.1 with the exact image and tag that was originally in your docker-compose.yaml for the Airflow services (scheduler, webserver, worker). This ensures compatibility.
Step A10: Modify docker-compose.yaml to Use the Dockerfile
Now, you tell Docker Compose to build your custom image using the Dockerfile instead of pulling the pre-built official image.
Action: Open your docker-compose.yaml file.
Find the service definitions for airflow-scheduler, airflow-webserver, and airflow-worker.
For each of these three services:
Comment out or delete the image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:....} line.
Add a build: section directly underneath where the image: line was:
build:
  context: .  # Use the current directory (where Dockerfile is) as build context
  dockerfile: Dockerfile # Specify the name of our Dockerfile
Use code with caution.
Yaml
Example Snippet (showing one service, apply similarly to others):
# ... (other parts of docker-compose.yaml) ...
services:
  # ... (postgres, redis services usually remain unchanged) ...

  airflow-scheduler:
    # image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.1} # <-- COMMENT OUT or DELETE this line
    build:                                               # <-- ADD these two lines
      context: .
      dockerfile: Dockerfile
    # All other existing configurations for airflow-scheduler (entrypoint, environment,
    # volumes, ports, healthcheck etc.) REMAIN THE SAME.
    # Make sure your volumes (like ./dags:/opt/airflow/dags and ~/.aws:...) are still there.
    # ...

  airflow-webserver:
    # image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.1} # <-- COMMENT OUT or DELETE
    build:                                               # <-- ADD
      context: .
      dockerfile: Dockerfile
    # ... (rest of webserver config remains) ...

  airflow-worker:
    # image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.1} # <-- COMMENT OUT or DELETE
    build:                                               # <-- ADD
      context: .
      dockerfile: Dockerfile
    # ... (rest of worker config remains) ...

  # The airflow-init service might also need to use the built image if it relies on
  # the same environment, or it can often keep using the base image.
  # For consistency, you can change airflow-init too:
  airflow-init:
    # image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.1} # <-- COMMENT OUT or DELETE
    build:                                               # <-- ADD
      context: .
      dockerfile: Dockerfile
    # ... (rest of init config remains) ...

# ... (rest of the file) ...
Use code with caution.
Yaml
Step A11: Build the Custom Images and Restart Airflow
Save all your changes (requirements-airflow.txt, Dockerfile, docker-compose.yaml).
In your terminal (inside airflow_stock_dashboard), stop any running Airflow services:
docker-compose down
Use code with caution.
Bash
Build the new custom images:
docker-compose build
Use code with caution.
Bash
This will execute the Dockerfile. You'll see output from Docker, including the pip install steps. This might take a few minutes the first time.
Initialize the DB (if you ran docker-compose down --volumes or if it's a very fresh setup, otherwise usually not needed again if postgres data volume persists):
docker-compose up airflow-init
Use code with caution.
Bash
Start all Airflow services using your new custom images:
docker-compose up -d
Use code with caution.
Bash
Step A12: Verify Dependencies in Airflow Worker (Optional but Good)
Wait for containers to start (docker ps).
Find the container ID or name for one of your airflow-worker services.
Exec into it:
docker exec -it <your_airflow_worker_container_name_or_id> bash
Use code with caution.
Bash
Once inside the container, check if your packages are installed (as the airflow user):
pip list | grep yfinance
pip list | grep pandas
pip list | grep boto3
pip list | grep psycopg2-binary
pip list | grep timescaledb
Use code with caution.
Bash
You should see them listed. You can also try importing them in a Python shell:
python
>>> import yfinance
>>> import pandas
>>> import boto3
>>> import psycopg2
>>> import timescaledb # This might just be a utility, core access via psycopg2/sqlalchemy
>>> exit()
Use code with caution.
Bash
Type exit to leave the container shell.
Checkpoint for Part A (Custom Airflow Image):
You have requirements-airflow.txt and Dockerfile in your project root.
Your docker-compose.yaml is modified to build: the Airflow services from your Dockerfile.
docker-compose build completes successfully.
docker-compose up -d starts Airflow using your custom images.
You can (optionally) verify that your Python dependencies are available inside the Airflow worker container.