import time
import random
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple
from models import Room, ClassSession, Timeslot, Assignment, normalize


class SearchTimeout(Exception):
    pass


class ClassTimetableCSP:
    def __init__(self, sessions: List[ClassSession], rooms: List[Room], timeslots: List[Timeslot]):
        self.sessions = sessions
        self.rooms = rooms
        self.timeslots = timeslots

        # Build domains D(c) = Timeslots x Rooms filtered by static unary constraints
        self.domains: Dict[ClassSession, List[Assignment]] = {}
        for session in self.sessions:
            valid_domain = []
            for slot in timeslots:
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
                or (a.course_id and a.course_id == b.course_id))

    def conflicts(self, a: ClassSession, a_val: Assignment, b: ClassSession, b_val: Assignment) -> bool:
        """True if the two placements violate a hard binary constraint."""
        a_slot, a_room = a_val
        b_slot, b_room = b_val
        # 4. Meetings of the same course go on different days
        if a.course_id and a.course_id == b.course_id and a_slot.day == b_slot.day:
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
    def __init__(self, csp: ClassTimetableCSP, time_limit_s: float = 5.0):
        self.csp = csp
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
        return min(unassigned, key=lambda s: (
            len(domains[s]),
            -sum(1 for n in self.csp.neighbours[s] if n not in schedule),
        ))

    def _order_domain_values(
        self, var: ClassSession, domains: Dict[ClassSession, List[Assignment]], schedule: Dict[ClassSession, Assignment]
    ) -> List[Assignment]:
        """Soft preferences: spread a cohort's classes across the week, and use the
        smallest room that fits so large halls stay free for large classes."""
        cohort_load = Counter(slot.day for s, (slot, _) in schedule.items() if s.cohort_keys & var.cohort_keys)
        return sorted(domains[var], key=lambda v: (
            cohort_load[v[0].day],
            v[1].capacity - var.students_count,
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
    def explain_static_impossibility(session: ClassSession, rooms: List[Room]) -> List[str]:
        reasons = []
        suitable_capacity = [r for r in rooms if r.capacity >= session.students_count]
        if not suitable_capacity:
            reasons.append(
                f"Course '{session.course_code}' ({session.name}): Enrolled count ({session.students_count}) exceeds all room capacities."
            )
        elif session.requires_lab:
            suitable_lab = [r for r in suitable_capacity if r.is_lab]
            if not suitable_lab:
                reasons.append(
                    f"Course '{session.course_code}' ({session.name}): Requires a lab, but no lab room has capacity >= {session.students_count}."
                )
        return reasons

    @staticmethod
    def max_parallel_free_slots(timeslots: List[Timeslot]) -> int:
        """Largest number of mutually non-overlapping slots in the week (greedy interval
        scheduling per day). No single cohort, instructor or room can attend more than this."""
        by_day: Dict[str, List[Timeslot]] = defaultdict(list)
        for t in timeslots:
            by_day[t.day].append(t)
        total = 0
        for slots in by_day.values():
            last_end = -1
            for t in sorted(slots, key=lambda t: t.end):
                if t.start >= last_end:
                    total += 1
                    last_end = t.end
        return total

    @classmethod
    def explain_global_impossibility(
        cls, sessions: List[ClassSession], rooms: List[Room], timeslots: List[Timeslot]
    ) -> List[str]:
        """Counting (pigeonhole) checks that prove infeasibility without searching."""
        if not rooms:
            return ["No rooms configured. Add at least one venue."]
        if not timeslots:
            return ["No timeslots configured. Add at least one weekly timeslot."]

        reasons = []
        capacity = cls.max_parallel_free_slots(timeslots)

        def check_group(label: str, members_of) -> None:
            """members_of(session) -> [(key, display name)] of the groups the session belongs to."""
            groups: Dict[str, List[ClassSession]] = defaultdict(list)
            names: Dict[str, str] = {}
            for s in sessions:
                for key, name in members_of(s):
                    groups[key].append(s)
                    names.setdefault(key, name)
            for key, members in groups.items():
                if len(members) > capacity:
                    reasons.append(
                        f"{label} '{names[key]}' has {len(members)} sessions/week "
                        f"but only {capacity} non-overlapping timeslots exist."
                    )

        check_group("Cohort", lambda s: [(normalize(c), c) for c in s.cohorts])
        check_group("Instructor", lambda s: [(s.instructor_key, s.instructor_id)])

        days_available = len({t.day for t in timeslots})
        per_course = Counter(s.course_id for s in sessions if s.course_id)
        for course_id, count in per_course.items():
            if count > days_available:
                code = next(s.course_code for s in sessions if s.course_id == course_id)
                reasons.append(
                    f"Course '{code}' meets {count} times/week, but timeslots exist on only {days_available} day(s) "
                    f"(meetings of a course must fall on different days)."
                )

        if len(sessions) > len(rooms) * capacity:
            reasons.append(
                f"{len(sessions)} sessions need placing, but {len(rooms)} room(s) x {capacity} non-overlapping slots "
                f"= {len(rooms) * capacity} places."
            )
        labs = [r for r in rooms if r.is_lab]
        lab_sessions = sum(1 for s in sessions if s.requires_lab)
        if labs and lab_sessions > len(labs) * capacity:
            reasons.append(
                f"{lab_sessions} lab sessions need placing, but {len(labs)} lab(s) x {capacity} slots "
                f"= {len(labs) * capacity} lab places."
            )
        return reasons
