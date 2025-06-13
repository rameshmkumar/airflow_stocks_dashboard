#Installing the image
FROM apache/airflow:3.0.2 

#Let's switch to airflow user
USER airflow

#Copy your project-specific Python requirements file into the image.
COPY --chown=airflow:airflow requirements-airflow.txt /opt/airflow/requirements-airflow.txt

#Installing python dependencies
RUN pip install --no-cache-dir -r /opt/airflow/requirements-airflow.txt

