import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import FrozenSet, Tuple

_TIME_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def parse_time_range(text: str) -> Tuple[int, int]:
    """Parse "09:30-11:00" into (start, end) minutes since midnight."""
    m = _TIME_RANGE.match(text or "")
    if not m:
        raise ValueError(f"Invalid time range '{text}'. Use HH:MM-HH:MM, e.g. 09:30-11:00.")
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError(f"Invalid time range '{text}'.")
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if end <= start:
        raise ValueError(f"Time range '{text}' must end after it starts.")
    return start, end


def normalize(text: str) -> str:
    """Case/whitespace-insensitive key used for instructor and cohort comparisons."""
    return " ".join((text or "").split()).lower()


@dataclass(frozen=True)
class Room:
    id: str
    capacity: int
    is_lab: bool

@dataclass(frozen=True)
class ClassSession:
    id: str             # unique per weekly meeting, e.g., "C1" or "C1#2"
    course_code: str    # e.g., "FAI"
    name: str           # e.g., "Fundamentals of AI"
    instructor_id: str  # e.g., "Dr. Amit Shukla"
    cohort_id: str      # e.g., "1MSc1", or "1MSc1, MTI" for a shared class
    students_count: int
    requires_lab: bool
    course_id: str = ""  # id of the course this meeting belongs to (courses can meet several times a week)

    @cached_property
    def instructor_key(self) -> str:
        return normalize(self.instructor_id)

    @cached_property
    def cohorts(self) -> Tuple[str, ...]:
        """A class can be shared by several cohorts, given as "1MSc1, MTI"."""
        return tuple(c.strip() for c in self.cohort_id.split(",") if c.strip())

    @cached_property
    def cohort_keys(self) -> FrozenSet[str]:
        return frozenset(normalize(c) for c in self.cohorts)

@dataclass(frozen=True)
class Timeslot:
    id: str             # e.g., "TS1"
    day: str            # e.g., "Monday"
    time: str           # e.g., "09:30-10:30"
    start: int = field(default=0, compare=False)  # minutes since midnight
    end: int = field(default=0, compare=False)

    @classmethod
    def create(cls, id: str, day: str, time: str) -> "Timeslot":
        start, end = parse_time_range(time)
        return cls(id=id, day=day, time=time.strip(), start=start, end=end)

    def overlaps(self, other: "Timeslot") -> bool:
        """Two slots clash if they are on the same day and their time ranges intersect."""
        return self.day == other.day and self.start < other.end and other.start < self.end

    def __str__(self):
        return f"{self.day} {self.time}"

Assignment = Tuple[Timeslot, Room]
