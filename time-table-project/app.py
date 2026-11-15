import os
import random
from collections import defaultdict
from flask import Flask, render_template, request, jsonify
from models import Room, ClassSession, Timeslot, format_range
from csp_solver import ClassTimetableCSP, BacktrackingSolver, MinConflictsSolver, ConflictExplainer
from database import init_db, load_state, save_resources, save_schedule, reset_to_defaults

app = Flask(__name__)

# Sample Initial Dataset (Monsoon 2026 Curriculum)
initial_rooms = [
    {"id": "CSE009", "capacity": 60, "is_lab": False},
    {"id": "CSE005", "capacity": 50, "is_lab": False},
    {"id": "CSE010", "capacity": 40, "is_lab": False},
    {"id": "CSE002", "capacity": 35, "is_lab": True},
    {"id": "CSE115", "capacity": 35, "is_lab": True}
]

def half_hour_slots(days, ranges):
    """30-minute timeslots for every day, e.g. ranges=[("09:30", "13:00"), ("14:00", "17:30")]."""
    to_min = lambda t: int(t[:2]) * 60 + int(t[3:])
    slots = []
    for day in days:
        for start, end in ranges:
            for m in range(to_min(start), to_min(end), 30):
                slots.append({"id": f"TS{len(slots) + 1}", "day": day, "time": format_range(m, m + 30)})
    return slots

# 30-minute slots every weekday, with the 13:00-14:00 lunch break left free
initial_timeslots = half_hour_slots(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    [("09:30", "13:00"), ("14:00", "17:30")],
)

predefined_time_ranges = [
    "08:30-09:30",
    "09:30-10:30",
    "09:30-11:00",
    "10:30-11:30",
    "11:00-12:30",
    "11:30-13:00",
    "12:30-13:30",
    "14:00-15:00",
    "14:00-15:30",
    "15:30-17:00",
    "16:00-17:30",
    "16:00-18:00"
]

