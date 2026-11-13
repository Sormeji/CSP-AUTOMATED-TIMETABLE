let rooms = [];
let timeslots = [];
let courses = [];
let currentSchedule = null;
let nextCourseId = 1;

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const DEFAULT_COHORTS = ["1MSc1", "MTI", "IMT3", "MSc3", "MCA3", "PhD", "MT3", "MCA1", "MSc1/IMTI"];
const LUNCH = { start: 13 * 60, end: 14 * 60, label: "13:00-14:00" };

const TIME_OPTIONS = Array.from({ length: 21 }, (_, i) => {
    const minutes = 8 * 60 + i * 30;
    return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
});

// Load Initial Dataset on Startup
document.addEventListener("DOMContentLoaded", async () => {
    let predefinedTimes = [];
    let savedSchedule = null;
    let savedStats = null;
    try {
        const response = await fetch('/api/initial-data');
        if (!response.ok) throw new Error("Network response was not ok");
        const data = await response.json();
        rooms = data.rooms || [];
        timeslots = data.timeslots || [];
        courses = (data.courses || []).map(c => ({ ...c, id: "C" + nextCourseId++, cohorts: cohortsOf(c) }));
        predefinedTimes = data.predefinedTimes || [];
        savedSchedule = data.schedule || null;
        savedStats = data.stats || null;
    } catch (err) {
        console.warn("Could not load initial API dataset, starting with empty state:", err);
    }

    setupTimePickers(predefinedTimes);
    renderCohortChoices();
    renderAll();
    setupFormListeners();

    if (savedSchedule) {
        currentSchedule = savedSchedule;
        if (savedStats) {
            const statTime = document.getElementById('statTime');
            const statBacktracks = document.getElementById('statBacktracks');
            const statMethod = document.getElementById('statMethod');
            if (statTime) statTime.innerText = `${savedStats.timeMs} ms`;
            if (statBacktracks) statBacktracks.innerText = savedStats.backtracks;
            if (statMethod) statMethod.innerText = savedStats.method || 'backtracking';
            document.getElementById('statsBar')?.classList.remove('hidden');
        }
        document.getElementById('exportBtn')?.classList.remove('hidden');
        document.getElementById('exportCsvBtn')?.classList.remove('hidden');
        populateCohortFilter(savedSchedule);
        renderTimetable(savedSchedule);
    }
});

async function persistChanges() {
    try {
        await fetch('/api/save-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rooms, timeslots, courses })
        });
    } catch (err) {
        console.error("Failed to persist changes to database:", err);
    }
}

function cohortsOf(item) {
    if (Array.isArray(item.cohorts) && item.cohorts.length) return item.cohorts;
    return String(item.cohort || '').split(',').map(s => s.trim()).filter(Boolean);
}

function parseRange(time) {
    const m = /^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$/.exec(time || '');
    if (!m) return null;
    return { start: +m[1] * 60 + +m[2], end: +m[3] * 60 + +m[4] };
}

function allKnownCohorts() {
    const set = new Set(DEFAULT_COHORTS);
    courses.forEach(c => cohortsOf(c).forEach(ch => set.add(ch)));
    return [...set];
}

function renderAll() {
    renderCourses();
    renderRooms();
    renderTimeslots();
}

function setCount(id, n) {
    const el = document.getElementById(id);
    if (el) el.textContent = n;
}

function renderCohortChoices() {
    const box = document.getElementById('cohortChoices');
    if (!box) return;
    const checked = new Set([...box.querySelectorAll('input:checked')].map(cb => cb.value));
    box.innerHTML = allKnownCohorts().map(c => `
        <label class="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" name="cCohorts" value="${escapeHtml(c)}" class="checkbox" ${checked.has(c) ? 'checked' : ''}> ${escapeHtml(c)}
        </label>
    `).join('');
}

function setupTimePickers(predefinedTimes) {
    const start = document.getElementById('sStart');
    const end = document.getElementById('sEnd');
    const preset = document.getElementById('sPreset');
    if (start) start.innerHTML = TIME_OPTIONS.slice(0, -1).map(t => `<option>${t}</option>`).join('');
    if (end) end.innerHTML = TIME_OPTIONS.slice(1).map(t => `<option>${t}</option>`).join('');
    if (start) start.value = "09:30";
    if (end) end.value = "11:00";

    if (preset) {
        preset.innerHTML = `<option value="">Common times…</option>` +
            predefinedTimes.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');
        preset.addEventListener('change', () => {
            const [s, e] = preset.value.split('-');
            if (s && e && start && end) { start.value = s; end.value = e; }
        });
    }
}

