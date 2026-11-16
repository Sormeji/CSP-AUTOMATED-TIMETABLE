# Automated Class Timetable Management System (CSP Solver)

A full-stack **Automated Class Timetable Management System** built with **Python (Flask)**, **SQLite**, and a responsive web interface. The system models weekly academic scheduling as a **Constraint Satisfaction Problem (CSP)**, combining **Backtracking Search**, **Forward Checking**, **Minimum Remaining Values (MRV)** and **Degree** heuristics, and **Min-Conflicts Local Search** to generate collision-free class timetables.

---

## Key Features

- **Zero-Collision CSP Engine:** Enforces hard constraints to prevent room double-booking, faculty clashes, student cohort overlaps, room capacity overflows, and lab/lecture venue mismatches.
- **Lecture & Practical Hours per Course:** Set the length of one lecture and the total lecture hours per week, and the same for practicals. For example, 3 h/week of 1.5 h lectures becomes 2 lectures, and 2 h/week of 2 h practicals becomes 1 lab session. Practicals are always placed in lab rooms.
- **30-Minute Timeslots:** Add 30-minute slots for any set of days (or every day) in one step, with an option to keep lunch (13:00–14:00) free. Back-to-back slots merge into continuous windows, so a 1.5 h lecture occupies three consecutive slots.
- **Hybrid Solver Strategy:**
  - **Primary Solver:** Systematic Backtracking Search with Forward Checking, MRV variable ordering and the Degree heuristic.
  - **Fallback Optimizer:** Min-Conflicts Local Search repair when tight constraints exceed the exact search time limit.
- **Randomized Arrangements:** Each click on *Generate schedule* produces a new, equally valid timetable. The arrangement number (random seed) is shown and can be passed to the API to reproduce a layout.
- **Lectures and Practicals Spread Out:** A course's lecture and practical are placed on different days whenever possible, and each cohort's load is spread evenly across the week.
- **Schedule Check Panel:** After generation, a table lists every course with lecture and practical hours *scheduled vs. needed*, the days they landed on, and any issue (missing sessions, or lecture and practical on the same day).
- **Rule-Based Conflict Explainer:** Diagnoses unsolvable schedules before search and outputs clear, human-readable explanations. Examples: a cohort needs more hours than the timeslots cover, no lab is large enough, or no continuous block is long enough for a 2 h practical.
- **Dynamic Resource Management:** Add, **edit** and remove courses (delete asks for confirmation, and saves show a success message), multi-cohort groups, rooms/labs, and weekly timeslots directly from the browser.
- **Shared Classes:** One course can be attended by several cohorts at once (e.g. MSc and IMT together).
- **SQLite Persistence:** Automatically saves all courses, rooms, timeslots, and generated timetables in `timetable.db` across sessions. Databases from older versions are upgraded automatically.
- **Export & Print Ready:** Export schedules to formatted **CSV** files (with session type and duration) or generate print-ready **PDF** timetables with cohort filtering.

---

## CSP Mathematical Formulation

The scheduling problem is defined as a triple $(V, D, C)$:

- **Variables ($V$):** Weekly class meetings $\{c_1, c_2, \dots, c_n\}$. Each course expands into lecture meetings and practical meetings, each with its own duration $\text{Dur}(c_i)$.
- **Domains ($D$):** Available `(Day, Start, Room)` placements, filtered by static unary constraints:
  - the interval $[\text{Start}, \text{Start} + \text{Dur}(c_i))$ must lie inside one continuous window of that day's timeslots, starting on a half-hour boundary;
  - room capacity and lab requirements (constraints 4 and 5 below).
- **Hard Constraints ($C$):** Let $\text{Time}(c_i)$ be the interval a meeting occupies.
  1. **Room Double-Booking:** $\forall c_i, c_j (i \neq j)$, if $\text{Time}(c_i) \cap \text{Time}(c_j) \neq \emptyset$, then $\text{Room}(c_i) \neq \text{Room}(c_j)$.
  2. **Faculty Clash:** $\forall c_i, c_j (i \neq j)$, if $\text{Instructor}(c_i) = \text{Instructor}(c_j)$, then $\text{Time}(c_i) \cap \text{Time}(c_j) = \emptyset$.
  3. **Student Cohort Clash:** $\forall c_i, c_j (i \neq j)$, if $\text{Cohort}(c_i) \cap \text{Cohort}(c_j) \neq \emptyset$, then $\text{Time}(c_i) \cap \text{Time}(c_j) = \emptyset$.
  4. **Room Capacity:** $\text{Capacity}(\text{Room}(c_i)) \ge \text{StudentsCount}(c_i)$.
  5. **Venue Type Match:** If $c_i$ is a practical, $\text{IsLab}(\text{Room}(c_i))$ must be `True`.
  6. **Spread Within a Course:** If $c_i$ and $c_j$ are two lectures (or two practicals) of the same course, then $\text{Day}(c_i) \neq \text{Day}(c_j)$.
- **Soft Preferences** (value ordering; broken only when necessary):
  - a course's lecture and practical on different days;
  - each cohort's classes spread evenly across the week;
  - the smallest room that fits, with lectures kept out of labs so labs stay free for practicals;
  - remaining ties broken randomly, which gives a different valid timetable on each run.
