import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional

from bson import json_util
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
UTC = timezone.utc
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=2500)
db = client[os.getenv("MONGO_DB", "attendance_db")]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMP_CODE_RE = re.compile(r"^EMP\d{4,6}$")
VALID_STATUSES = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}


def validate_hhmm(value: str) -> str:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise ValueError("time must be in HH:MM 24-hour format")
    return value


def validate_date_string(value: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError("date must be in YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be a valid calendar date") from exc
    return value


def epoch_ms_to_ist(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("timestamp must be integer epoch milliseconds")
    if value < 100_000_000_000 or value > 4_102_444_800_000:
        raise ValueError("timestamp must be epoch milliseconds in supported range")
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(IST).replace(microsecond=0)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("timestamp is outside supported range") from exc


def now_ist() -> datetime:
    return datetime.now(IST).replace(microsecond=0)


def as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(IST).replace(microsecond=0)


def to_epoch_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def round_half_up(value: float, places: int = 2) -> float:
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, validate_hhmm(shift_start).split(":"))
    local = as_ist(punch_in)
    scheduled = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if scheduled - local > timedelta(hours=12):
        scheduled -= timedelta(days=1)
    elapsed = local - scheduled
    return 0 if elapsed <= timedelta(minutes=10) else max(0, int(elapsed.total_seconds() // 60))


def attendance_date_for(punch_in_ist: datetime, shift_start: str, shift_end: str) -> str:
    start, end = validate_hhmm(shift_start), validate_hhmm(shift_end)
    if end <= start and punch_in_ist.strftime("%H:%M") < end:
        return (punch_in_ist.date() - timedelta(days=1)).isoformat()
    return punch_in_ist.date().isoformat()


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (as_ist(punch_out) - as_ist(punch_in)).total_seconds()
    if seconds < 0:
        raise ValueError("punch_out must be after punch_in")
    return round_half_up(seconds / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, attendance_day: str, shift_start: str) -> int:
    day = date.fromisoformat(validate_date_string(attendance_day))
    sh, sm = map(int, validate_hhmm(shift_start).split(":"))
    eh, em = map(int, validate_hhmm(shift_end).split(":"))
    end = datetime.combine(day, time(eh, em), tzinfo=IST)
    if (eh, em) <= (sh, sm):
        end += timedelta(days=1)
    minutes = int((as_ist(punch_out) - end).total_seconds() // 60)
    return minutes if minutes >= 30 else 0


def serialize_doc(doc: dict, datetime_fields: tuple[str, ...] = ()) -> dict:
    result = dict(doc)
    result.pop("_id", None)
    result.pop("id", None)
    for field in datetime_fields:
        if isinstance(result.get(field), datetime):
            result[field] = to_epoch_ms(result[field])
    result.setdefault("history", [])
    result.setdefault("late_minutes", 0)
    result.setdefault("overtime_minutes", 0)
    result.setdefault("half_day", False)
    for entry in result.get("history", []):
        if isinstance(entry.get("at"), datetime):
            entry["at"] = to_epoch_ms(entry["at"])
        for change in entry.get("changes", {}).values():
            for side in ("from", "to"):
                if isinstance(change.get(side), datetime):
                    change[side] = to_epoch_ms(change[side])
    return result


def ensure_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_code")
    db.employees.create_index([("joined_on", ASCENDING), ("department", ASCENDING)], name="ix_employee_joined_department")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="ix_employee_department_joined")
    db.attendance_logs.create_index([("date", ASCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_emp_code")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_employee")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", DESCENDING)], name="ix_attendance_employee_date_desc")
    db.attendance_logs.create_index([("status", ASCENDING), ("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_status_date_employee")
    db.attendance_logs.create_index([("date", ASCENDING), ("late_minutes", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_late_employee")


@app.on_event("startup")
def startup():
    try:
        client.admin.command("ping")
        ensure_indexes()
    except PyMongoError as exc:
        raise RuntimeError("MongoDB connection/index initialization failed") from exc


# Define all request models BEFORE endpoint functions use them.
class EmployeeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    emp_code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=120)
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code")
    @classmethod
    def valid_code(cls, v):
        if not EMP_CODE_RE.fullmatch(v):
            raise ValueError("emp_code must be EMP followed by 4 to 6 digits")
        return v

    @field_validator("name", "department")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("field must not be blank")
        return v

    @field_validator("email")
    @classmethod
    def valid_email(cls, v):
        if not EMAIL_RE.fullmatch(v):
            raise ValueError("email must be a valid email address")
        return v

    @field_validator("shift_start", "shift_end")
    @classmethod
    def valid_shift(cls, v):
        return validate_hhmm(v)

    @field_validator("joined_on")
    @classmethod
    def valid_joined(cls, v):
        return validate_date_string(v)

    @field_validator("shift_end")
    @classmethod
    def shift_times_differ(cls, v, info):
        if info.data.get("shift_start") == v:
            raise ValueError("shift_start and shift_end must differ")
        return v


class PunchInIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    emp_code: str = Field(min_length=1, max_length=32)
    punched_at: Optional[int] = Field(default=None, ge=0)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

    @field_validator("emp_code")
    @classmethod
    def valid_code(cls, v):
        if not v.strip():
            raise ValueError("emp_code must not be blank")
        return v

    @field_validator("punched_at", mode="before")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None:
            epoch_ms_to_ist(v)
        return v


class PunchOutIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    emp_code: str = Field(min_length=1, max_length=32)
    punched_at: Optional[int] = Field(default=None, ge=0)

    @field_validator("emp_code")
    @classmethod
    def valid_code(cls, v):
        if not v.strip():
            raise ValueError("emp_code must not be blank")
        return v

    @field_validator("punched_at", mode="before")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None:
            epoch_ms_to_ist(v)
        return v


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB unavailable") from exc


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="emp_code already exists") from exc
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Database operation failed") from exc
    return serialize_doc(doc, ("created_at",))


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {"department": department} if department else {}
    total = db.employees.count_documents(query)
    docs = db.employees.find(query, {"_id": 0}).sort("emp_code", ASCENDING).skip((page - 1) * page_size).limit(page_size)
    return {"items": [serialize_doc(d, ("created_at",)) for d in docs], "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")
    ts_ist = epoch_ms_to_ist(body.punched_at) if body.punched_at is not None else now_ist()
    day = attendance_date_for(ts_ist, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": day,
        "status": body.status,
        "punch_in": ts_ist.astimezone(UTC).replace(tzinfo=None),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts_ist, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="attendance record already exists for employee/date") from exc
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Database operation failed") from exc
    return serialize_doc(doc, ("punch_in", "punch_out"))


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")
    out_ist = epoch_ms_to_ist(body.punched_at) if body.punched_at is not None else now_ist()
    out_utc = out_ist.astimezone(UTC).replace(tzinfo=None)

    attendance = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$ne": None, "$lte": out_utc}},
        sort=[("punch_in", DESCENDING)],
    )
    if attendance is None:
        raise HTTPException(status_code=404, detail="no punch-in found")
    if attendance.get("punch_out") is not None:
        raise HTTPException(status_code=409, detail="attendance already punched out")

    punch_in_utc = attendance["punch_in"]
    if punch_in_utc.tzinfo is not None:
        punch_in_utc = punch_in_utc.astimezone(UTC).replace(tzinfo=None)
    elapsed = (out_utc - punch_in_utc).total_seconds()
    if elapsed <= 0:
        raise HTTPException(status_code=422, detail="punched_at must be after punch_in")
    if elapsed > 86400:
        raise HTTPException(status_code=422, detail="punch_out must be within 24 hours of punch_in")

    hours = compute_work_hours(punch_in_utc, out_utc)
    overtime = compute_overtime(out_ist, emp["shift_end"], attendance["date"], emp["shift_start"])
    half_day = hours < 4.50

    try:
        result = db.attendance_logs.update_one(
            {"_id": attendance["_id"], "punch_out": None},
            {"$set": {"punch_out": out_utc, "work_hours": hours, "overtime_minutes": overtime, "half_day": half_day}},
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Database operation failed") from exc
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="attendance already punched out")
    updated = db.attendance_logs.find_one({"_id": attendance["_id"]})
    return serialize_doc(updated, ("punch_in", "punch_out"))


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}
    if emp_code:
        query["emp_code"] = emp_code
    if date_from or date_to:
        date_filter = {}
        if date_from:
            validate_date_string(date_from)
            date_filter["$gte"] = date_from
        if date_to:
            validate_date_string(date_to)
            date_filter["$lte"] = date_to
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must be <= date_to")
        query["date"] = date_filter
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail="invalid attendance status")
        query["status"] = status
    total = db.attendance_logs.count_documents(query)
    docs = db.attendance_logs.find(query).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {
        "items": [serialize_doc(d, ("punch_in", "punch_out", "created_at")) for d in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }




# ---------------------------
# Analytics endpoints required by openapi.yaml
# Every calculation is performed in MongoDB aggregation pipelines.
# ---------------------------

PRESENT_STATUSES = ["PRESENT", "WFH", "ON_DUTY"]
ANALYTICS_ENDPOINTS = [
    "attendance_list",
    "employee_monthly",
    "department_summary",
    "late_leaderboard",
    "department_trend",
]


def validate_month(month: str) -> tuple[str, str, str]:
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=422, detail="month must be in YYYY-MM format")
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="month must be a valid calendar month") from exc
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)
    return month, first.isoformat(), next_month.isoformat()


def validate_analytics_date(value: str, field_name: str) -> str:
    try:
        return validate_date_string(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name}: {exc}") from exc


def half_up_expr(expression, places: int):
    """Mongo expression for non-negative half-up rounding (rather than $round's ties-to-even)."""
    factor = 10 ** places
    return {"$divide": [{"$floor": {"$add": [{"$multiply": [expression, factor]}, 0.5]}}, factor]}


def weekday_expr(date_expression):
    # $dayOfWeek: Sunday=1, Monday=2, ..., Saturday=7.
    return {"$in": [{"$dayOfWeek": date_expression}, [2, 3, 4, 5, 6]]}


def monthly_log_lookup(emp_code_expression, first_day: str, next_month: str, as_name="month_logs"):
    return {
        "$lookup": {
            "from": "attendance_logs",
            "let": {"employee_code": emp_code_expression},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$employee_code"]},
                    {"$gte": ["$date", first_day]},
                    {"$lt": ["$date", next_month]},
                ]}}},
            ],
            "as": as_name,
        }
    }


