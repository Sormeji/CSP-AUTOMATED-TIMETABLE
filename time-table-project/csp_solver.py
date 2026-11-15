import time
import random
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple
from models import Room, ClassSession, Timeslot, Assignment, normalize, format_range, format_hours

STEP_MINUTES = 30  # sessions may start on any half-hour inside an available window


class SearchTimeout(Exception):
    pass


def availability_windows(timeslots: List[Timeslot]) -> Dict[str, List[Tuple[int, int]]]:
    """Merge each day's timeslots into continuous windows. Back-to-back 30-minute slots
    09:30-10:00, 10:00-10:30, 10:30-11:00 become one window 09:30-11:00."""
    by_day: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for t in sorted(timeslots, key=lambda t: (t.start, t.end)):
        windows = by_day[t.day]
        if windows and t.start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], t.end))
        else:
            windows.append((t.start, t.end))
    return dict(by_day)


def placements(timeslots: List[Timeslot], duration: int) -> List[Timeslot]:
    """Every (day, start, end) a session can occupy.

    duration == 0 keeps the classic behaviour: the session takes one given timeslot as-is.
    Otherwise the session needs `duration` continuous minutes inside one window, and may
    start at any half-hour step of the window or at the start of any given slot."""
    if duration <= 0:
        return list(timeslots)
    starts_by_day: Dict[str, set] = defaultdict(set)
    for t in timeslots:
        starts_by_day[t.day].add(t.start)
    result: List[Timeslot] = []
    day_order = list(dict.fromkeys(t.day for t in timeslots))
    windows = availability_windows(timeslots)
    for day in day_order:
        candidates = set(starts_by_day[day])
        for w_start, w_end in windows[day]:
            candidates.update(range(w_start, w_end, STEP_MINUTES))
        for start in sorted(candidates):
            end = start + duration
            if any(w_start <= start and end <= w_end for w_start, w_end in windows[day]):
                time_text = format_range(start, end)
                result.append(Timeslot(id=f"{day} {time_text}", day=day, time=time_text, start=start, end=end))
    return result


class ClassTimetableCSP:
    def __init__(self, sessions: List[ClassSession], rooms: List[Room], timeslots: List[Timeslot]):
        self.sessions = sessions
        self.rooms = rooms
        self.timeslots = timeslots

        # Build domains D(c) = Placements(duration) x Rooms filtered by static unary constraints
        placement_cache: Dict[int, List[Timeslot]] = {}
        self.domains: Dict[ClassSession, List[Assignment]] = {}
        for session in self.sessions:
            if session.duration not in placement_cache:
                placement_cache[session.duration] = placements(timeslots, session.duration)
            valid_domain = []
            for slot in placement_cache[session.duration]:
                for room in rooms:
                    # Capacity match and Lab match checks
                    if room.capacity >= session.students_count and (not session.requires_lab or room.is_lab):
                        valid_domain.append((slot, room))
            self.domains[session] = valid_domain

        # Constraint graph: sessions that share an instructor, cohort or course can never overlap,
        # so they are each other's neighbours. Used by the degree heuristic.
        self.neighbours: Dict[ClassSession, List[ClassSession]] = {s: [] for s in sessions}
        for i, a in enumerate(sessions):
            for b in sessions[i + 1:]:
                if self._related(a, b):
                    self.neighbours[a].append(b)
                    self.neighbours[b].append(a)

    @staticmethod
    def _related(a: ClassSession, b: ClassSession) -> bool:
        return (a.instructor_key == b.instructor_key
                or a.cohort_keys & b.cohort_keys
                or (a.course_id and a.group_key == b.group_key))

    def conflicts(self, a: ClassSession, a_val: Assignment, b: ClassSession, b_val: Assignment) -> bool:
        """True if the two placements violate a hard binary constraint."""
        a_slot, a_room = a_val
        b_slot, b_room = b_val
        # 4. Meetings of the same course and kind (two lectures, or two practicals) go on different days
        if a.course_id and a.group_key == b.group_key and a_slot.day == b_slot.day:
            return True
        if not a_slot.overlaps(b_slot):
            return False
        # 1. Room Double-Booking  2. Faculty Clash  3. Student Cohort Clash
        return (a_room.id == b_room.id
                or a.instructor_key == b.instructor_key
                or a.cohort_keys & b.cohort_keys)

    def is_consistent(self, session: ClassSession, assignment: Assignment, schedule: Dict[ClassSession, Assignment]) -> bool:
        """Hard constraint evaluator."""
        return not any(
            self.conflicts(session, assignment, other, other_val)
            for other, other_val in schedule.items() if other is not session
        )


