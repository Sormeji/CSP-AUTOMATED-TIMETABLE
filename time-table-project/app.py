import os
from flask import Flask, render_template, request, jsonify
from models import Room, ClassSession, Timeslot
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

initial_timeslots = [
    {"id": "TS1", "day": "Monday", "time": "09:30-10:30"},
    {"id": "TS2", "day": "Monday", "time": "11:30-13:00"},
    {"id": "TS3", "day": "Monday", "time": "14:00-15:30"},
    {"id": "TS4", "day": "Tuesday", "time": "09:30-11:00"},
    {"id": "TS5", "day": "Tuesday", "time": "11:00-12:30"},
    {"id": "TS6", "day": "Wednesday", "time": "09:30-11:00"},
    {"id": "TS7", "day": "Wednesday", "time": "11:00-12:30"},
    {"id": "TS8", "day": "Thursday", "time": "09:30-11:00"},
    {"id": "TS9", "day": "Thursday", "time": "14:00-15:30"},
    {"id": "TS10", "day": "Friday", "time": "09:30-11:00"},
    {"id": "TS11", "day": "Friday", "time": "11:00-12:30"}
]

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

initial_courses = [
    {"id": "C1", "code": "FAI", "name": "Fundamentals of AI", "instructor": "Dr. Amit Shukla", "cohort": "1MSc1", "students": 45, "requiresLab": False, "sessionsPerWeek": 1},
    {"id": "C2", "code": "FML", "name": "Fundamentals of ML", "instructor": "Dr. Reshma Rastogi", "cohort": "1MSc1", "students": 30, "requiresLab": True, "sessionsPerWeek": 1},
    {"id": "C3", "code": "OSD", "name": "Operating Systems", "instructor": "Dr. Shachi Sharma", "cohort": "MCA1", "students": 40, "requiresLab": False, "sessionsPerWeek": 1},
    {"id": "C4", "code": "MFCS", "name": "Math Foundations", "instructor": "Dr. Manvi Grover", "cohort": "MCA1", "students": 40, "requiresLab": False, "sessionsPerWeek": 1},
    {"id": "C5", "code": "OT", "name": "Optimization Tech", "instructor": "Dr. Garima", "cohort": "1MSc1", "students": 45, "requiresLab": False, "sessionsPerWeek": 1},
    {"id": "C6", "code": "FSD3", "name": "Full Stack Dev 3", "instructor": "Dr. Anurag Tiwari", "cohort": "MCA3", "students": 30, "requiresLab": True, "sessionsPerWeek": 1},
    {"id": "C7", "code": "COD", "name": "Computer Org", "instructor": "Prof. Pranab K. Muhuri", "cohort": "MCA1", "students": 40, "requiresLab": False, "sessionsPerWeek": 1},
    {"id": "C8", "code": "DBMS", "name": "Database Systems", "instructor": "Dr. Ashwini B", "cohort": "MCA1", "students": 30, "requiresLab": True, "sessionsPerWeek": 1}
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
        per_week = _int(c, 'sessionsPerWeek', label, default=1)
        for k in range(per_week):
            sessions.append(ClassSession(
                id=course_id if per_week == 1 else f"{course_id}#{k + 1}",
                course_code=code,
                name=_str(c, 'name', label, required=False),
                instructor_id=_str(c, 'instructor', label),
                cohort_id=_cohorts(c, label),
                students_count=_int(c, 'students', label),
                requires_lab=_bool(c.get('requiresLab')),
                course_id=course_id,
            ))
    if not sessions:
        raise InputError("Add at least one course before generating a schedule.")
    return rooms, timeslots, sessions

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
        if not csp.domains[session] and session.course_id not in seen_courses:
            seen_courses.add(session.course_id)
            diagnostics.extend(ConflictExplainer.explain_static_impossibility(session, rooms))

    if diagnostics:
        return jsonify({
            "success": False,
            "schedule": None,
            "diagnostics": diagnostics,
            "stats": None
        }), 400

    # Run Backtracking Search with Forward Checking
    solver = BacktrackingSolver(csp, time_limit_s=float(os.environ.get("SOLVER_TIME_LIMIT", 5)))
    solution, execution_time = solver.solve()
    method = "backtracking"
    if solution is None and solver.timed_out:
        solution, _ = MinConflictsSolver(csp).solve()
        method = "min-conflicts"
    stats = {"timeMs": round(execution_time, 2), "backtracks": solver.backtracks, "method": method}

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
                "slot": {"id": slot.id, "day": slot.day, "time": slot.time, "start": slot.start},
                "room": {"id": room.id, "capacity": room.capacity, "is_lab": room.is_lab}
            }
        save_schedule(formatted_schedule, stats)
        return jsonify({
            "success": True,
            "schedule": formatted_schedule,
            "diagnostics": [],
            "stats": stats
        })

    if solver.timed_out:
        message = ("The solver ran out of time without finding a conflict-free timetable. "
                   "The constraints are very tight: try adding timeslots or venues.")
    else:
        message = ("No conflict-free timetable exists: every combination violates a faculty, cohort, "
                   "room or same-course-same-day constraint. Try adding more timeslots or venues.")
    return jsonify({"success": False, "schedule": None, "diagnostics": [message], "stats": stats}), 422

if __name__ == '__main__':
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))