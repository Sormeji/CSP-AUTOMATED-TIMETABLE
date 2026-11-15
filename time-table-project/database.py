import sqlite3
import json
import os

DB_PATH = os.environ.get("TIMETABLE_DB_PATH", "timetable.db")


def get_connection():
    """Creates and returns a SQLite database connection with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def course_hours(c):
    """(lecture_duration, lecture_hours, lab_duration, lab_hours) in hours for a course dict.
    Courses saved before hours existed (sessionsPerWeek + requiresLab) become 1-hour meetings."""
    if any(k in c for k in ("lectureHours", "labHours")):
        return (_num(c.get("lectureDuration")), _num(c.get("lectureHours")),
                _num(c.get("labDuration")), _num(c.get("labHours")))
    n = int(_num(c.get("sessionsPerWeek"), 1)) or 1
    return (0.0, 0.0, 1.0, float(n)) if c.get("requiresLab") else (1.0, float(n), 0.0, 0.0)


def _insert_course(cursor, course_id, c, cohort_str):
    lec_d, lec_h, lab_d, lab_h = course_hours(c)
    sessions = (int(lec_h // lec_d) if lec_d else 0) + (int(lab_h // lab_d) if lab_d else 0)
    cursor.execute(
        """INSERT INTO courses
           (id, code, name, instructor, cohort, students, requires_lab, sessions_per_week,
            lecture_duration, lecture_hours, lab_duration, lab_hours)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            course_id,
            str(c["code"]).strip(),
            str(c.get("name", "")).strip(),
            str(c["instructor"]).strip(),
            cohort_str,
            int(c["students"]),
            1 if lab_h > 0 else 0,
            max(sessions, 1),
            lec_d, lec_h, lab_d, lab_h,
        )
    )


def _migrate_course_hours(cursor):
    """Adds the lecture/practical hour columns to databases created by older versions
    and fills them from the old sessions_per_week / requires_lab values."""
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(courses)").fetchall()}
    for column in ("lecture_duration", "lecture_hours", "lab_duration", "lab_hours"):
        if column not in existing:
            cursor.execute(f"ALTER TABLE courses ADD COLUMN {column} REAL")
    cursor.execute("""
        UPDATE courses SET
            lecture_duration = CASE WHEN requires_lab = 1 THEN 0 ELSE 1 END,
            lecture_hours    = CASE WHEN requires_lab = 1 THEN 0 ELSE sessions_per_week END,
            lab_duration     = CASE WHEN requires_lab = 1 THEN 1 ELSE 0 END,
            lab_hours        = CASE WHEN requires_lab = 1 THEN sessions_per_week ELSE 0 END
        WHERE lecture_hours IS NULL AND lab_hours IS NULL
    """)


def init_db(default_rooms, default_timeslots, default_courses):
    """Initializes database tables and seeds default Monsoon 2026 data if empty."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Rooms Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                capacity INTEGER NOT NULL,
                is_lab INTEGER NOT NULL DEFAULT 0
            )
        """)

        # 2. Timeslots Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS timeslots (
                id TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                time TEXT NOT NULL
            )
        """)

        # 3. Courses Table (supports comma-separated cohorts and sessions_per_week)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT,
                instructor TEXT NOT NULL,
                cohort TEXT NOT NULL,
                students INTEGER NOT NULL,
                requires_lab INTEGER NOT NULL DEFAULT 0,
                sessions_per_week INTEGER NOT NULL DEFAULT 1,
                lecture_duration REAL,
                lecture_hours REAL,
                lab_duration REAL,
                lab_hours REAL
            )
        """)
        _migrate_course_hours(cursor)

        # 4. Saved Schedules Table (stores latest solved JSON)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_schedules (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schedule_json TEXT NOT NULL,
                stats_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default data only if all resource tables are completely empty
        room_count = cursor.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        slot_count = cursor.execute("SELECT COUNT(*) FROM timeslots").fetchone()[0]
        course_count = cursor.execute("SELECT COUNT(*) FROM courses").fetchone()[0]

        if room_count == 0 and slot_count == 0 and course_count == 0:
            for r in default_rooms:
                cursor.execute(
                    "INSERT INTO rooms (id, capacity, is_lab) VALUES (?, ?, ?)",
                    (r["id"], r["capacity"], 1 if r.get("is_lab") else 0)
                )
            for t in default_timeslots:
                cursor.execute(
                    "INSERT INTO timeslots (id, day, time) VALUES (?, ?, ?)",
                    (t["id"], t["day"], t["time"])
                )
            for c in default_courses:
                cohort_val = ", ".join(c["cohorts"]) if isinstance(c.get("cohorts"), list) else str(c.get("cohort", ""))
                _insert_course(cursor, c["id"], c, cohort_val)
        conn.commit()