function renderCourses() {
    const list = document.getElementById('courseList');
    if (!list) return;
    setCount('courseCount', courses.length);

    if (courses.length === 0) {
        list.innerHTML = `<p class="text-sm text-neutral-400 py-3">No courses added yet.</p>`;
        return;
    }

    list.innerHTML = courses.map((c, i) => `
        <div class="row-item">
            <div>
                <div><span class="font-semibold">${escapeHtml(c.code)}</span> ${escapeHtml(c.name || '')} ${c.requiresLab ? '<span class="tag ml-1">Lab</span>' : ''}</div>
                <div class="text-neutral-500 mt-0.5">${escapeHtml(c.instructor || '')} · ${escapeHtml(cohortsOf(c).join(', '))}</div>
                <div class="text-neutral-500">${c.students || 0} students · ${c.sessionsPerWeek || 1}× per week</div>
            </div>
            <button onclick="deleteCourse(${i})" class="delete-btn" aria-label="Remove course">×</button>
        </div>
    `).join('');
}

function renderRooms() {
    const list = document.getElementById('roomList');
    if (!list) return;
    setCount('roomCount', rooms.length);

    if (rooms.length === 0) {
        list.innerHTML = `<p class="text-sm text-neutral-400 py-3">No rooms added yet.</p>`;
        return;
    }

    list.innerHTML = rooms.map((r, i) => `
        <div class="row-item">
            <div>
                <div><span class="font-semibold">${escapeHtml(r.id)}</span> ${r.is_lab ? '<span class="tag ml-1">Lab</span>' : ''}</div>
                <div class="text-neutral-500 mt-0.5">${r.capacity} seats · ${r.is_lab ? 'Laboratory' : 'Lecture hall'}</div>
            </div>
            <button onclick="deleteRoom(${i})" class="delete-btn" aria-label="Remove room">×</button>
        </div>
    `).join('');
}

function renderTimeslots() {
    const list = document.getElementById('slotList');
    if (!list) return;
    setCount('slotCount', timeslots.length);

    if (timeslots.length === 0) {
        list.innerHTML = `<p class="text-sm text-neutral-400 py-3">No timeslots added yet.</p>`;
        return;
    }

    const ordered = timeslots
        .map((t, i) => ({ t, i, range: parseRange(t.time) }))
        .sort((a, b) => DAYS.indexOf(a.t.day) - DAYS.indexOf(b.t.day) || (a.range?.start ?? 0) - (b.range?.start ?? 0));

    list.innerHTML = ordered.map(({ t, i }) => `
        <div class="row-item items-center">
            <span><span class="inline-block w-24">${escapeHtml(t.day)}</span><span class="tabular-nums text-neutral-500">${escapeHtml(t.time)}</span></span>
            <button onclick="deleteSlot(${i})" class="delete-btn" aria-label="Remove timeslot">×</button>
        </div>
    `).join('');
}

function setupFormListeners() {
    const courseForm = document.getElementById('courseForm');
    if (courseForm) {
        courseForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const picked = [...document.querySelectorAll('input[name="cCohorts"]:checked')].map(cb => cb.value);
            const customInput = document.getElementById('cCustomCohort');
            const typed = customInput ? customInput.value.split(',').map(s => s.trim()).filter(Boolean) : [];
            const cohorts = [...new Set([...picked, ...typed])];
            if (cohorts.length === 0) {
                alert('Select or type at least one cohort.');
                return;
            }

            courses.push({
                id: "C" + nextCourseId++,
                code: document.getElementById('cCode').value.trim(),
                name: document.getElementById('cName').value.trim(),
                instructor: document.getElementById('cFaculty').value.trim(),
                cohorts,
                students: parseInt(document.getElementById('cStudents').value) || 0,
                sessionsPerWeek: parseInt(document.getElementById('cPerWeek')?.value) || 1,
                requiresLab: document.getElementById('cLab').checked
            });
            courseForm.reset();
            renderCohortChoices();
            renderCourses();
            markStale();
            persistChanges();
        });
    }

    const roomForm = document.getElementById('roomForm');
    if (roomForm) {
        roomForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const id = document.getElementById('rId').value.trim();
            if (rooms.some(r => r.id.toLowerCase() === id.toLowerCase())) {
                alert(`Room ${id} already exists.`);
                return;
            }
            rooms.push({
                id,
                capacity: parseInt(document.getElementById('rCap').value) || 0,
                is_lab: document.getElementById('rLab').checked
            });
            roomForm.reset();
            renderRooms();
            markStale();
            persistChanges();
        });
    }

    const slotForm = document.getElementById('slotForm');
    if (slotForm) {
        slotForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const day = document.getElementById('sDay').value;
            const start = document.getElementById('sStart').value;
            const end = document.getElementById('sEnd').value;
            if (start >= end) {
                alert('End time must be later than start time.');
                return;
            }
            const time = `${start}-${end}`;
            if (timeslots.some(t => t.day === day && t.time.replace(/\s+/g, '') === time)) {
                alert(`${day} ${time} already exists.`);
                return;
            }
            timeslots.push({ day, time });
            renderTimeslots();
            markStale();
            persistChanges();
        });
    }
}

