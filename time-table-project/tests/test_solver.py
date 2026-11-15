import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from app import app, initial_rooms, initial_timeslots, initial_courses, half_hour_slots
from csp_solver import ClassTimetableCSP, BacktrackingSolver, MinConflictsSolver, placements, availability_windows
from models import Room, ClassSession, Timeslot

BASE = {"rooms": initial_rooms, "timeslots": initial_timeslots, "courses": initial_courses}
SAMPLE_MEETINGS = sum(int(c["lectureHours"] / c["lectureDuration"]) if c["lectureHours"] else 0 for c in initial_courses) + \
                  sum(int(c["labHours"] / c["labDuration"]) if c["labHours"] else 0 for c in initial_courses)


def session(id, cohort="A", instructor="X", students=10, lab=False, course_id=""):
    return ClassSession(id, id, id, instructor, cohort, students, lab, course_id or id)


class TimeslotTests(unittest.TestCase):
    def test_overlap(self):
        a = Timeslot.create("1", "Monday", "09:00-11:00")
        self.assertTrue(a.overlaps(Timeslot.create("2", "Monday", "10:00-12:00")))
        self.assertFalse(a.overlaps(Timeslot.create("3", "Monday", "11:00-12:00")))  # back-to-back is fine
        self.assertFalse(a.overlaps(Timeslot.create("4", "Tuesday", "09:00-11:00")))

    def test_invalid_time(self):
        for bad in ("9-10", "11:00-10:00", "25:00-26:00", ""):
            with self.assertRaises(ValueError):
                Timeslot.create("1", "Monday", bad)