- **Feasibility Pre-Checks (pigeonhole):** Before searching, the explainer proves impossibility when a cohort, instructor, or the room/lab pool needs more weekly hours than the timeslots cover, when a course has more lectures (or practicals) than days able to host them, or when a meeting is longer than any continuous window.

---

## Project Structure

```text
CSP-AUTOMATED-TIMETABLE/
├── app.py                  # Flask web server, REST API endpoints, input validation, schedule check report
├── csp_solver.py           # Backtracking + Forward Checking, Min-Conflicts, time windows, and Conflict Explainer
├── database.py             # SQLite initialization, state persistence, default seeding, and schema upgrades
├── models.py               # Data models for Room, ClassSession, and Timeslot, plus time helpers
├── requirements.txt        # Python dependencies (Flask, Gunicorn)
├── Procfile                # Production process declaration for cloud hosting
├── README.md
├── static/
│   ├── css/
│   │   └── style.css       # Custom styling and print layout rules
│   ├── img/                # Institutional branding assets
│   └── js/
│       └── app.js          # Frontend state, course/slot forms, timetable grid, schedule check, CSV & PDF export
├── templates/
│   └── index.html          # Main web dashboard interface
└── tests/
    └── test_solver.py      # Unit and API tests
```

---

## Local Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Sormeji/CSP-AUTOMATED-TIMETABLE.git
   cd CSP-AUTOMATED-TIMETABLE
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

5. **Open in browser:**
   Navigate to `http://127.0.0.1:5000`. The application automatically initializes `timetable.db` with the default Monsoon 2026 dataset on first launch. The dataset uses 30-minute slots from Monday to Friday, 09:30–13:00 and 14:00–17:30.

> `timetable.db` is created in the folder you run the command from. Always start the app from the same folder so your saved data loads.

### Configuration (environment variables)

| Variable            | Default        | Purpose                                                        |
|---------------------|----------------|----------------------------------------------------------------|
| `PORT`              | `5000`         | Port for `python app.py` (on macOS, use e.g. `5050` if 5000 is busy) |
| `TIMETABLE_DB_PATH` | `timetable.db` | Location of the SQLite database                                |
| `SOLVER_TIME_LIMIT` | `5`            | Seconds of backtracking before Min-Conflicts takes over        |
| `FLASK_DEBUG`       | off            | Set to `1` for auto-reload during development                  |

---

## Usage

**Setup tab**

1. **Courses:** Enter code, title, instructor, students, and the cohort(s) attending. Then set:
   - *Hours per lecture* and *Lecture hours / week*
   - *Hours per practical* and *Practical hours / week* (0 if there is no practical)

   A live summary shows the result, e.g. *"Each week: 2 lectures × 1.5 h + 1 practical × 2 h"*. Weekly hours must be a multiple of the session length. Use **Edit** to change a course, or **×** to delete it (with confirmation).
2. **Rooms:** Room ID, capacity, and whether it is a lab.
3. **Timeslots:** Tick the days (or *Every day*), choose *From* and *To*, and click **Add 30-min slots**. A single custom slot can be added under *Add a single custom slot*. Use **Remove day** or **Clear all** to rebuild.

**Timetable tab**

Click **Generate schedule**, review the **Schedule check** panel, filter by cohort, and export to CSV or PDF. Click **Generate schedule** again for a different arrangement.

---

## REST API

| Method & Path            | Description                                                              |
|--------------------------|--------------------------------------------------------------------------|
| `GET  /`                 | Web dashboard                                                            |
| `GET  /api/initial-data` | Saved rooms, timeslots, courses, and the last generated timetable        |
| `POST /api/save-data`    | Persist rooms, timeslots, and courses                                    |
| `POST /api/reset-data`   | Restore the default dataset                                              |
| `POST /api/solve`        | Generate a timetable from `{rooms, timeslots, courses}`. Optional `seed` reproduces an arrangement |

Example course object:

```json
{
  "code": "FML", "name": "Fundamentals of ML", "instructor": "Dr. Reshma Rastogi",
  "cohort": "1MSc1", "students": 30,
  "lectureDuration": 1.5, "lectureHours": 3,
  "labDuration": 2, "labHours": 2
}
```

The older format (`sessionsPerWeek` + `requiresLab`) is still accepted. Each meeting is then treated as 1 hour.

---

## Running Tests

```bash
TIMETABLE_DB_PATH=/tmp/test.db python -m unittest tests.test_solver
```

A separate database path keeps your real `timetable.db` untouched.

---

## Cloud Deployment (Render)

1. Connect your GitHub repository to a new **Web Service** on [Render](https://render.com).
2. Configure the service settings:
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app` *(or `gunicorn --chdir <subfolder> app:app` if nested inside a subdirectory)*
3. Deploy the service to obtain your live public URL.

> Render's free instances have a temporary filesystem, so `timetable.db` resets to the default dataset on each redeploy or restart. Attach a persistent disk and point `TIMETABLE_DB_PATH` to it to keep data.

---

## Tech Stack

- **Backend:** Python 3, Flask, Gunicorn
- **Database:** SQLite3
- **Frontend:** HTML5, CSS3, Tailwind CSS, Vanilla JavaScript
- **AI / Algorithms:** Constraint Satisfaction Problem (CSP), Backtracking Search, Forward Checking, MRV & Degree Heuristics, Min-Conflicts Local Search, randomized value ordering