class BacktrackingSolver:
    def __init__(self, csp: ClassTimetableCSP, time_limit_s: float = 5.0, seed: Optional[int] = None):
        self.csp = csp
        # seed=None keeps the search deterministic; any number shuffles ties so each run
        # gives a different (equally valid) timetable.
        self.rng = random.Random(seed) if seed is not None else None
        self.time_limit_s = time_limit_s
        self.backtracks = 0
        self.timed_out = False
        self._deadline = 0.0

    def solve(self) -> Tuple[Optional[Dict[ClassSession, Assignment]], float]:
        start_time = time.perf_counter()
        self._deadline = start_time + self.time_limit_s
        try:
            result = self._backtrack({}, dict(self.csp.domains))
        except SearchTimeout:
            self.timed_out = True
            result = None
        execution_time_ms = (time.perf_counter() - start_time) * 1000.0
        return result, execution_time_ms

    def _select_unassigned_variable(
        self, schedule: Dict[ClassSession, Assignment], domains: Dict[ClassSession, List[Assignment]]
    ) -> ClassSession:
        """Minimum Remaining Values (MRV), ties broken by the Degree heuristic."""
        unassigned = [s for s in self.csp.sessions if s not in schedule]
        tie = {s: self.rng.random() for s in unassigned} if self.rng else {}
        return min(unassigned, key=lambda s: (
            len(domains[s]),
            -sum(1 for n in self.csp.neighbours[s] if n not in schedule),
            tie.get(s, 0),
        ))

    def _order_domain_values(
        self, var: ClassSession, domains: Dict[ClassSession, List[Assignment]], schedule: Dict[ClassSession, Assignment]
    ) -> List[Assignment]:
        """Soft preferences: spread a cohort's classes across the week, and use the
        smallest room that fits so large halls stay free for large classes;
        lectures avoid lab rooms when a classroom is free."""
        cohort_load = Counter(slot.day for s, (slot, _) in schedule.items() if s.cohort_keys & var.cohort_keys)
        # Days that already hold any meeting of this course (e.g. its lecture when placing its practical)
        course_days = {slot.day for s, (slot, _) in schedule.items() if var.course_id and s.course_id == var.course_id}
        rng = self.rng
        return sorted(domains[var], key=lambda v: (
            v[0].day in course_days,  # lecture and practical of a course on different days
            cohort_load[v[0].day],
            not var.requires_lab and v[1].is_lab,  # keep labs free for practicals
            v[1].capacity - var.students_count,
            rng.random() if rng else v[0].start % STEP_MINUTES != 0,
        ))

    def _forward_check(
        self,
        assigned_session: ClassSession,
        assignment: Assignment,
        domains: Dict[ClassSession, List[Assignment]],
        schedule: Dict[ClassSession, Assignment]
    ) -> Optional[Dict[ClassSession, List[Assignment]]]:
        """Prunes domains of remaining unassigned variables."""
        new_domains = dict(domains)  # domain lists are replaced, never mutated, so a shallow copy suffices

        for unassigned in self.csp.sessions:
            if unassigned in schedule:
                continue

            pruned_domain = [
                value for value in new_domains[unassigned]
                if not self.csp.conflicts(unassigned, value, assigned_session, assignment)
            ]
            if not pruned_domain:
                return None  # Domain wipeout detected

            new_domains[unassigned] = pruned_domain

        return new_domains

    def _backtrack(
        self, schedule: Dict[ClassSession, Assignment], domains: Dict[ClassSession, List[Assignment]]
    ) -> Optional[Dict[ClassSession, Assignment]]:
        if len(schedule) == len(self.csp.sessions):
            return dict(schedule)
        if time.perf_counter() > self._deadline:
            raise SearchTimeout()

        var = self._select_unassigned_variable(schedule, domains)

        for value in self._order_domain_values(var, domains, schedule):
            # Forward checking keeps every remaining value consistent with the schedule
            schedule[var] = value
            pruned_domains = self._forward_check(var, value, domains, schedule)
            if pruned_domains is not None:
                result = self._backtrack(schedule, pruned_domains)
                if result is not None:
                    return result

            # Undo assignment (Backtrack)
            del schedule[var]
            self.backtracks += 1

        return None


class MinConflictsSolver:
    """Local search fallback for instances where systematic search runs out of time."""

    def __init__(self, csp: ClassTimetableCSP, max_steps: int = 5000, time_limit_s: float = 3.0, seed: Optional[int] = None):
        self.csp = csp
        self.max_steps = max_steps
        self.time_limit_s = time_limit_s
        self.rng = random.Random(seed)

    def _count_conflicts(self, session: ClassSession, assignment: Assignment, schedule: Dict[ClassSession, Assignment]) -> int:
        return sum(
            1 for other, other_val in schedule.items()
            if other is not session and self.csp.conflicts(session, assignment, other, other_val)
        )

    def solve(self) -> Tuple[Optional[Dict[ClassSession, Assignment]], int]:
        deadline = time.perf_counter() + self.time_limit_s
        current_schedule: Dict[ClassSession, Assignment] = {}
        for session in self.csp.sessions:
            if not self.csp.domains[session]:
                return None, 0
            current_schedule[session] = self.rng.choice(self.csp.domains[session])

        for step in range(self.max_steps):
            conflicted_sessions = [
                s for s in self.csp.sessions
                if self._count_conflicts(s, current_schedule[s], current_schedule) > 0
            ]

            if not conflicted_sessions:
                return current_schedule, step
            if time.perf_counter() > deadline:
                break

            session = self.rng.choice(conflicted_sessions)
            scored = [(self._count_conflicts(session, v, current_schedule), v) for v in self.csp.domains[session]]
            min_conflicts = min(c for c, _ in scored)
            # Random tie-breaking avoids cycling between equally good values
            current_schedule[session] = self.rng.choice([v for c, v in scored if c == min_conflicts])

        return None, self.max_steps