function deleteCourse(i) { courses.splice(i, 1); renderCourses(); markStale(); persistChanges(); }
function deleteRoom(i) { rooms.splice(i, 1); renderRooms(); markStale(); persistChanges(); }
function deleteSlot(i) { timeslots.splice(i, 1); renderTimeslots(); markStale(); persistChanges(); }

function markStale() {
    if (currentSchedule) document.getElementById('staleNotice')?.classList.remove('hidden');
}

function switchTab(tab) {
    const tabInput = document.getElementById('tabInput');
    const tabOutput = document.getElementById('tabOutput');
    const viewInput = document.getElementById('viewInput');
    const viewOutput = document.getElementById('viewOutput');

    if (!tabInput || !tabOutput || !viewInput || !viewOutput) return;

    tabInput.classList.toggle('tab-active', tab === 'input');
    tabOutput.classList.toggle('tab-active', tab !== 'input');
    viewInput.classList.toggle('hidden', tab !== 'input');
    viewOutput.classList.toggle('hidden', tab === 'input');
}

async function runSolver() {
    const diagContainer = document.getElementById('diagnosticContainer');
    const diagList = document.getElementById('diagnosticList');
    const solveBtn = document.getElementById('solveBtn');
    if (diagContainer) diagContainer.classList.add('hidden');
    if (diagList) diagList.innerHTML = '';

    const showDiagnostics = (errors) => {
        if (diagContainer) diagContainer.classList.remove('hidden');
        if (diagList) diagList.innerHTML = errors.map(d => `<p>• ${escapeHtml(d)}</p>`).join('');
    };

    if (solveBtn) { solveBtn.disabled = true; solveBtn.textContent = 'Generating…'; }
    try {
        const response = await fetch('/api/solve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rooms, timeslots, courses })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            currentSchedule = data.schedule;
            document.getElementById('statTime').innerText = `${data.stats.timeMs} ms`;
            document.getElementById('statBacktracks').innerText = data.stats.backtracks;
            const statMethod = document.getElementById('statMethod');
            if (statMethod) statMethod.innerText = data.stats.method || 'backtracking';
            document.getElementById('statsBar')?.classList.remove('hidden');
            document.getElementById('exportBtn')?.classList.remove('hidden');
            document.getElementById('exportCsvBtn')?.classList.remove('hidden');
            document.getElementById('staleNotice')?.classList.add('hidden');

            populateCohortFilter(data.schedule);
            renderTimetable(data.schedule);
            switchTab('output');
        } else {
            showDiagnostics(data.diagnostics?.length ? data.diagnostics : [data.message || "Constraint satisfaction failed."]);
        }
    } catch (err) {
        console.error("CSP Solver Error:", err);
        showDiagnostics(["Error contacting backend Flask CSP server. Make sure Python app is running."]);
    } finally {
        if (solveBtn) { solveBtn.disabled = false; solveBtn.textContent = 'Generate schedule'; }
    }
}

function scheduledCohorts(schedule) {
    const used = new Set();
    Object.values(schedule || {}).forEach(item => cohortsOf(item).forEach(c => used.add(c)));
    return allKnownCohorts().filter(c => used.has(c)).concat([...used].filter(c => !allKnownCohorts().includes(c)));
}