def employee_monthly_pipeline(emp_code: str, month: str):
    month, first_day, next_month = validate_month(month)
    month_end = (date.fromisoformat(next_month) - timedelta(days=1)).isoformat()
    return [
        {"$match": {"emp_code": emp_code}},
        monthly_log_lookup("$emp_code", first_day, next_month),
        {"$set": {
            "_month_start": {"$cond": [{"$gt": ["$joined_on", first_day]}, "$joined_on", first_day]},
            "_month_end": month_end,
        }},
        {"$set": {
            "_work_dates": {"$cond": [
                {"$gt": ["$_month_start", "$_month_end"]},
                [],
                {"$map": {
                    "input": {"$range": [0, {"$add": [{"$dateDiff": {
                        "startDate": {"$dateFromString": {"dateString": "$_month_start"}},
                        "endDate": {"$dateFromString": {"dateString": "$_month_end"}},
                        "unit": "day",
                    }}, 1]}]},
                    "as": "offset",
                    "in": {"$dateAdd": {
                        "startDate": {"$dateFromString": {"dateString": "$_month_start"}},
                        "unit": "day",
                        "amount": "$$offset",
                    }},
                }},
            ]},
            "_log_metrics": {"$map": {
                "input": "$month_logs", "as": "log", "in": {
                    "present_weekday": {"$cond": [
                        {"$and": [
                            {"$in": ["$$log.status", PRESENT_STATUSES]},
                            weekday_expr({"$dateFromString": {"dateString": "$$log.date"}}),
                        ]},
                        {"$cond": [{"$eq": ["$$log.half_day", True]}, 0.5, 1]},
                        0,
                    ]},
                    "leave": {"$cond": [{"$eq": ["$$log.status", "LEAVE"]}, 1, 0]},
                    "late": {"$cond": [{"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]}, 1, 0]},
                    "late_minutes": {"$ifNull": ["$$log.late_minutes", 0]},
                    "overtime_minutes": {"$ifNull": ["$$log.overtime_minutes", 0]},
                }
            }},
        }},
        {"$set": {
            "working_days": {"$size": {"$filter": {
                "input": "$_work_dates", "as": "work_date", "cond": weekday_expr("$$work_date")
            }}},
            "present_days": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.present_weekday"}}},
            "leave_days": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.leave"}}},
            "late_count": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.late"}}},
            "total_late_minutes": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.late_minutes"}}},
            "total_overtime_minutes": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.overtime_minutes"}}},
        }},
        {"$project": {
            "_id": 0,
            "emp_code": 1,
            "month": {"$literal": month},
            "working_days": 1,
            "present_days": 1,
            "leave_days": 1,
            "late_count": 1,
            "total_late_minutes": 1,
            "total_overtime_minutes": 1,
            "attendance_pct": {"$cond": [
                {"$gt": ["$working_days", 0]},
                half_up_expr({"$multiply": [{"$divide": ["$present_days", "$working_days"]}, 100]}, 2),
                None,
            ]},
        }},
    ]


def department_summary_pipeline(month: str, department: Optional[str] = None):
    month, first_day, next_month = validate_month(month)
    month_end = (date.fromisoformat(next_month) - timedelta(days=1)).isoformat()
    employee_match = {"joined_on": {"$lte": month_end}}
    if department is not None:
        employee_match["department"] = department
    return [
        {"$match": employee_match},
        monthly_log_lookup("$emp_code", first_day, next_month),
        {"$set": {
            "_month_start": {"$cond": [{"$gt": ["$joined_on", first_day]}, "$joined_on", first_day]},
            "_month_end": month_end,
            "_log_metrics": {"$map": {
                "input": "$month_logs", "as": "log", "in": {
                    "present_weekday": {"$cond": [
                        {"$and": [
                            {"$in": ["$$log.status", PRESENT_STATUSES]},
                            weekday_expr({"$dateFromString": {"dateString": "$$log.date"}}),
                        ]},
                        {"$cond": [{"$eq": ["$$log.half_day", True]}, 0.5, 1]},
                        0,
                    ]},
                    "present_with_hours": {"$cond": [
                        {"$and": [
                            {"$in": ["$$log.status", PRESENT_STATUSES]},
                            {"$ne": [{"$ifNull": ["$$log.work_hours", None]}, None]},
                        ]},
                        1, 0,
                    ]},
                    "hours": {"$cond": [
                        {"$and": [
                            {"$in": ["$$log.status", PRESENT_STATUSES]},
                            {"$ne": [{"$ifNull": ["$$log.work_hours", None]}, None]},
                        ]},
                        "$$log.work_hours", 0,
                    ]},
                    "leave": {"$cond": [{"$eq": ["$$log.status", "LEAVE"]}, 1, 0]},
                    "on_duty": {"$cond": [{"$eq": ["$$log.status", "ON_DUTY"]}, 1, 0]},
                    "late": {"$cond": [{"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]}, 1, 0]},
                    "late_minutes": {"$ifNull": ["$$log.late_minutes", 0]},
                }
            }},
        }},
        {"$set": {
            "_work_dates": {"$cond": [
                {"$gt": ["$_month_start", "$_month_end"]},
                [],
                {"$map": {
                    "input": {"$range": [0, {"$add": [{"$dateDiff": {
                        "startDate": {"$dateFromString": {"dateString": "$_month_start"}},
                        "endDate": {"$dateFromString": {"dateString": "$_month_end"}},
                        "unit": "day",
                    }}, 1]}]},
                    "as": "offset",
                    "in": {"$dateAdd": {
                        "startDate": {"$dateFromString": {"dateString": "$_month_start"}},
                        "unit": "day", "amount": "$$offset"
                    }},
                }},
            ]},
            "_present_days": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.present_weekday"}}},
            "_hours_sum": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.hours"}}},
            "_hours_count": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.present_with_hours"}}},
            "_leave_count": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.leave"}}},
            "_on_duty_count": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.on_duty"}}},
            "_late_count": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.late"}}},
            "_total_late_minutes": {"$sum": {"$map": {"input": "$_log_metrics", "as": "m", "in": "$$m.late_minutes"}}},
        }},
        {"$set": {"_working_days": {"$size": {"$filter": {
            "input": "$_work_dates", "as": "work_date", "cond": weekday_expr("$$work_date")
        }}}}},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1},
            "present_days": {"$sum": "$_present_days"},
            "hours_sum": {"$sum": "$_hours_sum"},
            "hours_count": {"$sum": "$_hours_count"},
            "late_count": {"$sum": "$_late_count"},
            "total_late_minutes": {"$sum": "$_total_late_minutes"},
            "leave_count": {"$sum": "$_leave_count"},
            "on_duty_count": {"$sum": "$_on_duty_count"},
        }},
        {"$project": {
            "_id": 0, "department": "$_id", "headcount": 1,
            "present_days": 1,
            "avg_work_hours": {"$cond": [
                {"$gt": ["$hours_count", 0]},
                half_up_expr({"$divide": ["$hours_sum", "$hours_count"]}, 2),
                None,
            ]},
            "late_count": 1, "total_late_minutes": 1,
            "leave_count": 1, "on_duty_count": 1,
        }},
        {"$sort": {"department": 1}},
    ]


def late_leaderboard_pipeline(month: str, department: Optional[str] = None, limit: int = 10):
    month, first_day, next_month = validate_month(month)
    pipeline = [
        {"$match": {"date": {"$gte": first_day, "$lt": next_month}, "late_minutes": {"$gt": 0}}},
        {"$group": {
            "_id": "$emp_code",
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "late_count": {"$sum": 1},
        }},
        {"$lookup": {
            "from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"
        }},
        {"$unwind": "$employee"},
    ]
    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline.extend([
        {"$set": {"emp_code": "$_id", "name": "$employee.name", "department": "$employee.department"}},
        {"$setWindowFields": {
            "sortBy": {"total_late_minutes": -1},
            "output": {"rank": {"$rank": {}}},
        }},
        {"$match": {"rank": {"$lte": limit}}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": 1, "name": 1, "department": 1,
                       "total_late_minutes": 1, "late_count": 1}},
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
    ])
    return pipeline


def department_trend_pipeline(department: str, start_date: str, end_date: str):
    # $documents + $range creates the calendar entirely in MongoDB, including empty days.
    # No Python-side per-day loop or post-processing is used.
    return [
        {"$documents": [{"seed": 1}]},
        {"$set": {
            "_start": {"$dateFromString": {"dateString": start_date}},
            "_end": {"$dateFromString": {"dateString": end_date}},
        }},
        {"$set": {"_calendar": {"$map": {
            "input": {"$range": [0, {"$add": [{"$dateDiff": {
                "startDate": "$_start", "endDate": "$_end", "unit": "day"
            }}, 1]}]},
            "as": "offset",
            "in": {"$dateAdd": {"startDate": "$_start", "unit": "day", "amount": "$$offset"}},
        }}}},
        {"$unwind": "$_calendar"},
        {"$set": {"date": {"$dateToString": {"date": "$_calendar", "format": "%Y-%m-%d", "timezone": "UTC"}}}},
        {"$lookup": {
            "from": "employees",
            "let": {"day": "$date", "dept": {"$literal": department}},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$department", "$$dept"]},
                    {"$lte": ["$joined_on", "$$day"]},
                ]}}},
                {"$project": {"_id": 0, "emp_code": 1}},
            ],
            "as": "_eligible_employees",
        }},
        {"$set": {"headcount": {"$size": "$_eligible_employees"},
                   "_employee_codes": {"$map": {"input": "$_eligible_employees", "as": "e", "in": "$$e.emp_code"}}}},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"day": "$date", "codes": "$_employee_codes"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$date", "$$day"]},
                    {"$in": ["$emp_code", "$$codes"]},
                ]}}},
                {"$project": {"_id": 0, "status": 1, "half_day": 1, "late_minutes": 1}},
            ],
            "as": "_day_logs",
        }},
        {"$set": {
            "is_working_day": weekday_expr("$_calendar"),
            "present_count": {"$sum": {"$map": {"input": "$_day_logs", "as": "log", "in": {
                "$cond": [
                    {"$in": ["$$log.status", PRESENT_STATUSES]},
                    {"$cond": [{"$eq": ["$$log.half_day", True]}, 0.5, 1]},
                    0,
                ]
            }}}},
            "late_count": {"$sum": {"$map": {"input": "$_day_logs", "as": "log", "in": {
                "$cond": [{"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]}, 1, 0]
            }}}},
        }},
        {"$set": {"attendance_rate": {"$cond": [
            {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
            half_up_expr({"$divide": ["$present_count", "$headcount"]}, 4),
            None,
        ]}}},
        {"$setWindowFields": {
            "sortBy": {"date": 1},
            "output": {"_moving_avg_raw": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}},
        }},
        {"$set": {"moving_avg_7d": {"$cond": [
            {"$ne": [{"$ifNull": ["$_moving_avg_raw", None]}, None]},
            half_up_expr("$_moving_avg_raw", 4),
            None,
        ]}}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1,
                       "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}},
        {"$sort": {"date": 1}},
    ]


def _aggregate_or_503(collection, pipeline):
    try:
        return list(collection.aggregate(pipeline, allowDiskUse=True))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Analytics query failed") from exc


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    validate_month(month)
    results = _aggregate_or_503(db.employees, employee_monthly_pipeline(emp_code, month))
    if not results:
        raise HTTPException(status_code=404, detail="employee not found")
    return results[0]


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
):
    validate_month(month)
    return {"month": month, "items": _aggregate_or_503(db.employees, department_summary_pipeline(month, department))}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = None,
):
    validate_month(month)
    return {"month": month, "items": _aggregate_or_503(db.attendance_logs, late_leaderboard_pipeline(month, department, limit))}


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    start_date = validate_analytics_date(from_date, "from")
    end_date = validate_analytics_date(to_date, "to")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="to must be on or after from")
    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    if days > 92:
        raise HTTPException(status_code=422, detail="date range must not exceed 92 days")
    try:
        department_exists = next(db.employees.aggregate([{"$match": {"department": department}}, {"$limit": 1}, {"$project": {"_id": 1}}]), None)
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Database operation failed") from exc
    if department_exists is None:
        raise HTTPException(status_code=404, detail="department not found")
    pipeline = department_trend_pipeline(department, start_date, end_date)
    try:
        rows = list(db.aggregate(pipeline, allowDiskUse=True))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Analytics query failed") from exc
    return {"department": department, "items": rows}