class HalfHourSlotTests(unittest.TestCase):
    def test_back_to_back_slots_merge_into_windows(self):
        slots = [Timeslot.create(str(i), "Mon", t) for i, t in enumerate(
            ["09:30-10:00", "10:00-10:30", "10:30-11:00", "11:30-12:00"])]
        self.assertEqual(availability_windows(slots), {"Mon": [(570, 660), (690, 720)]})

    def test_long_session_needs_continuous_block(self):
        slots = [Timeslot.create(str(i), "Mon", t) for i, t in enumerate(
            ["09:30-10:00", "10:00-10:30", "10:30-11:00", "11:30-12:00"])]
        self.assertEqual([p.time for p in placements(slots, 90)], ["09:30-11:00"])
        self.assertEqual([p.time for p in placements(slots, 60)], ["09:30-10:30", "10:00-11:00"])
        self.assertEqual(placements(slots, 120), [])

    def test_half_hour_slot_generator(self):
        slots = half_hour_slots(["Monday"], [("09:30", "11:00")])
        self.assertEqual([s["time"] for s in slots], ["09:30-10:00", "10:00-10:30", "10:30-11:00"])

    def test_lecture_and_lab_of_same_course_may_share_a_day(self):
        slots = [Timeslot.create(str(i), "Mon", f"{h:02d}:{m:02d}-{h + (m + 30) // 60:02d}:{(m + 30) % 60:02d}")
                 for i, (h, m) in enumerate((9 + k // 2, 30 * (k % 2)) for k in range(8))]
        lec = ClassSession("L", "A", "A", "X", "C", 10, False, "A", kind="lecture", duration=60)
        lab = ClassSession("P", "A", "A", "X", "C", 10, True, "A", kind="lab", duration=120)
        csp = ClassTimetableCSP([lec, lab], [Room("R", 50, False), Room("LAB", 50, True)], slots)
        result, _ = BacktrackingSolver(csp).solve()
        self.assertIsNotNone(result)
        a, b = result[lec][0], result[lab][0]
        self.assertFalse(a.overlaps(b))


class SharedCohortTests(unittest.TestCase):
    def test_shared_class_blocks_both_cohorts(self):
        slot = [Timeslot.create("1", "Mon", "09:00-10:00")]
        shared = ClassSession("s", "S", "S", "X", "A, B", 10, False, "S")
        only_b = ClassSession("b", "B", "B", "Y", "b", 10, False, "B")  # cohort names are case-insensitive
        csp = ClassTimetableCSP([shared, only_b], [Room("R1", 50, False), Room("R2", 50, False)], slot)
        self.assertIsNone(BacktrackingSolver(csp).solve()[0])


class SolverTests(unittest.TestCase):
    def assert_valid(self, csp, schedule):
        self.assertEqual(len(schedule), len(csp.sessions))
        items = list(schedule.items())
        for i, (a, av) in enumerate(items):
            self.assertIn(av, csp.domains[a])
            for b, bv in items[i + 1:]:
                self.assertFalse(csp.conflicts(a, av, b, bv), f"{a.id} clashes with {b.id}")

    def test_overlapping_slots_are_respected(self):
        slots = [Timeslot.create("1", "Mon", "09:00-11:00"), Timeslot.create("2", "Mon", "10:00-12:00"),
                 Timeslot.create("3", "Mon", "11:00-12:00")]
        csp = ClassTimetableCSP([session("a"), session("b")], [Room("R", 50, False)], slots)
        result, _ = BacktrackingSolver(csp).solve()
        self.assert_valid(csp, result)
        self.assertEqual({v[0].id for v in result.values()} & {"1", "3"}, {"1", "3"})

    def test_best_fit_room(self):
        rooms = [Room("Big", 200, False), Room("Small", 20, False)]
        csp = ClassTimetableCSP([session("a", students=15)], rooms, [Timeslot.create("1", "Mon", "09:00-10:00")])
        result, _ = BacktrackingSolver(csp).solve()
        self.assertEqual(next(iter(result.values()))[1].id, "Small")

    def test_same_course_different_days(self):
        slots = [Timeslot.create(str(i), d, t) for i, (d, t) in enumerate(
            [("Mon", "09:00-10:00"), ("Mon", "10:00-11:00"), ("Tue", "09:00-10:00")])]
        sessions = [session("a1", course_id="A"), session("a2", course_id="A")]
        csp = ClassTimetableCSP(sessions, [Room("R", 50, False)], slots)
        result, _ = BacktrackingSolver(csp).solve()
        self.assert_valid(csp, result)
        self.assertEqual({v[0].day for v in result.values()}, {"Mon", "Tue"})

    def test_infeasible_returns_none(self):
        csp = ClassTimetableCSP([session("a"), session("b")], [Room("R", 50, False)],
                                [Timeslot.create("1", "Mon", "09:00-10:00")])
        solver = BacktrackingSolver(csp)
        self.assertIsNone(solver.solve()[0])
        self.assertFalse(solver.timed_out)

    def test_min_conflicts_finds_valid_schedule(self):
        slots = [Timeslot.create(str(i), "Mon", f"{8 + i:02d}:00-{9 + i:02d}:00") for i in range(6)]
        sessions = [session(f"s{i}", cohort=f"C{i % 3}", instructor=f"I{i % 2}") for i in range(6)]
        csp = ClassTimetableCSP(sessions, [Room("R1", 50, False), Room("R2", 50, False)], slots)
        result, _ = MinConflictsSolver(csp, seed=1).solve()
        self.assert_valid(csp, result)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_sample_data_solves(self):
        r = self.client.post("/api/solve", json=BASE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json["schedule"]), SAMPLE_MEETINGS)

    def test_duplicate_course_ids_are_not_lost(self):
        courses = [dict(c, id="C1") for c in initial_courses]
        r = self.client.post("/api/solve", json=dict(BASE, courses=courses))
        self.assertEqual(len(r.json["schedule"]), SAMPLE_MEETINGS)

    def test_old_style_sessions_per_week_still_accepted(self):
        old = [{k: v for k, v in c.items() if k not in ("lectureDuration", "lectureHours", "labDuration", "labHours")}
               for c in initial_courses]
        courses = [dict(c, sessionsPerWeek=2, requiresLab=c["code"] in ("FML", "DBMS")) for c in old]
        r = self.client.post("/api/solve", json=dict(BASE, courses=courses))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json["schedule"]), 2 * len(initial_courses))
        self.assertTrue(all(v["durationMin"] == 60 for v in r.json["schedule"].values()))

    def test_lecture_and_practical_hours(self):
        rooms = [{"id": "R1", "capacity": 50}, {"id": "LAB", "capacity": 50, "is_lab": True}]
        course = {"code": "FML", "instructor": "X", "cohort": "A", "students": 30,
                  "lectureDuration": 1.5, "lectureHours": 3, "labDuration": 2, "labHours": 2}
        r = self.client.post("/api/solve", json={"rooms": rooms, "timeslots": initial_timeslots, "courses": [course]})
        self.assertEqual(r.status_code, 200)
        sched = list(r.json["schedule"].values())
        lectures = [v for v in sched if v["kind"] == "lecture"]
        labs = [v for v in sched if v["kind"] == "lab"]
        self.assertEqual(len(lectures), 2)
        self.assertEqual(len(labs), 1)
        self.assertTrue(all(v["durationMin"] == 90 and v["room"]["id"] == "R1" for v in lectures))
        self.assertEqual(labs[0]["durationMin"], 120)
        self.assertEqual(labs[0]["room"]["id"], "LAB")
        self.assertNotEqual(lectures[0]["slot"]["day"], lectures[1]["slot"]["day"])
        # Nothing may run through the 13:00-14:00 lunch gap the sample slots leave free
        for v in sched:
            self.assertTrue(v["slot"]["end"] <= 13 * 60 or v["slot"]["start"] >= 14 * 60, v["slot"])

    def test_lecture_and_practical_on_different_days_and_runs_vary(self):
        layouts = set()
        for _ in range(5):
            r = self.client.post("/api/solve", json=BASE)
            self.assertEqual(r.status_code, 200)
            checks = r.json["stats"]["checks"]
            self.assertTrue(all(not c["issues"] for c in checks), checks)
            for c in checks:
                if c["lecture"]["meetings"] and c["lab"]["meetings"]:
                    self.assertFalse(set(c["lecture"]["days"]) & set(c["lab"]["days"]), c)
                self.assertEqual(c["lecture"]["scheduled"], c["lecture"]["required"])
            layouts.add(tuple(sorted((k, v["slot"]["day"], v["slot"]["time"]) for k, v in r.json["schedule"].items())))
        self.assertGreater(len(layouts), 1)

    def test_same_seed_same_timetable(self):
        a = self.client.post("/api/solve", json=dict(BASE, seed=42)).json
        b = self.client.post("/api/solve", json=dict(BASE, seed=42)).json
        self.assertEqual(a["stats"]["seed"], 42)
        self.assertEqual({k: v["slot"] for k, v in a["schedule"].items()}, {k: v["slot"] for k, v in b["schedule"].items()})

    def test_hours_must_split_evenly(self):
        bad = dict(initial_courses[0], lectureDuration=1.5, lectureHours=4)
        r = self.client.post("/api/solve", json=dict(BASE, courses=[bad]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("multiple", r.json["diagnostics"][0])
        for fields in ({"lectureHours": 0, "labHours": 0}, {"lectureHours": 1.25}, {"lectureDuration": 0}):
            r = self.client.post("/api/solve", json=dict(BASE, courses=[dict(initial_courses[0], **fields)]))
            self.assertEqual(r.status_code, 400, fields)

    def test_block_too_long_for_any_window(self):
        course = dict(initial_courses[0], lectureDuration=4, lectureHours=4)  # windows are only 3.5 h long
        r = self.client.post("/api/solve", json=dict(BASE, courses=[course]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("continuous 4 h block", r.json["diagnostics"][0])

    def test_pigeonhole_is_reported_immediately(self):
        weekly_hours = len(initial_timeslots) / 2
        n = int(weekly_hours // 3) + 1  # each copy of FAI needs 3 h from the same cohort
        courses = [dict(initial_courses[0], instructor=f"I{i}") for i in range(n)]
        r = self.client.post("/api/solve", json=dict(BASE, courses=courses))
        self.assertEqual(r.status_code, 400)
        self.assertIn("timeslots only cover", r.json["diagnostics"][0])

    def test_bad_input_returns_400(self):
        self.assertEqual(self.client.post("/api/solve", data="x", content_type="text/plain").status_code, 400)
        self.assertEqual(self.client.post("/api/solve", json=dict(BASE, courses=[{"id": "C1"}])).status_code, 400)
        r = self.client.post("/api/solve", json=dict(BASE, timeslots=[{"day": "Monday", "time": "9-10"}]))
        self.assertEqual(r.status_code, 400)

    def test_shared_cohort_class_clashes_with_each_cohort(self):
        rooms = [{"id": "R1", "capacity": 50}, {"id": "R2", "capacity": 50}]
        slot = [{"day": "Monday", "time": "09:30-11:00"}]
        courses = [{"code": "A", "instructor": "X", "cohorts": ["1MSc1", "MTI"], "students": 30},
                   {"code": "B", "instructor": "Y", "cohort": "MTI", "students": 30}]
        r = self.client.post("/api/solve", json={"rooms": rooms, "timeslots": slot, "courses": courses})
        self.assertEqual(r.status_code, 400)
        self.assertIn("MTI", r.json["diagnostics"][0])

        r = self.client.post("/api/solve", json={"rooms": rooms, "timeslots": slot + [{"day": "Tuesday", "time": "09:30-11:00"}], "courses": courses})
        self.assertEqual(r.status_code, 200)
        days = {v["courseCode"]: v["slot"]["day"] for v in r.json["schedule"].values()}
        self.assertNotEqual(days["A"], days["B"])
        self.assertEqual(next(v["cohorts"] for v in r.json["schedule"].values() if v["courseCode"] == "A"), ["1MSc1", "MTI"])

    def test_course_needs_a_cohort(self):
        courses = [dict(initial_courses[0], cohort="", cohorts=[])]
        self.assertEqual(self.client.post("/api/solve", json=dict(BASE, courses=courses)).status_code, 400)

    def test_old_database_is_migrated(self):
        import sqlite3, tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE courses (id TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT, instructor TEXT NOT NULL,
                cohort TEXT NOT NULL, students INTEGER NOT NULL, requires_lab INTEGER NOT NULL DEFAULT 0,
                sessions_per_week INTEGER NOT NULL DEFAULT 1);
            INSERT INTO courses VALUES ('C1', 'QML', 'Q ML', 'X', 'A', 50, 0, 3), ('C2', 'DB', 'DB', 'Y', 'A', 30, 1, 1);
        """)
        conn.commit()
        conn.close()
        old_path = database.DB_PATH
        database.DB_PATH = path
        try:
            database.init_db([], [], [])
            courses = {c["code"]: c for c in database.load_state()["courses"]}
        finally:
            database.DB_PATH = old_path
        self.assertEqual((courses["QML"]["lectureDuration"], courses["QML"]["lectureHours"], courses["QML"]["labHours"]), (1, 3, 0))
        self.assertEqual((courses["DB"]["labDuration"], courses["DB"]["labHours"], courses["DB"]["lectureHours"]), (1, 1, 0))

    def test_no_timeslots_message(self):
        r = self.client.post("/api/solve", json=dict(BASE, timeslots=[]))
        self.assertIn("No timeslots", r.json["diagnostics"][0])


if __name__ == "__main__":
    unittest.main()
