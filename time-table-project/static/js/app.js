let rooms = [];
let timeslots = [];
let courses = [];
let currentSchedule = null;
let nextCourseId = 1;
let editingCourse = -1;  // index of the course being edited, -1 when adding

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const DEFAULT_COHORTS = ["1MSc1", "MTI", "IMT3", "MSc3", "MCA3", "PhD", "MT3", "MCA1", "MSc1/IMTI"];
const LUNCH = { start: 13 * 60, end: 14 * 60, label: "13:00-14:00" };

const fmtTime = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
const toMinutes = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
const fmtHours = (h) => `${Number(h.toFixed(2))} h`;

// 08:00, 08:30, ... 20:00
const TIME_OPTIONS = Array.from({ length: 25 }, (_, i) => fmtTime(8 * 60 + i * 30));
// 0.5 h, 1 h, ... 4 h
const DURATION_OPTIONS = Array.from({ length: 8 }, (_, i) => (i + 1) / 2);

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
        courses = (data.courses || []).map(c => ({ ...withHours(c), id: "C" + nextCourseId++, cohorts: cohortsOf(c) }));
        predefinedTimes = data.predefinedTimes || [];
        savedSchedule = data.schedule || null;
        savedStats = data.stats || null;
    } catch (err) {
        console.warn("Could not load initial API dataset, starting with empty state:", err);
    }

    setupTimePickers(predefinedTimes);
    setupCourseHours();
    setupBulkSlots();
    renderCohortChoices();
    renderAll();
    setupFormListeners();

    if (savedSchedule) {
        currentSchedule = savedSchedule;
        if (savedStats) showStats(savedStats);
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

/** Fill in lecture/practical hours for courses saved before they existed (1-hour meetings). */
function withHours(c) {
    if (c.lectureHours != null || c.labHours != null) {
        return { ...c, lectureDuration: +c.lectureDuration || 0, lectureHours: +c.lectureHours || 0,
                 labDuration: +c.labDuration || 0, labHours: +c.labHours || 0 };
    }
    const n = +c.sessionsPerWeek || 1;
    return c.requiresLab
        ? { ...c, lectureDuration: 0, lectureHours: 0, labDuration: 1, labHours: n }
        : { ...c, lectureDuration: 1, lectureHours: n, labDuration: 0, labHours: 0 };
}

/** How a course's weekly hours split into meetings, or an error message. */
function coursePlan(c) {
    const parts = [];
    for (const [word, dur, hours] of [["lecture", c.lectureDuration, c.lectureHours], ["practical", c.labDuration, c.labHours]]) {
        if (!hours) continue;
        if (hours < 0 || Math.round(hours * 2) !== hours * 2) return { error: `${word[0].toUpperCase() + word.slice(1)} hours per week must be in steps of 0.5.` };
        if (!dur) return { error: `Choose how long each ${word} lasts.` };
        const count = hours / dur;
        if (!Number.isInteger(count)) {
            return { error: `${fmtHours(hours)} of ${word}s a week doesn't split into ${fmtHours(dur)} ${word}s. Use a multiple of ${fmtHours(dur)}.` };
        }
        parts.push({ word, dur, hours, count });
    }
    if (!parts.length) return { error: "Give the course some lecture or practical hours per week." };
    return { parts };
}

function describePlan(plan) {
    return plan.parts.map(p => `${p.count} ${p.word}${p.count > 1 ? 's' : ''} × ${fmtHours(p.dur)}`).join(' + ');
}

function readCourseHours() {
    return {
        lectureDuration: parseFloat(document.getElementById('cLecDur').value) || 0,
        lectureHours: parseFloat(document.getElementById('cLecHours').value) || 0,
        labDuration: parseFloat(document.getElementById('cLabDur').value) || 0,
        labHours: parseFloat(document.getElementById('cLabHours').value) || 0,
    };
}

function setupCourseHours() {
    document.querySelectorAll('.duration-select').forEach(sel => {
        sel.innerHTML = DURATION_OPTIONS.map(h => `<option value="${h}">${fmtHours(h)}</option>`).join('');
    });
    resetCourseHours();
    ['cLecDur', 'cLecHours', 'cLabDur', 'cLabHours'].forEach(id =>
        document.getElementById(id)?.addEventListener('input', updatePlanPreview));
}

function resetCourseHours() {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    set('cLecDur', 1.5); set('cLecHours', 3); set('cLabDur', 2); set('cLabHours', 0);
    updatePlanPreview();
}

function updatePlanPreview() {
    const line = document.getElementById('cPlan');
    if (!line || !document.getElementById('cLecDur')) return;
    const plan = coursePlan(readCourseHours());
    line.classList.toggle('error', !!plan.error);
    line.textContent = plan.error || `Each week: ${describePlan(plan)}`;
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
        <div class="row-item ${i === editingCourse ? 'editing' : ''}">
            <div>
                <div><span class="font-semibold">${escapeHtml(c.code)}</span> ${escapeHtml(c.name || '')} ${c.labHours > 0 ? '<span class="tag ml-1">Lab</span>' : ''}</div>
                <div class="text-neutral-500 mt-0.5">${escapeHtml(c.instructor || '')} · ${escapeHtml(cohortsOf(c).join(', '))} · ${c.students || 0} students</div>
                ${c.lectureHours > 0 ? `<div class="text-neutral-500">Lecture: ${fmtHours(c.lectureHours)}/week in ${fmtHours(c.lectureDuration)} classes</div>` : ''}
                ${c.labHours > 0 ? `<div class="text-neutral-500">Practical: ${fmtHours(c.labHours)}/week in ${fmtHours(c.labDuration)} labs</div>` : ''}
            </div>
            <div class="row-actions">
                <button onclick="editCourse(${i})" class="edit-btn" aria-label="Edit ${escapeHtml(c.code)}">Edit</button>
                <button onclick="deleteCourse(${i})" class="delete-btn" aria-label="Remove ${escapeHtml(c.code)}">×</button>
            </div>
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

/** Back-to-back or overlapping ranges merged, e.g. [[570,600],[600,630]] -> [[570,630]]. */
function mergeRanges(ranges) {
    const out = [];
    [...ranges].sort((a, b) => a.start - b.start).forEach(r => {
        const last = out[out.length - 1];
        if (last && r.start <= last.end) last.end = Math.max(last.end, r.end);
        else out.push({ start: r.start, end: r.end });
    });
    return out;
}

function renderTimeslots() {
    const list = document.getElementById('slotList');
    if (!list) return;
    setCount('slotCount', timeslots.length);

    if (timeslots.length === 0) {
        list.innerHTML = `<p class="text-sm text-neutral-400 py-3">No timeslots added yet.</p>`;
        return;
    }

    const days = [...new Set(timeslots.map(t => t.day))].sort((a, b) => DAYS.indexOf(a) - DAYS.indexOf(b));
    list.innerHTML = days.map(day => {
        const slots = timeslots
            .map((t, i) => ({ t, i, range: parseRange(t.time) }))
            .filter(x => x.t.day === day)
            .sort((a, b) => (a.range?.start ?? 0) - (b.range?.start ?? 0));
        const windows = mergeRanges(slots.map(x => x.range).filter(Boolean));
        const total = windows.reduce((m, w) => m + w.end - w.start, 0);
        return `
            <div class="day-group">
                <div class="day-group-head">
                    <span class="font-semibold">${escapeHtml(day)}</span>
                    <button onclick="deleteDay('${escapeHtml(day)}')" class="link-btn text-xs" aria-label="Remove all ${escapeHtml(day)} slots">Remove day</button>
                </div>
                <div class="day-windows">${windows.map(w => `${fmtTime(w.start)}–${fmtTime(w.end)}`).join(', ')} · ${fmtHours(total / 60)}</div>
                <div class="slot-chips">
                    ${slots.map(({ t, i }) => `<span class="slot-chip">${escapeHtml(t.time)}<button onclick="deleteSlot(${i})" aria-label="Remove ${escapeHtml(day)} ${escapeHtml(t.time)}">×</button></span>`).join('')}
                </div>
            </div>`;
    }).join('');
}

/** Every 30-minute slot between start and end (minutes) for the chosen days. */
function halfHourSlots(days, start, end, skipLunch) {
    const out = [];
    days.forEach(day => {
        for (let m = start; m + 30 <= end; m += 30) {
            if (skipLunch && m < LUNCH.end && LUNCH.start < m + 30) continue;
            out.push({ day, time: `${fmtTime(m)}-${fmtTime(m + 30)}` });
        }
    });
    return out;
}

function setupBulkSlots() {
    const daysBox = document.getElementById('bDays');
    const all = document.getElementById('bAllDays');
    const start = document.getElementById('bStart');
    const end = document.getElementById('bEnd');
    const skip = document.getElementById('bSkipLunch');
    if (!daysBox || !start || !end) return;

    const weekdays = DAYS.slice(0, 5);
    daysBox.innerHTML = DAYS.map(d => `
        <label><input type="checkbox" name="bDay" value="${d}" class="checkbox" ${weekdays.includes(d) ? 'checked' : ''}> ${d.slice(0, 3)}</label>
    `).join('');
    start.innerHTML = TIME_OPTIONS.slice(0, -1).map(t => `<option>${t}</option>`).join('');
    end.innerHTML = TIME_OPTIONS.slice(1).map(t => `<option>${t}</option>`).join('');
    start.value = "09:30";
    end.value = "17:30";

    const dayBoxes = () => [...daysBox.querySelectorAll('input[name="bDay"]')];
    const syncAll = () => {
        const boxes = dayBoxes();
        all.checked = boxes.every(b => b.checked);
        all.indeterminate = !all.checked && boxes.some(b => b.checked);
    };
    all.addEventListener('change', () => { dayBoxes().forEach(b => { b.checked = all.checked; }); preview(); });
    daysBox.addEventListener('change', () => { syncAll(); preview(); });
    [start, end, skip].forEach(el => el?.addEventListener('change', preview));

    function pending() {
        const days = dayBoxes().filter(b => b.checked).map(b => b.value);
        const s = toMinutes(start.value), e = toMinutes(end.value);
        if (!days.length) return { error: 'Pick at least one day.' };
        if (e <= s) return { error: '"To" must be later than "From".' };
        const all = halfHourSlots(days, s, e, skip?.checked);
        const fresh = all.filter(n => !timeslots.some(t => t.day === n.day && t.time.replace(/\s+/g, '') === n.time));
        return { days, all, fresh };
    }
    function preview() {
        const line = document.getElementById('bPreview');
        if (!line) return;
        const p = pending();
        line.classList.toggle('error', !!p.error);
        if (p.error) { line.textContent = p.error; return; }
        const perDay = p.all.length / p.days.length;
        const dup = p.all.length - p.fresh.length;
        line.textContent = `${perDay} slots × ${p.days.length} day${p.days.length > 1 ? 's' : ''} = ${p.all.length}` +
            (dup ? ` (${dup} already added)` : '');
    }
    syncAll();
    preview();

    document.getElementById('bulkSlotForm')?.addEventListener('submit', (e) => {
        e.preventDefault();
        const p = pending();
        if (p.error) { alert(p.error); return; }
        if (!p.fresh.length) { alert('All of those slots already exist.'); return; }
        timeslots.push(...p.fresh);
        renderTimeslots();
        preview();
        markStale();
        persistChanges();
    });
    window.refreshBulkPreview = preview;
}

function clearSlots() {
    if (!timeslots.length || !confirm('Remove all timeslots?')) return;
    timeslots = [];
    renderTimeslots();
    window.refreshBulkPreview?.();
    markStale();
    persistChanges();
}

function deleteDay(day) {
    timeslots = timeslots.filter(t => t.day !== day);
    renderTimeslots();
    window.refreshBulkPreview?.();
    markStale();
    persistChanges();
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

            const hours = readCourseHours();
            const plan = coursePlan(hours);
            if (plan.error) {
                alert(plan.error);
                return;
            }
            // Only keep the length of a part that is actually used
            if (!hours.lectureHours) hours.lectureDuration = 0;
            if (!hours.labHours) hours.labDuration = 0;

            const course = {
                id: editingCourse >= 0 ? courses[editingCourse].id : "C" + nextCourseId++,
                code: document.getElementById('cCode').value.trim(),
                name: document.getElementById('cName').value.trim(),
                instructor: document.getElementById('cFaculty').value.trim(),
                cohorts,
                students: parseInt(document.getElementById('cStudents').value) || 0,
                ...hours,
                requiresLab: hours.labHours > 0,
                sessionsPerWeek: plan.parts.reduce((n, p) => n + p.count, 0)
            };
            const wasEditing = editingCourse >= 0;
            if (wasEditing) courses[editingCourse] = course;
            else courses.push(course);
            showToast(`${wasEditing ? 'Saved changes to' : 'Added'} ${course.code}: ${describePlan(plan)} per week.`);
            endCourseEdit();
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
            window.refreshBulkPreview?.();
            markStale();
            persistChanges();
        });
    }
}