class ConflictExplainer:
    @staticmethod
    def _label(session: ClassSession) -> str:
        kind = {"lecture": " lecture", "lab": " practical"}.get(session.kind, "")
        return f"Course '{session.course_code}' ({session.name}){kind}"

    @classmethod
    def explain_static_impossibility(
        cls, session: ClassSession, rooms: List[Room], timeslots: Optional[List[Timeslot]] = None
    ) -> List[str]:
        reasons = []
        suitable_capacity = [r for r in rooms if r.capacity >= session.students_count]
        if not suitable_capacity:
            reasons.append(
                f"{cls._label(session)}: Enrolled count ({session.students_count}) exceeds all room capacities."
            )
        elif session.requires_lab and not any(r.is_lab for r in suitable_capacity):
            reasons.append(
                f"{cls._label(session)}: Requires a lab, but no lab room has capacity >= {session.students_count}."
            )
        elif timeslots and session.duration and not placements(timeslots, session.duration):
            longest = max((e - s for ws in availability_windows(timeslots).values() for s, e in ws), default=0)
            reasons.append(
                f"{cls._label(session)}: needs a continuous {format_hours(session.duration)} block, but the longest "
                f"run of back-to-back timeslots is only {format_hours(longest)}."
            )
        return reasons

    @staticmethod
    def weekly_minutes(timeslots: List[Timeslot]) -> int:
        """Total time covered by timeslots in the week (overlaps counted once)."""
        return sum(e - s for ws in availability_windows(timeslots).values() for s, e in ws)

    @classmethod
    def explain_global_impossibility(
        cls, sessions: List[ClassSession], rooms: List[Room], timeslots: List[Timeslot]
    ) -> List[str]:
        """Counting (pigeonhole) checks that prove infeasibility without searching.

        A cohort, instructor or room can't be in two places at once, so the hours it must
        spend in class can't exceed the hours the timeslots cover."""
        if not rooms:
            return ["No rooms configured. Add at least one venue."]
        if not timeslots:
            return ["No timeslots configured. Add at least one weekly timeslot."]

        reasons = []
        available = cls.weekly_minutes(timeslots)
        shortest_slot = min(t.minutes for t in timeslots)

        def need(s: ClassSession) -> int:
            # A whole-slot session takes at least the shortest slot.
            return s.duration or shortest_slot

        def check_group(label: str, members_of) -> None:
            """members_of(session) -> [(key, display name)] of the groups the session belongs to."""
            load: Dict[str, int] = defaultdict(int)
            names: Dict[str, str] = {}
            for s in sessions:
                for key, name in members_of(s):
                    load[key] += need(s)
                    names.setdefault(key, name)
            for key, minutes in load.items():
                if minutes > available:
                    reasons.append(
                        f"{label} '{names[key]}' needs {format_hours(minutes)}/week of classes, "
                        f"but the timeslots only cover {format_hours(available)}/week."
                    )

        check_group("Cohort", lambda s: [(normalize(c), c) for c in s.cohorts])
        check_group("Instructor", lambda s: [(s.instructor_key, s.instructor_id)])

        groups: Dict[Tuple[str, str], List[ClassSession]] = defaultdict(list)
        for s in sessions:
            if s.course_id:
                groups[s.group_key].append(s)
        for members in groups.values():
            first = members[0]
            days = {p.day for p in placements(timeslots, first.duration)}
            if len(members) > len(days) and days:
                what = {"lecture": "lectures", "lab": "practicals"}.get(first.kind, "meetings")
                reasons.append(
                    f"Course '{first.course_code}' has {len(members)} {what}/week, but only {len(days)} day(s) "
                    f"have room for a {format_hours(need(first))} block ({what} of a course must fall on different days)."
                )

        total = sum(need(s) for s in sessions)
        if total > len(rooms) * available:
            reasons.append(
                f"Classes need {format_hours(total)}/week of room time, but {len(rooms)} room(s) x "
                f"{format_hours(available)} = {format_hours(len(rooms) * available)}."
            )
        labs = [r for r in rooms if r.is_lab]
        lab_total = sum(need(s) for s in sessions if s.requires_lab)
        if labs and lab_total > len(labs) * available:
            reasons.append(
                f"Practicals need {format_hours(lab_total)}/week of lab time, but {len(labs)} lab(s) x "
                f"{format_hours(available)} = {format_hours(len(labs) * available)}."
            )
        return reasons