# lectureDuration / labDuration: hours per meeting; lectureHours / labHours: total hours per week
initial_courses = [
    {"id": "C1", "code": "FAI", "name": "Fundamentals of AI", "instructor": "Dr. Amit Shukla", "cohort": "1MSc1", "students": 45,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 0, "labHours": 0},
    {"id": "C2", "code": "FML", "name": "Fundamentals of ML", "instructor": "Dr. Reshma Rastogi", "cohort": "1MSc1", "students": 30,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 2, "labHours": 2},
    {"id": "C3", "code": "OSD", "name": "Operating Systems", "instructor": "Dr. Shachi Sharma", "cohort": "MCA1", "students": 40,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 0, "labHours": 0},
    {"id": "C4", "code": "MFCS", "name": "Math Foundations", "instructor": "Dr. Manvi Grover", "cohort": "MCA1", "students": 40,
     "lectureDuration": 1, "lectureHours": 3, "labDuration": 0, "labHours": 0},
    {"id": "C5", "code": "OT", "name": "Optimization Tech", "instructor": "Dr. Garima", "cohort": "1MSc1", "students": 45,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 0, "labHours": 0},
    {"id": "C6", "code": "FSD3", "name": "Full Stack Dev 3", "instructor": "Dr. Anurag Tiwari", "cohort": "MCA3", "students": 30,
     "lectureDuration": 1, "lectureHours": 2, "labDuration": 2, "labHours": 4},
    {"id": "C7", "code": "COD", "name": "Computer Org", "instructor": "Prof. Pranab K. Muhuri", "cohort": "MCA1", "students": 40,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 0, "labHours": 0},
    {"id": "C8", "code": "DBMS", "name": "Database Systems", "instructor": "Dr. Ashwini B", "cohort": "MCA1", "students": 30,
     "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 2, "labHours": 2},
]

# Initialize SQLite database on startup
init_db(initial_rooms, initial_timeslots, initial_courses)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/initial-data', methods=['GET'])
def get_initial_data():
    state = load_state()
    if not state["rooms"] and not state["timeslots"] and not state["courses"]:
        init_db(initial_rooms, initial_timeslots, initial_courses)
        state = load_state()
    return jsonify({
        **state,
        "predefinedTimes": predefined_time_ranges
    })

@app.route('/api/save-data', methods=['POST'])
def save_data():
    data = request.get_json(silent=True) or {}
    try:
        save_resources(
            data.get("rooms", []),
            data.get("timeslots", []),
            data.get("courses", [])
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/reset-data', methods=['POST'])
def reset_data():
    reset_to_defaults(initial_rooms, initial_timeslots, initial_courses)
    state = load_state()
    return jsonify({"success": True, **state, "predefinedTimes": predefined_time_ranges})

class InputError(ValueError):
    pass

def _str(obj, key, label, required=True):
    value = obj.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise InputError(f"{label}: '{key}' is required.")
    return value

def _int(obj, key, label, minimum=1, default=None):
    value = obj.get(key, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise InputError(f"{label}: '{key}' must be a whole number (got {value!r}).")
    if number < minimum:
        raise InputError(f"{label}: '{key}' must be at least {minimum}.")
    return number

def _bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)

def _cohorts(obj, label):
    """Cohorts as a list (['1MSc1', 'MTI']) or a comma-separated string ('1MSc1, MTI')."""
    raw = obj.get('cohorts')
    if not isinstance(raw, list):
        raw = str(obj.get('cohort') or '').split(',')
    cohorts = []
    for c in raw:
        c = str(c).strip()
        if c and c.lower() not in (x.lower() for x in cohorts):
            cohorts.append(c)
    if not cohorts:
        raise InputError(f"{label}: at least one cohort is required.")
    return ", ".join(cohorts)

def _hours(obj, key, label):
    """Hours as a non-negative multiple of 0.5 (30 minutes); returns minutes."""
    value = obj.get(key) or 0
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise InputError(f"{label}: '{key}' must be a number of hours (got {value!r}).")
    minutes = hours * 60
    if hours < 0 or hours > 40 or abs(minutes - round(minutes / 30) * 30) > 1e-6:
        raise InputError(f"{label}: '{key}' must be between 0 and 40 hours, in steps of 0.5 (got {value!r}).")
    return int(round(minutes))

def course_plan(c, label):
    """[(kind, minutes per meeting, meetings per week)] for a course.

    New style: lectureDuration + lectureHours and/or labDuration + labHours (hours).
    Old style (sessionsPerWeek + requiresLab) is still accepted: each meeting is 1 hour."""
    if not any(k in c for k in ("lectureHours", "labHours")):
        per_week = _int(c, 'sessionsPerWeek', label, default=1)
        return [("lab" if _bool(c.get('requiresLab')) else "lecture", 60, per_week)]

    plan = []
    for kind, dur_key, total_key, word in (("lecture", "lectureDuration", "lectureHours", "Lecture"),
                                           ("lab", "labDuration", "labHours", "Practical")):
        total = _hours(c, total_key, label)
        if total == 0:
            continue
        duration = _hours(c, dur_key, label)
        if duration == 0:
            raise InputError(f"{label}: set how many hours each {word.lower()} lasts.")
        if total % duration:
            raise InputError(
                f"{label}: {word.lower()} hours per week ({total / 60:g} h) must be a multiple of "
                f"the {word.lower()} length ({duration / 60:g} h).")
        plan.append((kind, duration, total // duration))
    if not plan:
        raise InputError(f"{label}: give it some lecture or practical hours per week.")
    return plan

def parse_payload(data):
    """Turn the raw JSON body into model objects, rejecting malformed or ambiguous input."""
    if not isinstance(data, dict):
        raise InputError("Request body must be a JSON object with rooms, timeslots and courses.")

    rooms, seen_rooms = [], set()
    for r in data.get('rooms') or []:
        room_id = _str(r, 'id', "Room")
        if room_id.lower() in seen_rooms:
            raise InputError(f"Room '{room_id}' is listed more than once.")
        seen_rooms.add(room_id.lower())
        rooms.append(Room(id=room_id, capacity=_int(r, 'capacity', f"Room {room_id}"), is_lab=_bool(r.get('is_lab'))))

    timeslots, seen_slots = [], set()
    for i, t in enumerate(data.get('timeslots') or []):
        label = f"Timeslot {i + 1}"
        try:
            slot = Timeslot.create(id=f"TS{i + 1}", day=_str(t, 'day', label), time=_str(t, 'time', label))
        except ValueError as e:
            raise InputError(f"{label}: {e}")
        if (slot.day, slot.start, slot.end) in seen_slots:
            continue
        seen_slots.add((slot.day, slot.start, slot.end))
        timeslots.append(slot)

    sessions = []
    for i, c in enumerate(data.get('courses') or []):
        course_id = f"C{i + 1}"
        code = _str(c, 'code', f"Course {i + 1}")
        label = f"Course {code}"
        common = dict(
            course_code=code,
            name=_str(c, 'name', label, required=False),
            instructor_id=_str(c, 'instructor', label),
            cohort_id=_cohorts(c, label),
            students_count=_int(c, 'students', label),
            course_id=course_id,
        )
        for kind, duration, count in course_plan(c, label):
            letter = "P" if kind == "lab" else "L"
            for k in range(count):
                sessions.append(ClassSession(
                    id=f"{course_id}-{letter}{k + 1}",
                    requires_lab=(kind == "lab"),
                    kind=kind,
                    duration=duration,
                    **common,
                ))
    if not sessions:
        raise InputError("Add at least one course before generating a schedule.")
    return rooms, timeslots, sessions

def schedule_checks(sessions, solution):
    """Per course: weekly hours asked for vs placed, and anything that ended up on the same day."""
    by_course = defaultdict(list)
    for s in sessions:
        by_course[s.course_id].append(s)
    checks = []
    for course_id, members in by_course.items():
        first = members[0]
        row = {"code": first.course_code, "name": first.name, "cohort": first.cohort_id, "issues": []}
        for kind in ("lecture", "lab"):
            wanted = [s for s in members if s.kind == kind]
            placed = [s for s in wanted if s in solution]
            row[kind] = {
                "required": sum(s.duration for s in wanted) / 60,
                "scheduled": sum(solution[s][0].minutes for s in placed) / 60,
                "meetings": len(placed),
                "days": [solution[s][0].day for s in placed],
            }
            if len(placed) < len(wanted):
                row["issues"].append(f"{len(wanted) - len(placed)} {kind if kind == 'lecture' else 'practical'}(s) not scheduled")
        shared = sorted(set(row["lecture"]["days"]) & set(row["lab"]["days"]))
        if shared:
            row["issues"].append(f"Lecture and practical both on {', '.join(shared)} (no other free day fitted)")
        checks.append(row)
    return checks

@app.route('/api/solve', methods=['POST'])
def solve_timetable():
    raw_data = request.get_json(silent=True)
    try:
        rooms, timeslots, sessions = parse_payload(raw_data)
    except InputError as e:
        return jsonify({"success": False, "schedule": None, "diagnostics": [str(e)], "stats": None}), 400

    # Persist latest input configuration before solving
    save_resources(
        raw_data.get("rooms", []),
        raw_data.get("timeslots", []),
        raw_data.get("courses", [])
    )

    # Initialize CSP
    csp = ClassTimetableCSP(sessions, rooms, timeslots)

    # Check for domain wipeouts/static conflicts before solving
    diagnostics = ConflictExplainer.explain_global_impossibility(sessions, rooms, timeslots)
    seen_courses = set()
    for session in sessions:
        if not csp.domains[session] and session.group_key not in seen_courses:
            seen_courses.add(session.group_key)
            diagnostics.extend(ConflictExplainer.explain_static_impossibility(session, rooms, timeslots))

    if diagnostics:
        return jsonify({
            "success": False,
            "schedule": None,
            "diagnostics": diagnostics,
            "stats": None
        }), 400

    # Run Backtracking Search with Forward Checking
    # A fresh random seed each time gives a different arrangement on every "Generate";
    # pass {"seed": n} to reproduce one.
    seed = raw_data.get("seed")
    seed = int(seed) if isinstance(seed, (int, float)) or (isinstance(seed, str) and seed.isdigit()) else random.randrange(1_000_000)
    solver = BacktrackingSolver(csp, time_limit_s=float(os.environ.get("SOLVER_TIME_LIMIT", 5)), seed=seed)
    solution, execution_time = solver.solve()
    method = "backtracking"
    if solution is None and solver.timed_out:
        solution, _ = MinConflictsSolver(csp, seed=seed).solve()
        method = "min-conflicts"
    stats = {"timeMs": round(execution_time, 2), "backtracks": solver.backtracks, "method": method, "seed": seed}

    if solution:
        formatted_schedule = {}
        for session, (slot, room) in solution.items():
            formatted_schedule[session.id] = {
                "courseCode": session.course_code,
                "courseName": session.name,
                "instructor": session.instructor_id,
                "cohort": session.cohort_id,
                "cohorts": list(session.cohorts),
                "students": session.students_count,
                "requiresLab": session.requires_lab,
                "kind": session.kind,
                "durationMin": slot.end - slot.start,
                "slot": {"id": slot.id, "day": slot.day, "time": slot.time, "start": slot.start, "end": slot.end},
                "room": {"id": room.id, "capacity": room.capacity, "is_lab": room.is_lab}
            }
        stats["checks"] = schedule_checks(sessions, solution)
        save_schedule(formatted_schedule, stats)
        return jsonify({
            "success": True,
            "schedule": formatted_schedule,
            "diagnostics": [],
            "stats": stats
        })

    if solver.timed_out:
        message = ("The solver ran out of time without finding a conflict-free timetable. "
                   "The constraints are very tight: try adding timeslots or venues, or shorter lecture/practical lengths.")
    else:
        message = ("No conflict-free timetable exists: every combination violates a faculty, cohort, "
                   "room or same-course-same-day constraint. Try adding more timeslots or venues.")
    return jsonify({"success": False, "schedule": None, "diagnostics": [message], "stats": stats}), 422

if __name__ == '__main__':
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))