def load_state():
    """Fetches all persisted rooms, timeslots, courses, and the latest schedule."""
    with get_connection() as conn:
        cursor = conn.cursor()

        rooms = [
            {"id": row["id"], "capacity": row["capacity"], "is_lab": bool(row["is_lab"])}
            for row in cursor.execute("SELECT * FROM rooms").fetchall()
        ]

        timeslots = [
            {"id": row["id"], "day": row["day"], "time": row["time"]}
            for row in cursor.execute("SELECT * FROM timeslots").fetchall()
        ]

        courses = []
        for row in cursor.execute("SELECT * FROM courses").fetchall():
            cohort_str = row["cohort"] or ""
            cohort_list = [c.strip() for c in cohort_str.split(",") if c.strip()]
            courses.append({
                "id": row["id"],
                "code": row["code"],
                "name": row["name"] or "",
                "instructor": row["instructor"],
                "cohort": cohort_str,
                "cohorts": cohort_list,
                "students": row["students"],
                "requiresLab": bool(row["requires_lab"]),
                "sessionsPerWeek": row["sessions_per_week"],
                "lectureDuration": row["lecture_duration"] or 0,
                "lectureHours": row["lecture_hours"] or 0,
                "labDuration": row["lab_duration"] or 0,
                "labHours": row["lab_hours"] or 0,
            })

        sched_row = cursor.execute("SELECT schedule_json, stats_json FROM saved_schedules WHERE id = 1").fetchone()
        schedule = json.loads(sched_row["schedule_json"]) if sched_row else None
        stats = json.loads(sched_row["stats_json"]) if (sched_row and sched_row["stats_json"]) else None

        return {
            "rooms": rooms,
            "timeslots": timeslots,
            "courses": courses,
            "schedule": schedule,
            "stats": stats
        }


def save_resources(rooms, timeslots, courses):
    """Replaces stored rooms, timeslots, and courses with the latest state from the UI."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rooms")
        cursor.execute("DELETE FROM timeslots")
        cursor.execute("DELETE FROM courses")

        for r in rooms:
            cursor.execute(
                "INSERT INTO rooms (id, capacity, is_lab) VALUES (?, ?, ?)",
                (str(r["id"]).strip(), int(r["capacity"]), 1 if r.get("is_lab") else 0)
            )

        for idx, t in enumerate(timeslots):
            slot_id = t.get("id") or f"TS{idx + 1}"
            cursor.execute(
                "INSERT INTO timeslots (id, day, time) VALUES (?, ?, ?)",
                (slot_id, str(t["day"]).strip(), str(t["time"]).strip())
            )

        for idx, c in enumerate(courses):
            course_id = f"C{idx + 1}"
            if isinstance(c.get("cohorts"), list) and c["cohorts"]:
                cohort_str = ", ".join(str(x).strip() for x in c["cohorts"] if str(x).strip())
            else:
                cohort_str = str(c.get("cohort", "")).strip()

            _insert_course(cursor, course_id, c, cohort_str)
        conn.commit()


def save_schedule(schedule, stats):
    """Persists the most recently solved timetable and solver metrics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO saved_schedules (id, schedule_json, stats_json, updated_at)
               VALUES (1, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                   schedule_json = excluded.schedule_json,
                   stats_json = excluded.stats_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (json.dumps(schedule), json.dumps(stats))
        )
        conn.commit()


def reset_to_defaults(default_rooms, default_timeslots, default_courses):
    """Clears all custom entries and restores the initial Monsoon 2026 dataset."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rooms")
        cursor.execute("DELETE FROM timeslots")
        cursor.execute("DELETE FROM courses")
        cursor.execute("DELETE FROM saved_schedules")
        conn.commit()
    init_db(default_rooms, default_timeslots, default_courses)