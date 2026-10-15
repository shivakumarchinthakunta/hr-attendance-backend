# HR Attendance & Analytics API

A backend application built with **FastAPI and MongoDB** to manage employee records, track daily attendance, and generate workforce analytics using MongoDB aggregation pipelines.

The project demonstrates REST API development, data validation, database operations, attendance calculations, pagination, and analytical reporting.

[Repository](https://github.com/shivakumarchinthakunta/hr-attendance-backend)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [Architecture](#architecture)
- [API Endpoints](#api-endpoints)
- [Getting Started](#getting-started)
- [Example API Requests](#example-api-requests)
- [Analytics](#analytics)
- [Error Handling](#error-handling)
- [Project Structure](#project-structure)
- [Future Enhancements](#future-enhancements)

## Overview

The HR Attendance & Analytics API provides a foundation for employee management and attendance tracking.

It supports employee registration, daily punch-in and punch-out operations, attendance history, and analytical endpoints for understanding workforce attendance patterns.

The analytics layer uses MongoDB aggregation pipelines to process attendance records inside the database rather than loading the entire dataset into application memory.

## Features

### Employee Management
- Create employee records.
- Retrieve employees with pagination.
- Filter employees by department.
- Store employee details, including department and shift timings.

### Attendance Management
- Record employee punch-in timestamps.
- Record employee punch-out timestamps.
- Calculate work hours.
- Calculate late-arrival minutes.
- Track overtime and half-day status.
- Retrieve attendance records with employee and pagination filters.
- Prevent duplicate attendance records for the same employee and date.
- Prevent repeated punch-out operations.

### Workforce Analytics
- Employee monthly attendance analytics.
- Department-level attendance summaries.
- Monthly late-comer leaderboard with tie handling.
- Department daily attendance trends, including weekends and missing days.
- Seven-day moving average for attendance trends.
- MongoDB query execution statistics through an administrative explain endpoint.

### API Design
- RESTful endpoints with JSON request and response bodies.
- Request validation using Pydantic models.
- Interactive API documentation using Swagger UI.
- Structured HTTP error responses.
- Pagination for list endpoints.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| FastAPI | REST API framework |
| MongoDB | Document database |
| PyMongo | MongoDB database operations |
| MongoDB Aggregation Pipeline | Analytics and reporting |
| Pydantic | Request validation and data models |
| Uvicorn | ASGI server |
| Swagger UI / OpenAPI | API documentation and testing |
| Git and GitHub | Version control |

## Architecture

```text
Client / Swagger UI
        |
        v
    FastAPI
        |
        v
 Validation & Business Logic
        |
        v
      PyMongo
        |
        v
      MongoDB
        |
        +-- Employees
        |
        +-- Attendance Logs
        |
        +-- Aggregation Pipelines
                 |
                 v
          Analytics Results
```

MongoDB stores employee and attendance documents. FastAPI validates requests, executes business logic, and returns JSON responses. Analytics endpoints use aggregation pipelines to calculate reporting metrics.

## API Endpoints

Base URL for local development: `http://localhost:8000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Check API health |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees with pagination and optional department filter |
| POST | `/attendance/punch-in` | Record employee punch-in |
| POST | `/attendance/punch-out` | Record employee punch-out |
| GET | `/attendance` | List attendance records |
| GET | `/analytics/employees/{emp_code}/monthly` | Employee monthly analytics |
| GET | `/analytics/departments/summary` | Department attendance summary |
| GET | `/analytics/leaderboard/late` | Monthly late-comer leaderboard |
| GET | `/analytics/departments/{department}/trend` | Daily department attendance trend |
| GET | `/admin/explain/{endpoint}` | Inspect database query execution statistics |

Open `http://localhost:8000/docs` after starting the server to explore the request schemas, parameters, and responses interactively.

## Getting Started

### Prerequisites

Install or prepare:

- Python 3.11 or a compatible Python version.
- MongoDB running locally or an accessible MongoDB instance.
- Git.
- A terminal or command prompt.

### 1. Clone the repository

```bash
git clone https://github.com/shivakumarchinthakunta/hr-attendance-backend.git
cd hr-attendance-backend
```

### 2. Create a virtual environment

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure MongoDB

Start MongoDB and configure the connection string and database settings expected by the application.

Use environment variables for database credentials and other secrets if supported by your configuration. Never commit real credentials to GitHub.

**Important:** Use the exact configuration variable names expected by `app/main.py`. The names may differ between implementations.

### 5. Start the API

```bash
python -m uvicorn app.main:app --reload --port 8000
```

The server should be accessible at:

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

### 6. Verify the health endpoint

```bash
curl http://localhost:8000/health
```

A successful response should return HTTP `200 OK` with the health status defined by the application.

## Example API Requests

The examples below use the API contract exercised during development.

### Create an employee

**POST** `/employees`

```json
{
  "emp_code": "EMP0005",
  "name": "Rahul Kumar",
  "email": "rahul.kumar@example.com",
  "department": "Engineering",
  "shift_start": "09:30",
  "shift_end": "18:30",
  "joined_on": "2026-10-15"
}
```

A successful creation should return HTTP `201 Created`.

Use a unique employee code and email consistent with your application's validation rules.

### List employees

**GET** `/employees?page=1&page_size=20`

Filter by department:

```http
GET /employees?department=Engineering&page=1&page_size=20
```

The response contains employee items and pagination metadata.

### Punch in

**POST** `/attendance/punch-in`

```json
{
  "emp_code": "EMP0005",
  "punched_at": 1792035000000,
  "status": "PRESENT"
}
```

`punched_at` is an example Unix timestamp in milliseconds. Use the appropriate timestamp for the actual attendance event.

### Punch out

**POST** `/attendance/punch-out`

```json
{
  "emp_code": "EMP0005",
  "punched_at": 1792067400000
}
```

The application records the punch-out and calculates work hours according to its implemented rules.

### List attendance

```http
GET /attendance?emp_code=EMP0005&page=1&page_size=20
```

Use the optional employee filter and pagination parameters supported by the API.

## Analytics

### 1. Employee Monthly Analytics

```http
GET /analytics/employees/EMP0005/monthly
```

Provides employee-level monthly attendance analytics according to the implemented response contract.

### 2. Department Summary

```http
GET /analytics/departments/summary
```

Provides aggregated attendance information grouped by department.

### 3. Late-Comer Leaderboard

```http
GET /analytics/leaderboard/late
```

Ranks employees by late-arrival activity for the relevant reporting period, with tie handling as implemented by the application.

### 4. Department Attendance Trend

```http
GET /analytics/departments/Engineering/trend
```

Provides a daily trend for a department. The intended analytics include weekends, missing dates, headcount, and a seven-day moving average.

### 5. Query Execution Statistics

```http
GET /admin/explain/{endpoint}
```

Inspects database execution statistics for a supported endpoint's main query or aggregation.

This endpoint should be restricted to authorized administrators before deployment in a production environment.

### Analytics implementation principles

- Use MongoDB aggregation pipelines for analytical calculations.
- Perform filtering, grouping, and calculations in the database where practical.
- Handle date ranges, missing days, and ties consistently.
- Apply pagination and appropriate database indexes.
- Validate query performance using execution statistics.

**Performance note:** The project requirements include handling attendance analytics at a scale of 100,000 records. Actual performance should be validated using representative data, appropriate indexes, and measured query execution times.

## Error Handling

The API uses HTTP status codes to communicate outcomes.

| Status | Meaning |
|---|---|
| 200 | Request completed successfully |
| 201 | Resource created successfully |
| 400 | Invalid business operation, where implemented |
| 404 | Employee or resource not found |
| 409 | Attendance conflict, such as duplicate punch-in or repeated punch-out |
| 422 | Request validation error |
| 500 / 503 | Internal or database operation failure, depending on the implemented handler |

Example conflict response:

```json
{
  "detail": "attendance record already exists for employee/date"
}
```

Actual response messages and status codes depend on the endpoint's implementation.

## Project Structure

```text
hr-attendance-backend/
├── app/
│   └── main.py
├── .gitignore
├── README.md
├── DECISIONS.md
├── REVIEW.md
└── requirements.txt
```

The current repository keeps the application entry point in `app/main.py`. As the project grows, models, database configuration, business logic, analytics pipelines, and tests can be separated into dedicated modules.

## Future Enhancements

- Authentication and role-based access control.
- Automated unit and integration tests.
- Docker-based development and deployment.
- CI/CD pipeline for automated testing.
- Structured application logging and monitoring.
- Database index and aggregation performance benchmarks.
- API deployment with secure environment configuration.
- Automated API documentation and example datasets.

## Running Tests

Automated tests should be added and executed before production deployment.

If a test suite is available, run it using the project's configured test command, for example:

```bash
pytest
```

This command requires `pytest` and an existing test suite to be configured.

## Security

- Do not commit `.env` files, database credentials, API keys, or access tokens.
- Restrict administrative endpoints.
- Validate all incoming requests.
- Configure appropriate network access and database permissions.
- Use HTTPS and appropriate authentication before exposing the API publicly.

## License

No license has been configured for this repository yet. Add a license if you intend to define permissions for reuse and distribution.

---

**Built with Python, FastAPI, and MongoDB.**
