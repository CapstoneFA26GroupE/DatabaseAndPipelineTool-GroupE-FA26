# Openpilot Data Pipeline

## Authors for Capstone 2026
- Kalyani Valath
- Chi Nguyen
- Daniel Yeaman
- Michael Cote
- Farzana Tasnim

## Background

This repository contains code for the data pipeline for the
[Comma AI](https://comma.ai/) Platform. It is organized as a
containerized mono-repo.

An end-to-end platform to ingest, process, and manage driving data
for computer vision workflows for OpenPilot.

A unified system with job execution, artifact storage, and Computer
Vision Annotation Tool (CVAT) labeling for future machine learning
and human review.

## Fall 2026 Capstone Continuation

This project is a continuation of a previous University of Oklahoma
Computer Science capstone project for the MiLa autonomous vehicle
research platform.

The previous capstone team developed the core infrastructure for
ingesting, processing, annotating, and storing autonomous-driving data.

Our team is continuing development of the existing platform with the
goal of reducing the amount of manual work required to prepare
autonomous-driving data for machine learning training and research.

The overall data preparation pipeline includes:

- Multimodal driving-data collection
- Camera and video processing
- GPS and IMU data handling
- LiDAR data integration
- Data annotation
- Data and artifact storage
- Preparation of datasets for machine-learning experiments

## Project Objectives

The primary goal of the project is to automate more of the AI training
data preparation pipeline used for the MiLa autonomous research vehicle.

Our team will focus on understanding and extending the existing system,
identifying manual or inefficient steps, and improving the reliability
and automation of the data pipeline.

## Technologies and Tools

| Technology | Purpose |
| --- | --- |
| Python | Data processing, backend services, workers, and CVAT integration |
| Docker | Containerization of the services in the data pipeline |
| CVAT | Computer vision data annotation |
| FastAPI | Backend API and pipeline orchestration |
| React + Vite | Frontend interface |
| PostgreSQL | Structured data and job metadata storage |
| MinIO | Storage for large driving-data artifacts |
| OpenPilot / Comma AI | Driving-data source and autonomous-driving platform |

## Ticket 2 Key Feature

One key feature of the current platform is the automated retrieval and
processing of driving data.

The OpenPilot Download Worker monitors the Routes table for routes that
are ready to be downloaded. When an eligible route is detected, the
worker retrieves the corresponding driving data and stores it for later
processing and annotation.

For Ticket 2, our group will document and test a specific behavior
associated with this feature.

## Fall 2026 Goals and Progress Plan

Our current goals are to:

1. Understand the architecture and functionality implemented by the
   previous capstone team.
2. Identify manual or inefficient steps in the existing data preparation
   workflow.
3. Improve automation of the collection, processing, annotation, or
   storage pipeline.
4. Improve reliability through testing and validation.
5. Extend the platform to better support data collected from the MiLa
   autonomous research vehicle.

## Authors

- Noah Pursell
- Trevor Bean
- Vinh Khang Huynh
- Thomas Petersen
- Roman Beames

## Videos

[Demo](https://www.youtube.com/watch?v=M1dots9e0jE)  
[Repo Setup/Installation](https://www.youtube.com/watch?v=LfWelxg0oPc)  
[Code Walkthrough + Explanations](https://www.youtube.com/watch?v=pgbatZj3tOk)  
[Creating New CVAT Job Definitions](https://youtu.be/M9UgbizjnKg)     

## Dependencies (Do These First)

### Docker

1. Install [docker](https://www.docker.com/get-started/) for your operating system.

### Comma AI JWT

1. Get a new jwt on [comma.ai's website](https://jwt.comma.ai)
1. Save this for future steps

### ENV File

1. Create a `.env` file at the root directory, copied from the `.example_env` file
1. Fill out the marked spots

### Minio License

1. Go to the [minio download page](https://www.min.io/download)
1. Download a **FREE** license
1. Create a folder in the root director called `minio`
1. Move the license into the folder. It should be called `minio/minio.license`

## Running the Code

1. Start the databases with 
```bash 
docker compose up --build -d postgres minio
```
2. Create a database migration with 
```bash 
docker compose run --build --rm alembic_worker alembic -c /app/alembic_worker/alembic.ini revision --autogenerate -m "first migration"
```
3. Push the migration with 
```bash
docker compose up --build alembic_worker minio_initializer
```
4. Start the backend and open pilot workers with 
```bash
docker compose up --build -d backend open_pilot_download_worker open_pilot_upload_worker dataset_export_worker
```
5. Start the cvat container using
```bash
chmod +x ./scripts/setup_cvat.sh
./scripts/setup_cvat.sh
```
6. Start the cvat workers with 
```bash
docker compose up --build -d cvat_worker cvat_import_export_worker
```
7. Start the frontend with
```bash
docker compose up --build -d frontend
# for development: use docker's watch to get live updates
docker compose watch frontend
```

## Ports

| Service       | Link                         | Port |
| ------------- | ---------------------------- | ---- |
| Frontend      | <http://localhost:5173>      | 5173 |
| Backend       | <http://localhost:8000/docs> | 8000 |
| CVAT          | <http://localhost:8080>      | 8080 |
| Minio Console | <http://localhost:9001>      | 9001 |
| Minio API     | <http://localhost:9000>      | 9000 |
| Postgres      | localhost:5433               | 5433 |

## Contributing

### Code Organization

#### Frontend

The frontend code is stored in the `/frontend/` folder. This is a React Vite build for the pipeline's UI. Most of the code is in the `/src/` folder where everything is organized into `/pages/` or `/components/`. All of the api processes are located in the `/api/` folder, and utilities in `/utils/`.

#### Backend

The backend code is stored in the `/backend/` folder. This is the primary orchestrator for the pipeline. It acts as an API that is interacted with through the front-end that allows for controlling route downloads, processing, and retrieval. It is a FastAPI deployment. When editing the backend, most code should actually be written in the `/shared/` folder. Keep `/backend/main.py` as minimal as possible.

#### Open Pilot Download Worker

The Open Pilot Download Worker, located in `/open_pilot_download_worker/` is a worker that can download videos and logs from OpenPilot. It does this by watching the `Routes` table in the database for any routes that are ready to be downloaded. When it sees a new route ready to download, it begins to download the route and save it in a folder under `/data/`.

#### Postgres

SQL storage for the project.

#### Alembic Worker

Alembic Worker, located in `/alembic_worker/` is the tool we use for Postgres SQL migrations. It looks at the models defined in the `/shared/db/` code, and updates the SQL database to reflect the schema. Look at `/alembic_worker/readme.md` for information on how to use it.

#### Minio

S3 Bucket storage for the project.

### Shared

This is where the majority of code lives, in the `/shared/` directory. This code is copied into the other containers, such as the backend or the worker containers.

### Data

Do not put any code here. The folders `/data/` and `/cvat_share/` is used as a shared volume between workers.

### Ruff

Before commiting any code, run the `ruff` linter and fix any issues found.

`ruff check .`

### Pyright

Before commiting any code, run the `pyright` static type checker and fix any issues found.

`pyright`

## Testing

Testing code is inside the `./tests/` folder. See [Tests Readme](./tests/README.md) for more information.

## CVAT Job Extension Notes

CVAT Jobs are somewhat complicated, so this section aims to explain them as simple as possible.

TLDR: CVAT jobs are defined by two things: a python class and a set of arguments for that class. If you want to make a new job, you might have to create a new python class, or you might be able to use an exhisting python class, but pass in different arguments.

### CVAT Annotation Function

Under `./shared/cvat_annotation_functions/` there is a file called `i_cvat_detection.py` which defines the `ICVATDetection` interface. This interface is a template for how custom CVAT functions should be defined. If you need a new type of CVAT job, you can create a new class (called a _plugin_) that inherites from the `ICVATDetection` interface. You will need to register this with the `@register_cvat_detection_plugin` function. Look at `./shared/cvat_annotation_functions/cvat_detr_detection.py` for an example.

### Passing Arguments to a CVAT Annotation Function

You do not need a new plugin to make a new job definition if an existing implementation already does what you want. Example `POST /job-definitions` payload reusing the built-in `detr_detection` plugin with a different config:

```json
{
  "type": "object_detection",
  "implementation_key": "detr_detection",
  "name": "RT-DETR small threshold test",
  "description": "Reuse existing detector with different config",
  "config": {
    "model_name": "PekingU/rtdetr_v2_r50vd"
  }
}
```

Only add a new plugin when you need a new implementation key or different detection code path.

## TODO

Check out the [course Kanban board](https://cscapstone.cs.ou.edu/pages/account/) for TODOs.

## Important link

- [Comma Connect](https://connect.comma.ai/)

## Comma Routes

- 16 Segments: db478799b6f9f210/00000098--ce43889a70
- 4 Segments: db478799b6f9f210/0000000e--9ecd39f6bc
- 2 Segments: db478799b6f9f210|00000081--23c1159034
