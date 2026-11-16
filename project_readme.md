# Automated Class Timetable Management System (CSP Solver)

A full-stack **Automated Class Timetable Management System** built with **Python (Flask)**, **SQLite**, and a responsive web interface. The system models weekly academic scheduling as a **Constraint Satisfaction Problem (CSP)**, combining **Backtracking Search**, **Forward Checking**, **Minimum Remaining Values (MRV)** heuristics, and **Min-Conflicts Local Search** to generate guaranteed collision-free class timetables.

---

## Key Features

- **Zero-Collision CSP Engine:** Mathematically enforces hard constraints to prevent room double-booking, faculty clashes, student cohort overlaps, room capacity overflows, and lab/lecture venue mismatches.
- **Hybrid Solver Strategy:**
  - **Primary Solver:** Systematic Backtracking Search with Forward Checking and MRV variable ordering.
  - **Fallback Optimizer:** Min-Conflicts Local Search repair when tight constraints exceed the exact search time limit.
- **Rule-Based Conflict Explainer:** Diagnoses unsolvable schedules before or during search and outputs clear, human-readable explanations (e.g., missing lab capacity or resource bottlenecks).
- **Dynamic Resource Management:** Add, view, and remove courses, instructors, multi-cohort groups, rooms/labs, and weekly timeslots directly from the browser.
- **SQLite Persistence:** Automatically saves all courses, rooms, timeslots, and generated timetables in `timetable.db` across sessions.
- **Export & Print Ready:** Export schedules to formatted **CSV** files or generate print-ready **PDF** timetables with cohort filtering.

---

## CSP Mathematical Formulation

The scheduling problem is defined as a triple $(V, D, C)$:

- **Variables ($V$):** Weekly class sessions $C = \{c_1, c_2, \dots, c_n\}$.
- **Domains ($D$):** Available `(Timeslot, Room)` pairs filtered by static unary constraints (room capacity and lab requirements).
- **Hard Constraints ($C$):**
  1. **Room Double-Booking:** $\forall c_i, c_j (i \neq j)$, if $\text{Slot}(c_i) = \text{Slot}(c_j)$, then $\text{Room}(c_i) \neq \text{Room}(c_j)$.
  2. **Faculty Clash:** $\forall c_i, c_j (i \neq j)$, if $\text{Instructor}(c_i) = \text{Instructor}(c_j)$, then $\text{Slot}(c_i) \neq \text{Slot}(c_j)$.
  3. **Student Cohort Clash:** $\forall c_i, c_j (i \neq j)$, if $\text{Cohort}(c_i) \cap \text{Cohort}(c_j) \neq \emptyset$, then $\text{Slot}(c_i) \neq \text{Slot}(c_j)$.
  4. **Room Capacity:** $\text{Capacity}(\text{Room}(c_i)) \ge \text{Students Count}(c_i)$.
  5. **Venue Type Match:** If $c_i$ requires a lab, $\text{IsLab}(\text{Room}(c_i))$ must be `True`.

---

## Project Structure

```text
CSP-AUTOMATED-TIMETABLE/
├── app.py                  # Flask web server and REST API endpoints
├── csp_solver.py           # Backtracking + Forward Checking, Min-Conflicts, and Conflict Explainer
├── database.py             # SQLite initialization, state persistence, and default seeding
├── models.py               # Data models for Room, ClassSession, and Timeslot
├── requirements.txt        # Python dependencies (Flask, Gunicorn)
├── Procfile                # Production process declaration for cloud hosting
├── static/
│   ├── css/
│   │   └── style.css       # Custom styling and print layout rules
│   ├── img/                # Institutional branding assets
│   └── js/
│       └── app.js          # Frontend state management, timetable rendering, CSV & PDF export
└── templates/
    └── index.html          # Main web dashboard interface
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
   Navigate to `http://127.0.0.1:5000`. The application automatically initializes `timetable.db` with the default Monsoon 2026 dataset on first launch.

---

## Cloud Deployment (Render)

1. Connect your GitHub repository to a new **Web Service** on [Render](https://render.com).
2. Configure the service settings:
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app` *(or `gunicorn --chdir <subfolder> app:app` if nested inside a subdirectory)*
3. Deploy the service to obtain your live public URL.

---

## Tech Stack

- **Backend:** Python 3, Flask, Gunicorn
- **Database:** SQLite3
- **Frontend:** HTML5, CSS3, Tailwind CSS, Vanilla JavaScript
- **AI / Algorithms:** Constraint Satisfaction Problem (CSP), Backtracking Search, Forward Checking, MRV Heuristic, Min-Conflicts Local Search