function deleteCourse(i) {
    const c = courses[i];
    if (!c) return;
    if (!confirm(`Delete ${c.code}${c.name ? ' – ' + c.name : ''}? This removes all its lectures and practicals from the timetable.`)) return;
    courses.splice(i, 1);
    if (editingCourse === i) endCourseEdit();
    else if (editingCourse > i) editingCourse--;
    renderCourses();
    markStale();
    persistChanges();
    showToast(`Deleted ${c.code}.`);
}

/** Load a course into the form; the submit button then saves instead of adding. */
function editCourse(i) {
    const c = courses[i];
    if (!c) return;
    editingCourse = i;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    set('cCode', c.code || '');
    set('cName', c.name || '');
    set('cFaculty', c.instructor || '');
    set('cStudents', c.students || 1);
    set('cLecDur', c.lectureDuration || 1.5);
    set('cLecHours', c.lectureHours || 0);
    set('cLabDur', c.labDuration || 2);
    set('cLabHours', c.labHours || 0);
    renderCohortChoices();
    const mine = new Set(cohortsOf(c));
    document.querySelectorAll('input[name="cCohorts"]').forEach(cb => { cb.checked = mine.has(cb.value); });
    updatePlanPreview();
    document.getElementById('courseSubmit').textContent = `Save changes to ${c.code}`;
    document.getElementById('courseCancel')?.classList.remove('hidden');
    renderCourses();
    document.getElementById('courseForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.getElementById('cCode')?.focus({ preventScroll: true });
}

function endCourseEdit() {
    editingCourse = -1;
    document.getElementById('courseForm')?.reset();
    resetCourseHours();
    renderCohortChoices();
    document.querySelectorAll('input[name="cCohorts"]').forEach(cb => { cb.checked = false; });
    const btn = document.getElementById('courseSubmit');
    if (btn) btn.textContent = 'Add course';
    document.getElementById('courseCancel')?.classList.add('hidden');
}

function cancelEditCourse() { endCourseEdit(); renderCourses(); }

let toastTimer = null;
function showToast(message) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

function renderChecks(stats) {
    const panel = document.getElementById('checksPanel');
    const body = document.getElementById('checksBody');
    const summary = document.getElementById('checksSummary');
    const checks = stats?.checks;
    if (!panel || !body) return;
    if (!checks?.length) { panel.classList.add('hidden'); return; }
    const short = (d) => d.slice(0, 3);
    const part = (p) => {
        if (!p || !p.required) return '<span class="ok">–</span>';
        const cls = p.scheduled < p.required ? 'bad' : '';
        return `<span class="${cls}">${fmtHours(p.scheduled)} / ${fmtHours(p.required)}</span>
                <div class="days">${[...p.days].sort((x, y) => DAYS.indexOf(x) - DAYS.indexOf(y)).map(short).join(', ')}</div>`;
    };
    const withIssues = checks.filter(c => c.issues.length);
    summary.textContent = withIssues.length
        ? `· ${withIssues.length} course${withIssues.length > 1 ? 's' : ''} need attention`
        : `· all ${checks.length} courses got their full hours, lectures and practicals on separate days`;
    body.innerHTML = checks.map(c => `
        <tr>
            <td><span class="font-semibold">${escapeHtml(c.code)}</span> <span class="text-neutral-500">${escapeHtml(c.name || '')}</span></td>
            <td>${escapeHtml(c.cohort)}</td>
            <td>${part(c.lecture)}</td>
            <td>${part(c.lab)}</td>
            <td>${c.issues.length ? c.issues.map(x => `<div class="bad">⚠ ${escapeHtml(x)}</div>`).join('') : '<span class="ok">✓ OK</span>'}</td>
        </tr>`).join('');
    panel.classList.remove('hidden');
}

function showStats(stats) {
    if (!stats) return;
    const put = (id, v) => { const el = document.getElementById(id); if (el) el.innerText = v; };
    put('statTime', `${stats.timeMs} ms`);
    put('statBacktracks', stats.backtracks);
    put('statMethod', stats.method || 'backtracking');
    put('statSeed', stats.seed != null ? `#${stats.seed}` : '-');
    document.getElementById('statsBar')?.classList.remove('hidden');
    renderChecks(stats);
}
function deleteRoom(i) { rooms.splice(i, 1); renderRooms(); markStale(); persistChanges(); }
function deleteSlot(i) { timeslots.splice(i, 1); renderTimeslots(); window.refreshBulkPreview?.(); markStale(); persistChanges(); }

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
            showStats(data.stats);
            showToast('New timetable generated. Click "Generate schedule" again for a different arrangement.');
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

function kindOf(item) {
    return item.kind || (item.requiresLab ? 'lab' : 'lecture');
}

function buildTimetableHTML(schedule) {
    const items = Object.values(schedule || {});
    const filter = document.getElementById('cohortFilter')?.value || '';
    const columns = filter ? [filter] : scheduledCohorts(schedule);
    const visible = items.filter(item => cohortsOf(item).some(c => columns.includes(c)));

    let html = '';
    DAYS.forEach(day => {
        const dayItems = visible
            .filter(item => item.slot?.day === day)
            .map(item => ({ item, range: parseRange(item.slot.time) }))
            .filter(x => x.range);
        if (dayItems.length === 0) return;

        // Rows are the stretches between every class start/end time, so a 2 h practical
        // next to two 1 h lectures spans two rows.
        const bounds = new Set();
        dayItems.forEach(({ range }) => { bounds.add(range.start); bounds.add(range.end); });
        const lunchFree = !dayItems.some(({ range }) => range.start < LUNCH.end && LUNCH.start < range.end);
        const hasBefore = dayItems.some(({ range }) => range.end <= LUNCH.start);
        const hasAfter = dayItems.some(({ range }) => range.start >= LUNCH.end);
        const showLunch = lunchFree && hasBefore && hasAfter;
        if (showLunch) { bounds.add(LUNCH.start); bounds.add(LUNCH.end); }
        const edges = [...bounds].sort((a, b) => a - b);
        const rows = edges.slice(0, -1).map((start, i) => ({
            start, end: edges[i + 1],
            lunch: showLunch && start === LUNCH.start,
        }));

        const card = (item) => `
            <div class="tt-class">
                <div class="flex justify-between items-start gap-2">
                    <span class="font-bold">${escapeHtml(item.courseCode)}</span>
                    <span class="tag">${kindOf(item) === 'lab' ? 'Practical' : 'Lecture'}</span>
                </div>
                <div class="tt-name">${escapeHtml(item.courseName || '')}</div>
                <div class="tt-meta">${escapeHtml(item.slot.time)} · ${escapeHtml(item.room?.id || '')} · ${escapeHtml(item.instructor || '')}</div>
            </div>`;

        const body = rows.map(row => {
            if (row.lunch) {
                return `<tr class="tt-lunch"><td class="tt-time">${LUNCH.label}</td><td colspan="${columns.length}">Lunch break</td></tr>`;
            }
            const cells = columns.map(cohort => {
                const mine = dayItems.filter(x => cohortsOf(x.item).includes(cohort));
                const starting = mine.filter(x => x.range.start === row.start);
                if (starting.length) {
                    const end = Math.max(...starting.map(x => x.range.end));
                    const span = rows.filter(r => r.start >= row.start && r.end <= end).length;
                    return `<td rowspan="${span}">${starting.map(x => card(x.item)).join('')}</td>`;
                }
                // Covered by a class that started in an earlier row: the rowspan already fills it
                if (mine.some(x => x.range.start < row.start && row.start < x.range.end)) return '';
                return `<td class="tt-empty">–</td>`;
            }).join('');
            return `<tr><td class="tt-time">${fmtTime(row.start)}-${fmtTime(row.end)}</td>${cells}</tr>`;
        }).join('');

        html += `
            <section class="tt-day">
                <h3 class="serif text-xl font-semibold mb-2">${day}</h3>
                <div class="overflow-x-auto">
                    <table class="tt-grid" style="min-width: ${7 + columns.length * 8}rem">
                        <thead><tr><th class="tt-time">Time</th>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                        <tbody>${body}</tbody>
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
        .map(item => {
            const r = parseRange(item.slot.time);
            const hours = r ? (r.end - r.start) / 60 : '';
            return [item.slot.day, item.slot.time, hours, kindOf(item) === 'lab' ? 'Practical' : 'Lecture', item.room?.id,
                    item.courseCode, item.courseName, item.instructor, cohortsOf(item).join('; '), item.students].map(cell).join(',');
        });
    const csv = ["Day,Time,Hours,Type,Room,Course Code,Course Name,Instructor,Cohort(s),Students", ...rows].join('\n');

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