def _explain_collection_aggregate(collection_name: str, pipeline: list):
    try:
        if collection_name == "$database":
            command = {"aggregate": 1, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}
            raw = db.command("explain", command, verbosity="executionStats")
            return json_util.loads(json_util.dumps(raw))
        command = {"aggregate": collection_name, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}
        raw = db.command("explain", command, verbosity="executionStats")
        return json_util.loads(json_util.dumps(raw))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB explain failed") from exc


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    if endpoint not in ANALYTICS_ENDPOINTS:
        raise HTTPException(status_code=422, detail=f"endpoint must be one of {', '.join(ANALYTICS_ENDPOINTS)}")

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if date_from or date_to:
            bounds = {}
            if date_from:
                bounds["$gte"] = validate_analytics_date(date_from, "date_from")
            if date_to:
                bounds["$lte"] = validate_analytics_date(date_to, "date_to")
            if date_from and date_to and date_from > date_to:
                raise HTTPException(status_code=422, detail="date_from must be <= date_to")
            query["date"] = bounds
        if status:
            if status not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid attendance status")
            query["status"] = status
        command = {"find": "attendance_logs", "filter": query,
                   "sort": {"date": -1, "emp_code": 1},
                   "skip": (page - 1) * page_size, "limit": page_size}
        try:
            raw = db.command("explain", command, verbosity="executionStats")
            explanation = json_util.loads(json_util.dumps(raw))
        except PyMongoError as exc:
            raise HTTPException(status_code=503, detail="MongoDB explain failed") from exc
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explanation}

    if endpoint in {"employee_monthly", "department_summary", "late_leaderboard"}:
        if not month:
            raise HTTPException(status_code=422, detail="month is required for this endpoint")
        validate_month(month)
        if endpoint == "employee_monthly":
            if not emp_code:
                raise HTTPException(status_code=422, detail="emp_code is required for this endpoint")
            collection_name = "employees"
            pipeline = employee_monthly_pipeline(emp_code, month)
        elif endpoint == "department_summary":
            collection_name = "employees"
            pipeline = department_summary_pipeline(month, department)
        else:
            collection_name = "attendance_logs"
            pipeline = late_leaderboard_pipeline(month, department, limit)
        return {"endpoint": endpoint, "collection": collection_name,
                "explain": _explain_collection_aggregate(collection_name, pipeline)}

    if endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(status_code=422, detail="department, from and to are required for this endpoint")
        start_date = validate_analytics_date(from_date, "from")
        end_date = validate_analytics_date(to_date, "to")
        if end_date < start_date or (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1 > 92:
            raise HTTPException(status_code=422, detail="invalid department trend date range")
        pipeline = department_trend_pipeline(department, start_date, end_date)
        return {"endpoint": endpoint, "collection": "database aggregate",
                "explain": _explain_collection_aggregate("$database", pipeline)}

    raise HTTPException(status_code=422, detail="unsupported endpoint")