function populateCohortFilter(schedule) {
    const select = document.getElementById('cohortFilter');
    if (!select) return;
    const previous = select.value;
    const cohorts = scheduledCohorts(schedule);
    select.innerHTML = `<option value="">All cohorts</option>` +
        cohorts.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    if (cohorts.includes(previous)) select.value = previous;
}

function buildTimetableHTML(schedule) {
    const items = Object.values(schedule || {});
    const filter = document.getElementById('cohortFilter')?.value || '';
    const columns = filter ? [filter] : scheduledCohorts(schedule);
    const visible = items.filter(item => cohortsOf(item).some(c => columns.includes(c)));

    let html = '';
    DAYS.forEach(day => {
        const dayItems = visible.filter(item => item.slot?.day === day);
        if (dayItems.length === 0) return;

        const rows = new Map();
        timeslots.filter(t => t.day === day).forEach(t => {
            const r = parseRange(t.time);
            if (r) rows.set(`${r.start}-${r.end}`, { ...r, label: t.time.replace(/\s+/g, '') });
        });
        dayItems.forEach(item => {
            const r = parseRange(item.slot.time);
            if (r) rows.set(`${r.start}-${r.end}`, { ...r, label: item.slot.time.replace(/\s+/g, '') });
        });
        const sorted = [...rows.values()].sort((a, b) => a.start - b.start || a.end - b.end);

        const lunchFree = !sorted.some(r => r.start < LUNCH.end && LUNCH.start < r.end);
        const lunchAt = sorted.findIndex(r => r.start >= LUNCH.end);
        if (lunchFree && lunchAt > 0) sorted.splice(lunchAt, 0, { lunch: true });

        html += `
            <section class="tt-day">
                <h3 class="serif text-xl font-semibold mb-2">${day}</h3>
                <div class="overflow-x-auto">
                    <table class="tt-grid" style="min-width: ${7 + columns.length * 8}rem">
                        <thead><tr><th class="tt-time">Time</th>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                        <tbody>
                            ${sorted.map(row => row.lunch ? `
                                <tr class="tt-lunch"><td class="tt-time">${LUNCH.label}</td><td colspan="${columns.length}">Lunch break</td></tr>
                            ` : `
                                <tr>
                                    <td class="tt-time">${escapeHtml(row.label)}</td>
                                    ${columns.map(cohort => {
                                        const here = dayItems.filter(item => {
                                            const r = parseRange(item.slot.time);
                                            return r && r.start === row.start && r.end === row.end && cohortsOf(item).includes(cohort);
                                        });
                                        if (here.length === 0) return `<td class="tt-empty">–</td>`;
                                        return `<td>${here.map(item => `
                                            <div class="tt-class">
                                                <div class="flex justify-between items-start gap-2">
                                                    <span class="font-bold">${escapeHtml(item.courseCode)}</span>
                                                    <span class="tag">${item.requiresLab ? 'Practical' : 'Lecture'}</span>
                                                </div>
                                                <div class="tt-name">${escapeHtml(item.courseName || '')}</div>
                                                <div class="tt-meta">${escapeHtml(item.room?.id || '')} · ${escapeHtml(item.instructor || '')}</div>
                                            </div>`).join('')}</td>`;
                                    }).join('')}
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </section>
        `;
    });

    return html || `<div class="border border-neutral-200 p-12 text-center text-sm text-neutral-500">No scheduled sessions found.</div>`;
}

function renderTimetable(schedule) {
    const container = document.getElementById('timetableContainer');
    if (!container || !schedule) return;
    container.innerHTML = buildTimetableHTML(schedule);
}

function exportHTML() {
    if (!currentSchedule) return;
    const printWindow = window.open('', '_blank');
    if (!printWindow) {
        alert('Allow pop-ups for this page to print the timetable.');
        return;
    }
    const filter = document.getElementById('cohortFilter')?.value;
    const logoEl = document.querySelector('.masthead-logo');
    const logo = logoEl
        ? new URL(logoEl.getAttribute('src'), location.href).href.replace('sau-emblem.png', 'sau-logo.png')
        : '';
    const generated = new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });

    printWindow.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Class Timetable${filter ? ' – ' + escapeHtml(filter) : ''} · South Asian University</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,600&display=swap" rel="stylesheet">
    <style>
        @page { size: A4 landscape; margin: 14mm; }
        * { box-sizing: border-box; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
        body {
            margin: 24px;
            background: #fff;
            color: #000;
            font-family: "Inter", ui-sans-serif, system-ui, -apple-system, sans-serif;
            font-size: 12px;
        }
        .letterhead { display: flex; align-items: center; gap: 18px; padding-bottom: 14px; margin-bottom: 20px; border-bottom: 2px solid #000; }
        .letterhead img { height: 84px; width: auto; }
        .letterhead .rule { width: 1px; align-self: stretch; background: #000; }
        .letterhead .meta { margin-left: auto; text-align: right; font-size: 11px; color: #525252; line-height: 1.6; }
        .eyebrow { font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: #525252; }
        .masthead-sub { margin-top: 0.25rem; font-size: 0.8125rem; color: #737373; }
        h1 { font-family: "Source Serif 4", Georgia, serif; font-size: 26px; font-weight: 600; margin: 2px 0 0; }
        h3 { font-family: "Source Serif 4", Georgia, serif; font-size: 17px; font-weight: 600; margin: 0 0 8px; }
        .tt-day { break-inside: avoid; page-break-inside: avoid; }
        .tt-day + .tt-day { margin-top: 22px; }

        /* Monochrome Timetable Grid matching style.css */
        .tt-grid {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 0.75rem;
        }
        .tt-grid th,
        .tt-grid td {
            border: 1px solid #000;
            padding: 0.5rem;
            vertical-align: top;
            text-align: left;
            word-wrap: break-word;
        }
        .tt-grid th {
            font-size: 0.75rem;
            font-weight: 600;
            background: #f5f5f5;
        }
        .tt-grid .tt-time {
            width: 7rem;
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }
        .tt-grid .tt-empty { color: #a3a3a3; text-align: center; vertical-align: middle; }
        .tt-grid .tt-lunch td {
            background: #f5f5f5;
            font-size: 0.6875rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            text-align: center;
            color: #525252;
        }
        .tt-grid .tt-lunch .tt-time { text-align: left; letter-spacing: normal; color: #000; }
        .tt-class + .tt-class { margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px dashed #000; }
        .tt-name { margin-top: 0.125rem; font-weight: 500; }
        .tt-meta { margin-top: 0.25rem; color: #525252; font-size: 0.6875rem; }
        .tag { display: inline-block; padding: 0 0.375rem; font-size: 0.6875rem; font-weight: 500; border: 1px solid #000; }

        .font-bold { font-weight: 700; }
        .flex { display: flex; } .justify-between { justify-content: space-between; } .items-start { align-items: flex-start; } .gap-2 { gap: 0.5rem; }
        .print-footer { margin-top: 24px; padding-top: 10px; border-top: 1px solid #000; font-size: 10px; color: #737373; display: flex; justify-content: space-between; }
        @media print { body { margin: 0; } .tt-grid { min-width: 0 !important; } }
    </style>
</head>
<body>
    <header class="letterhead">
        ${logo ? `<img src="${logo}" alt="South Asian University"><div class="rule"></div>` : ''}
        <div>
            <div class="eyebrow">South Asian University · New Delhi</div>
            <h1>Class Timetable</h1>
            <div class="masthead-sub">Monsoon Semester 2026</div>
        </div>
        <div class="meta">
            <div><strong>${filter ? 'Cohort ' + escapeHtml(filter) : 'All cohorts'}</strong></div>
            <div>Generated ${escapeHtml(generated)}</div>
        </div>
    </header>
    ${buildTimetableHTML(currentSchedule)}
    <footer class="print-footer">
        <span>South Asian University, New Delhi</span>
        <span>Generated by the Class Timetable system</span>
    </footer>
    <script>
        window.onload = function() {
            setTimeout(function() {
                window.focus();
                window.print();
            }, 250);
        };
    <\/script>
</body>
</html>`);
    printWindow.document.close();
}

function exportCSV() {
    if (!currentSchedule) return;
    const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const rows = Object.values(currentSchedule)
        .sort((a, b) => DAYS.indexOf(a.slot.day) - DAYS.indexOf(b.slot.day) || a.slot.start - b.slot.start)
        .map(item => [item.slot.day, item.slot.time, item.room?.id, item.courseCode, item.courseName,
                      item.instructor, cohortsOf(item).join('; '), item.students, item.requiresLab ? 'Yes' : 'No'].map(cell).join(','));
    const csv = ["Day,Time,Room,Course Code,Course Name,Instructor,Cohort(s),Students,Requires Lab", ...rows].join('\n');

    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "class_timetable.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}