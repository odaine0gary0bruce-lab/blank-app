from __future__ import annotations

import csv
import io
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


# =========================================================
# MAINTAINLY - SINGLE-FILE STREAMLIT EDITION
# Save this file as app.py and run: streamlit run app.py
# =========================================================

st.set_page_config(
    page_title="Maintainly - Maintenance scheduling made clear",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#18332d; --muted:#6f7e79; --green:#2f7564; --paper:#f5f7f3; --line:#dce3de; }
    .stApp { background:var(--paper); color:var(--ink); }
    .main .block-container { max-width:1500px; padding:1.3rem 2rem 3rem; }
    section[data-testid="stSidebar"] { background:#173f36; }
    section[data-testid="stSidebar"] * { color:#eef7f3; }
    section[data-testid="stSidebar"] div[role="radiogroup"] label { border-radius:10px; padding:.58rem .7rem; }
    section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background:rgba(255,255,255,.14); }
    .brand { padding:.35rem .2rem 1.35rem; }
    .brand b { font-size:1.3rem; }
    .brand span { display:inline-grid; place-items:center; width:38px; height:38px; margin-right:.6rem;
        border-radius:11px; background:#d8ede4; color:#214e43!important; }
    .brand small { display:block; margin:.35rem 0 0 3rem; color:#b8d1c8!important; }
    .eyebrow { color:var(--green); font-size:.72rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .copy { color:var(--muted); margin-top:-.4rem; margin-bottom:1.2rem; }
    h1,h2,h3 { color:var(--ink); letter-spacing:-.02em; }
    div[data-testid="stMetric"], div[data-testid="stForm"], div[data-testid="stExpander"] {
        background:#fff; border:1px solid var(--line); border-radius:14px; padding:.45rem .7rem;
    }
    div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
    .stButton button, .stDownloadButton button { border-radius:10px; font-weight:700; }
    .stButton button[kind="primary"] { background:var(--green); border-color:var(--green); }
    .board-card { background:#fff; border:1px solid var(--line); border-left:4px solid var(--green);
        border-radius:11px; padding:.7rem; margin:.45rem 0; min-height:100px; }
    .board-card small { color:var(--green); font-weight:800; }
    .board-card b { display:block; margin:.3rem 0; }
    .board-card span { color:var(--muted); font-size:.82rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PRIORITIES = ["Emergency", "Critical", "Urgent", "High", "Medium", "Low", "Opportunity / Shutdown"]
JOB_STATUSES = ["Pending", "Scheduled", "Draft Scheduled", "Final Scheduled", "In progress", "Active", "On Hold", "Completed", "Overdue"]
SKILLS = ["Mechanical", "Welding", "Electrical", "HVAC", "Instrumentation", "Multi-skill", "General"]

DATA_DIR = Path(os.getenv("MAINTENANCE_DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "maintainly.db"


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def safe_index(options: list[str], value: str) -> int:
    return options.index(value) if value in options else 0


def flash(message: str) -> None:
    st.session_state["flash"] = message
    st.rerun()


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(query: str, parameters: tuple = ()) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, parameters).fetchall()]


def initialize_database() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS team_members (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                skill TEXT NOT NULL, weekly_hours REAL NOT NULL DEFAULT 40,
                availability TEXT NOT NULL DEFAULT 'Available', active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, asset_number TEXT NOT NULL UNIQUE, asset_name TEXT NOT NULL,
                location TEXT NOT NULL, department TEXT NOT NULL, criticality TEXT NOT NULL,
                manufacturer TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS work_orders (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, asset TEXT NOT NULL, location TEXT NOT NULL,
                department TEXT NOT NULL, due_at TEXT NOT NULL, duration_hours REAL NOT NULL DEFAULT 1,
                priority TEXT NOT NULL DEFAULT 'Medium', priority_score INTEGER NOT NULL DEFAULT 7,
                status TEXT NOT NULL DEFAULT 'Pending', category TEXT NOT NULL DEFAULT 'Mechanical',
                crew_size INTEGER NOT NULL DEFAULT 1, mechanical_needed INTEGER NOT NULL DEFAULT 0,
                welding_needed INTEGER NOT NULL DEFAULT 0, allowed_days TEXT NOT NULL,
                preferred_day TEXT NOT NULL DEFAULT '', scope_ready INTEGER NOT NULL DEFAULT 1,
                parts_ready INTEGER NOT NULL DEFAULT 1, permits_ready INTEGER NOT NULL DEFAULT 1,
                shutdown_ready INTEGER NOT NULL DEFAULT 1, released INTEGER NOT NULL DEFAULT 1,
                notes TEXT NOT NULL DEFAULT '', completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY, work_order_id TEXT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
                state TEXT NOT NULL DEFAULT 'Draft', day TEXT NOT NULL, crew_label TEXT NOT NULL,
                technicians TEXT NOT NULL, hours REAL NOT NULL, status TEXT NOT NULL DEFAULT 'Scheduled',
                notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedule_history (
                id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL, action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '', changed_at TEXT NOT NULL
            );
            """
        )
        stamp = now()
        if conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0] == 0:
            team = [
                ("TM-MAYA", "Maya Chen", "Senior technician", "maya@maintainly.local", "Mechanical", 40, "Available", 1),
                ("TM-JORDAN", "Jordan Lee", "Electrical technician", "jordan@maintainly.local", "Electrical", 40, "Available", 1),
                ("TM-SAM", "Sam Rivera", "Maintenance technician", "sam@maintainly.local", "Multi-skill", 40, "Available", 1),
                ("TM-AMARA", "Amara Brown", "Welder", "amara@maintainly.local", "Welding", 40, "Available", 1),
            ]
            conn.executemany("INSERT INTO team_members VALUES (?,?,?,?,?,?,?,?,?,?)", [(*item, stamp, stamp) for item in team])
        if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
            assets = [
                ("AS-GEN02", "GEN-02", "Backup Generator 02", "Utility yard", "Utilities", "Critical", "Caterpillar", "C18", 1, "Monthly readiness testing"),
                ("AS-CH01", "CH-01", "Process Chiller 01", "Central plant", "Utilities", "Critical", "York", "YVAA", 1, "Water treatment readings required"),
                ("AS-DOCK07", "DOCK-07", "Dock Door 07", "Warehouse - Bay 7", "Warehouse", "High", "Rite-Hite", "RHH-5000", 1, "Safety interlocks installed"),
            ]
            conn.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [(*item, stamp, stamp) for item in assets])
        if conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 0:
            due = (datetime.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
            jobs = [
                ("WO-2842", "Generator load bank test", "GEN-02", "Utility yard", "Utilities", due, 2.5, "Critical", 18, "Pending", "Electrical", 2, 1, 0, ",".join(DAYS[:5]), "Tuesday", 1, 1, 1, 1, 1, "Coordinate the test window with security."),
                ("WO-2850", "Conveyor belt alignment", "DOCK-07", "Warehouse - Bay 7", "Warehouse", due, 3.0, "High", 12, "Pending", "Mechanical", 2, 2, 0, ",".join(DAYS[:5]), "Thursday", 1, 1, 1, 1, 1, "Check tracking after a 20-minute run."),
            ]
            conn.executemany(
                """INSERT INTO work_orders (id,title,asset,location,department,due_at,duration_hours,priority,priority_score,status,category,crew_size,mechanical_needed,welding_needed,allowed_days,preferred_day,scope_ready,parts_ready,permits_ready,shutdown_ready,released,notes,completed_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)""",
                [(*item, stamp, stamp) for item in jobs],
            )


initialize_database()


def save_team(data: dict, member_id: str | None = None) -> None:
    member_id = member_id or uid("TM")
    stamp = now()
    with connection() as conn:
        if conn.execute("SELECT 1 FROM team_members WHERE id=?", (member_id,)).fetchone():
            conn.execute("UPDATE team_members SET name=?,role=?,email=?,skill=?,weekly_hours=?,availability=?,active=?,updated_at=? WHERE id=?",
                         (data["name"], data["role"], data["email"].lower(), data["skill"], data["hours"], data["availability"], int(data["active"]), stamp, member_id))
        else:
            conn.execute("INSERT INTO team_members VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (member_id, data["name"], data["role"], data["email"].lower(), data["skill"], data["hours"], data["availability"], int(data["active"]), stamp, stamp))


def save_asset(data: dict, asset_id: str | None = None) -> None:
    asset_id = asset_id or uid("AS")
    stamp = now()
    values = (data["number"].upper(), data["name"], data["location"], data["department"], data["criticality"], data["manufacturer"], data["model"], int(data["active"]), data["notes"])
    with connection() as conn:
        if conn.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
            conn.execute("UPDATE assets SET asset_number=?,asset_name=?,location=?,department=?,criticality=?,manufacturer=?,model=?,active=?,notes=?,updated_at=? WHERE id=?", (*values, stamp, asset_id))
        else:
            conn.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (asset_id, *values, stamp, stamp))


def save_job(data: dict, job_id: str | None = None) -> None:
    job_id = job_id or f"WO-{3000 + uuid.uuid4().int % 6999}"
    stamp = now()
    values = (data["title"], data["asset"], data["location"], data["department"], data["due_at"], data["duration"], data["priority"], data["score"], data["status"], data["category"], data["crew"], data["mechanical"], data["welding"], ",".join(data["allowed_days"]), data["preferred_day"], int(data["scope"]), int(data["parts"]), int(data["permits"]), int(data["shutdown"]), int(data["released"]), data["notes"])
    with connection() as conn:
        if conn.execute("SELECT 1 FROM work_orders WHERE id=?", (job_id,)).fetchone():
            conn.execute("""UPDATE work_orders SET title=?,asset=?,location=?,department=?,due_at=?,duration_hours=?,priority=?,priority_score=?,status=?,category=?,crew_size=?,mechanical_needed=?,welding_needed=?,allowed_days=?,preferred_day=?,scope_ready=?,parts_ready=?,permits_ready=?,shutdown_ready=?,released=?,notes=?,updated_at=? WHERE id=?""", (*values, stamp, job_id))
        else:
            conn.execute("""INSERT INTO work_orders (id,title,asset,location,department,due_at,duration_hours,priority,priority_score,status,category,crew_size,mechanical_needed,welding_needed,allowed_days,preferred_day,scope_ready,parts_ready,permits_ready,shutdown_ready,released,notes,completed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)""", (job_id, *values, stamp, stamp))


def history(conn: sqlite3.Connection, assignment_id: str, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO schedule_history VALUES (?,?,?,?,?)", (uid("SH"), assignment_id, action, detail, now()))


def skill_match(skill: str, required: str) -> bool:
    value = skill.lower()
    return required.lower() in value or "multi" in value or "general" in value


def generate_draft(daily_limit: float, clear_first: bool) -> tuple[int, list[str]]:
    created, warnings = 0, []
    stamp = now()
    with connection() as conn:
        if clear_first:
            conn.execute("DELETE FROM assignments WHERE state='Draft'")
            conn.execute("UPDATE work_orders SET status='Pending' WHERE status='Draft Scheduled'")
        jobs = [dict(row) for row in conn.execute("SELECT * FROM work_orders WHERE status NOT IN ('Completed') AND released=1 ORDER BY priority_score DESC,due_at").fetchall()]
        members = [dict(row) for row in conn.execute("SELECT * FROM team_members WHERE active=1 AND availability!='Unavailable'").fetchall()]
        load: dict[tuple[str, str], float] = {}
        for assignment in conn.execute("SELECT * FROM assignments WHERE status!='Complete'").fetchall():
            for name in assignment["technicians"].split(","):
                if name:
                    load[(assignment["day"], name)] = load.get((assignment["day"], name), 0) + assignment["hours"]
        for job in jobs:
            already = conn.execute("SELECT COALESCE(SUM(hours),0) FROM assignments WHERE work_order_id=? AND status!='Complete'", (job["id"],)).fetchone()[0]
            remaining = max(0.0, job["duration_hours"] - already)
            if remaining <= 0:
                continue
            days = [day for day in job["allowed_days"].split(",") if day in DAYS]
            if job["preferred_day"] in days:
                days = [job["preferred_day"], *[day for day in days if day != job["preferred_day"]]]
            crew_size = max(job["crew_size"], job["mechanical_needed"] + job["welding_needed"], 1)
            scheduled = False
            for day in days:
                selected: list[dict] = []
                for required, count in (("Mechanical", job["mechanical_needed"]), ("Welding", job["welding_needed"])):
                    candidates = [m for m in members if m not in selected and skill_match(m["skill"], required) and load.get((day, m["name"]), 0) < daily_limit]
                    candidates.sort(key=lambda m: load.get((day, m["name"]), 0))
                    selected.extend(candidates[:count])
                remaining_members = [m for m in members if m not in selected and load.get((day, m["name"]), 0) < daily_limit]
                remaining_members.sort(key=lambda m: load.get((day, m["name"]), 0))
                selected.extend(remaining_members[:max(0, crew_size - len(selected))])
                if len(selected) < crew_size:
                    continue
                names = [m["name"] for m in selected]
                hours = min(remaining, min(daily_limit - load.get((day, name), 0) for name in names))
                if hours < .5:
                    continue
                assignment_id = uid("SA")
                crew_count = conn.execute("SELECT COUNT(*) FROM assignments WHERE day=?", (day,)).fetchone()[0] + 1
                conn.execute("INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?,?)", (assignment_id, job["id"], "Draft", day, f"{day[:3]} Crew {crew_count}", ",".join(names), hours, "Scheduled", job["notes"], stamp, stamp))
                history(conn, assignment_id, "Generated", f"{job['id']} assigned to {', '.join(names)}")
                for name in names:
                    load[(day, name)] = load.get((day, name), 0) + hours
                conn.execute("UPDATE work_orders SET status='Draft Scheduled',updated_at=? WHERE id=?", (stamp, job["id"]))
                created += 1
                scheduled = True
                break
            if not scheduled:
                warnings.append(f"{job['id']} - {job['title']} could not be scheduled with current skills and capacity.")
    return created, warnings


def promote_all() -> int:
    with connection() as conn:
        assignments = conn.execute("SELECT * FROM assignments WHERE state='Draft'").fetchall()
        conn.execute("UPDATE assignments SET state='Final',updated_at=? WHERE state='Draft'", (now(),))
        for item in assignments:
            conn.execute("UPDATE work_orders SET status='Final Scheduled',updated_at=? WHERE id=?", (now(), item["work_order_id"]))
            history(conn, item["id"], "Promoted", "Draft to Final")
        return len(assignments)


def title(text: str, copy: str) -> None:
    st.markdown('<div class="eyebrow">Operations workspace</div>', unsafe_allow_html=True)
    st.title(text)
    st.markdown(f'<p class="copy">{copy}</p>', unsafe_allow_html=True)


def team_form(prefix: str, member: dict | None = None) -> tuple[bool, dict]:
    member = member or {}
    with st.form(f"{prefix}_team"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", member.get("name", ""))
        role = c2.text_input("Role", member.get("role", "Maintenance technician"))
        email = c1.text_input("Email", member.get("email", ""))
        skill = c2.selectbox("Skill", SKILLS, index=safe_index(SKILLS, member.get("skill", "Mechanical")))
        availability_options = ["Available", "Limited", "Unavailable"]
        availability = c1.selectbox("Availability", availability_options, index=safe_index(availability_options, member.get("availability", "Available")))
        hours = c2.number_input("Weekly hours", 1.0, 84.0, float(member.get("weekly_hours", 40)), 1.0)
        active = st.checkbox("Active", bool(member.get("active", 1)))
        submitted = st.form_submit_button("Save team member", type="primary", use_container_width=True)
    return submitted, {"name":name.strip(), "role":role.strip(), "email":email.strip(), "skill":skill, "availability":availability, "hours":hours, "active":active}


def asset_form(prefix: str, asset: dict | None = None) -> tuple[bool, dict]:
    asset = asset or {}
    with st.form(f"{prefix}_asset"):
        c1, c2 = st.columns(2)
        number = c1.text_input("Asset number", asset.get("asset_number", ""))
        name = c2.text_input("Asset name", asset.get("asset_name", ""))
        location = c1.text_input("Location", asset.get("location", ""))
        department = c2.text_input("Department", asset.get("department", "Operations"))
        criticality_options = ["Critical", "High", "Normal", "Low"]
        criticality = c1.selectbox("Criticality", criticality_options, index=safe_index(criticality_options, asset.get("criticality", "Normal")))
        manufacturer = c2.text_input("Manufacturer", asset.get("manufacturer", ""))
        model = c1.text_input("Model", asset.get("model", ""))
        active = c2.checkbox("Active asset", bool(asset.get("active", 1)))
        notes = st.text_area("Notes", asset.get("notes", ""))
        submitted = st.form_submit_button("Save asset", type="primary", use_container_width=True)
    return submitted, {"number":number.strip(), "name":name.strip(), "location":location.strip(), "department":department.strip(), "criticality":criticality, "manufacturer":manufacturer.strip(), "model":model.strip(), "active":active, "notes":notes.strip()}


def job_form(prefix: str, job: dict | None = None) -> tuple[bool, dict]:
    job = job or {}
    assets = rows("SELECT * FROM assets WHERE active=1 ORDER BY asset_number")
    asset_options = ["UNASSIGNED", *[a["asset_number"] for a in assets]]
    due = datetime.now() + timedelta(days=2)
    try:
        due = datetime.fromisoformat(job.get("due_at", ""))
    except ValueError:
        pass
    with st.form(f"{prefix}_job"):
        name = st.text_input("Job name", job.get("title", ""))
        c1, c2, c3 = st.columns(3)
        asset = c1.selectbox("Asset", asset_options, index=safe_index(asset_options, job.get("asset", "UNASSIGNED")))
        location = c2.text_input("Location", job.get("location", "Plant"))
        department = c3.text_input("Department", job.get("department", "Operations"))
        due_date = c1.date_input("Due date", due.date())
        due_time = c2.time_input("Due time", due.time().replace(second=0, microsecond=0))
        duration = c3.number_input("Duration hours", .5, 168.0, float(job.get("duration_hours", 1)), .5)
        priority = c1.selectbox("Priority", PRIORITIES, index=safe_index(PRIORITIES, job.get("priority", "Medium")))
        score = c2.number_input("Priority score", 1, 20, int(job.get("priority_score", 7)))
        status = c3.selectbox("Status", JOB_STATUSES, index=safe_index(JOB_STATUSES, job.get("status", "Pending")))
        category = c1.text_input("Category", job.get("category", "Mechanical"))
        crew = c2.number_input("Crew required", 1, 20, int(job.get("crew_size", 1)))
        preferred_options = ["No preference", *DAYS]
        preferred_value = job.get("preferred_day", "") or "No preference"
        preferred = c3.selectbox("Preferred day", preferred_options, index=safe_index(preferred_options, preferred_value))
        mechanical = c1.number_input("Mechanical manpower", 0, 20, int(job.get("mechanical_needed", 0)))
        welding = c2.number_input("Welding manpower", 0, 20, int(job.get("welding_needed", 0)))
        allowed_default = [d for d in job.get("allowed_days", ",".join(DAYS[:5])).split(",") if d in DAYS]
        allowed = st.multiselect("Allowed days", DAYS, default=allowed_default)
        r1, r2, r3, r4, r5 = st.columns(5)
        scope = r1.checkbox("Scope ready", bool(job.get("scope_ready", 1)))
        parts = r2.checkbox("Parts ready", bool(job.get("parts_ready", 1)))
        permits = r3.checkbox("Permits ready", bool(job.get("permits_ready", 1)))
        shutdown = r4.checkbox("Shutdown ready", bool(job.get("shutdown_ready", 1)))
        released = r5.checkbox("Release", bool(job.get("released", 1)))
        notes = st.text_area("Notes", job.get("notes", ""))
        submitted = st.form_submit_button("Save work order", type="primary", use_container_width=True)
    return submitted, {"title":name.strip(), "asset":asset, "location":location.strip(), "department":department.strip(), "due_at":datetime.combine(due_date, due_time).isoformat(), "duration":duration, "priority":priority, "score":score, "status":status, "category":category.strip(), "crew":crew, "mechanical":mechanical, "welding":welding, "allowed_days":allowed, "preferred_day":"" if preferred == "No preference" else preferred, "scope":scope, "parts":parts, "permits":permits, "shutdown":shutdown, "released":released, "notes":notes.strip()}


def assignment_rows(state: str | None = None) -> list[dict]:
    query = """SELECT a.*,w.title,w.asset,w.location FROM assignments a LEFT JOIN work_orders w ON w.id=a.work_order_id"""
    params = ()
    if state:
        query += " WHERE a.state=? AND a.status!='Complete'"
        params = (state,)
    query += " ORDER BY CASE a.day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END,a.crew_label"
    return rows(query, params)


def board(state: str) -> None:
    assignments = assignment_rows(state)
    for group in (DAYS[:5], DAYS[5:]):
        columns = st.columns(len(group))
        for column, day in zip(columns, group):
            with column:
                day_rows = [a for a in assignments if a["day"] == day]
                st.subheader(day[:3])
                st.caption(f"{sum(a['hours'] for a in day_rows):.1f}h")
                for a in day_rows:
                    st.markdown(f'<div class="board-card"><small>{a["crew_label"]}</small><b>{a["title"]}</b><span>{a["work_order_id"]} · {a["hours"]:.1f}h<br>{a["technicians"].replace(",", ", ")}</span></div>', unsafe_allow_html=True)
                if not day_rows:
                    st.caption("No work")


with st.sidebar:
    st.markdown('<div class="brand"><span>M</span><b>Maintainly</b><small>Plant maintenance</small></div>', unsafe_allow_html=True)
    page = st.radio("Navigation", ["Schedule", "Work orders", "Planning", "Assets", "Team", "Reports"], label_visibility="collapsed")
    st.markdown("---")
    st.caption("Persistent Streamlit edition")

message = st.session_state.pop("flash", None)
if message:
    st.success(message)


if page == "Schedule":
    title("Schedule", "Plan the week, spot risks early and keep your team moving.")
    assignments = [a for a in assignment_rows() if a["status"] != "Complete"]
    open_jobs = rows("SELECT * FROM work_orders WHERE status!='Completed'")
    team = rows("SELECT * FROM team_members WHERE active=1")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Scheduled work", len(assignments))
    c2.metric("Planned hours", f"{sum(a['hours'] for a in assignments):.1f}h")
    c3.metric("Open backlog", len(open_jobs))
    c4.metric("Active team", len(team))
    state = st.radio("State", ["Final", "Draft"], horizontal=True, label_visibility="collapsed")
    board(state)

elif page == "Team":
    title("Team", "Add, edit and remove team members and manage weekly capacity.")
    team = rows("SELECT * FROM team_members ORDER BY name")
    c1, c2, c3 = st.columns(3)
    active = [m for m in team if m["active"]]
    c1.metric("Active members", len(active))
    c2.metric("Weekly capacity", f"{sum(m['weekly_hours'] for m in active):.0f}h")
    c3.metric("Skills covered", len({m["skill"] for m in active}))
    roster, add, edit = st.tabs(["Roster", "Add member", "Edit / delete"])
    with roster:
        st.dataframe(pd.DataFrame([{ "Name":m["name"], "Role":m["role"], "Skill":m["skill"], "Availability":m["availability"], "Hours":m["weekly_hours"], "Active":bool(m["active"]), "Email":m["email"] } for m in team]), use_container_width=True, hide_index=True)
    with add:
        submitted, data = team_form("add")
        if submitted:
            if not data["name"] or not data["email"]:
                st.error("Name and email are required.")
            else:
                try:
                    save_team(data)
                    flash("Team member added.")
                except sqlite3.IntegrityError:
                    st.error("That email address is already in use.")
    with edit:
        if team:
            labels = {m["id"]: f"{m['name']} - {m['skill']}" for m in team}
            member_id = st.selectbox("Select team member", list(labels), format_func=labels.get)
            member = next(m for m in team if m["id"] == member_id)
            submitted, data = team_form(f"edit_{member_id}", member)
            if submitted:
                try:
                    save_team(data, member_id)
                    flash("Team member updated.")
                except sqlite3.IntegrityError:
                    st.error("That email address is already in use.")
            if st.button("Delete selected team member"):
                with connection() as conn:
                    conn.execute("DELETE FROM team_members WHERE id=?", (member_id,))
                flash("Team member deleted.")

elif page == "Assets":
    title("Assets", "Track asset health, criticality and service history.")
    assets = rows("SELECT * FROM assets ORDER BY asset_number")
    c1, c2, c3 = st.columns(3)
    c1.metric("Registered assets", len(assets))
    c2.metric("Active assets", len([a for a in assets if a["active"]]))
    c3.metric("Critical assets", len([a for a in assets if a["criticality"] == "Critical"]))
    register, add, edit = st.tabs(["Asset register", "Add asset", "Edit / delete"])
    with register:
        st.dataframe(pd.DataFrame([{ "Asset":a["asset_number"], "Name":a["asset_name"], "Location":a["location"], "Department":a["department"], "Criticality":a["criticality"], "Active":bool(a["active"]) } for a in assets]), use_container_width=True, hide_index=True)
    with add:
        submitted, data = asset_form("add")
        if submitted:
            if not data["number"] or not data["name"]:
                st.error("Asset number and name are required.")
            else:
                try:
                    save_asset(data)
                    flash("Asset added.")
                except sqlite3.IntegrityError:
                    st.error("That asset number already exists.")
    with edit:
        if assets:
            labels = {a["id"]: f"{a['asset_number']} - {a['asset_name']}" for a in assets}
            asset_id = st.selectbox("Select asset", list(labels), format_func=labels.get)
            asset = next(a for a in assets if a["id"] == asset_id)
            submitted, data = asset_form(f"edit_{asset_id}", asset)
            if submitted:
                save_asset(data, asset_id)
                flash("Asset updated.")
            if st.button("Delete selected asset"):
                with connection() as conn:
                    conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
                flash("Asset deleted.")

elif page == "Work orders":
    title("Work orders", "Prioritize, assign and close out maintenance work.")
    jobs = rows("SELECT * FROM work_orders ORDER BY priority_score DESC,due_at")
    add, register, edit = st.tabs(["Add work order", "Register", "Edit / delete"])
    with add:
        submitted, data = job_form("add")
        if submitted:
            if not data["title"] or not data["allowed_days"]:
                st.error("Job name and at least one allowed day are required.")
            else:
                save_job(data)
                flash("Work order created.")
    with register:
        filter_value = st.selectbox("Filter", ["Open", "All", *JOB_STATUSES])
        filtered = jobs if filter_value == "All" else [j for j in jobs if (j["status"] != "Completed" if filter_value == "Open" else j["status"] == filter_value)]
        st.dataframe(pd.DataFrame([{ "Work order":j["id"], "Job":j["title"], "Asset":j["asset"], "Due":j["due_at"].replace("T", " ")[:16], "Priority":j["priority"], "Crew":j["crew_size"], "Status":j["status"] } for j in filtered]), use_container_width=True, hide_index=True)
    with edit:
        if jobs:
            labels = {j["id"]: f"{j['id']} - {j['title']}" for j in jobs}
            job_id = st.selectbox("Select work order", list(labels), format_func=labels.get)
            job = next(j for j in jobs if j["id"] == job_id)
            submitted, data = job_form(f"edit_{job_id}", job)
            if submitted:
                save_job(data, job_id)
                flash("Work order updated.")
            if st.button("Delete selected work order"):
                with connection() as conn:
                    conn.execute("DELETE FROM work_orders WHERE id=?", (job_id,))
                flash("Work order deleted.")

elif page == "Planning":
    title("Planning", "Turn the maintenance backlog into validated crews and a final weekly plan.")
    jobs = rows("SELECT * FROM work_orders ORDER BY priority_score DESC,due_at")
    open_jobs = [j for j in jobs if j["status"] != "Completed"]
    draft = assignment_rows("Draft")
    final = assignment_rows("Final")
    ready = [j for j in open_jobs if j["scope_ready"] and j["parts_ready"] and j["permits_ready"] and j["shutdown_ready"] and j["released"]]
    overview, readiness, draft_tab, final_tab, board_tab, history_tab, data_tab = st.tabs(["Overview", "Readiness", "Draft", "Final", "Board", "History", "Data"])
    with overview:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Backlog", len(open_jobs), f"{len(ready)} ready")
        c2.metric("Draft assignments", len(draft))
        c3.metric("Final assignments", len(final))
        c4.metric("Completed", len(jobs) - len(open_jobs))
    with readiness:
        st.dataframe(pd.DataFrame([{ "Work order":j["id"], "Job":j["title"], "Scope":bool(j["scope_ready"]), "Parts":bool(j["parts_ready"]), "Permits":bool(j["permits_ready"]), "Shutdown":bool(j["shutdown_ready"]), "Released":bool(j["released"]), "Ready":j in ready } for j in open_jobs]), use_container_width=True, hide_index=True)
    with draft_tab:
        c1, c2, c3 = st.columns(3)
        limit = c1.number_input("Daily limit", 4.0, 12.0, 8.0, .5)
        clear = c2.checkbox("Clear existing draft", True)
        if c3.button("Generate draft", type="primary", use_container_width=True):
            count, warnings = generate_draft(limit, clear)
            st.session_state["warnings"] = warnings
            flash(f"{count} draft assignment(s) generated.")
        for warning in st.session_state.get("warnings", []):
            st.warning(warning)
        st.dataframe(pd.DataFrame([{ "Day":a["day"], "Crew":a["crew_label"], "Work order":a["work_order_id"], "Job":a["title"], "Technicians":a["technicians"].replace(",", ", "), "Hours":a["hours"], "Status":a["status"] } for a in draft]), use_container_width=True, hide_index=True)
        if st.button("Promote all draft assignments"):
            flash(f"{promote_all()} assignment(s) promoted to Final.")
        if draft and st.button("Clear draft schedule"):
            with connection() as conn:
                conn.execute("DELETE FROM assignments WHERE state='Draft'")
                conn.execute("UPDATE work_orders SET status='Pending' WHERE status='Draft Scheduled'")
            flash("Draft schedule cleared.")
    with final_tab:
        st.dataframe(pd.DataFrame([{ "Day":a["day"], "Crew":a["crew_label"], "Work order":a["work_order_id"], "Job":a["title"], "Technicians":a["technicians"].replace(",", ", "), "Hours":a["hours"], "Status":a["status"] } for a in final]), use_container_width=True, hide_index=True)
        if final:
            labels = {a["id"]: f"{a['day']} - {a['crew_label']} - {a['work_order_id']}" for a in final}
            assignment_id = st.selectbox("Select final assignment", list(labels), format_func=labels.get)
            if st.button("Complete selected assignment", type="primary"):
                with connection() as conn:
                    assignment = conn.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()
                    conn.execute("UPDATE assignments SET status='Complete',updated_at=? WHERE id=?", (now(), assignment_id))
                    remaining = conn.execute("SELECT COUNT(*) FROM assignments WHERE work_order_id=? AND status!='Complete'", (assignment["work_order_id"],)).fetchone()[0]
                    if remaining == 0:
                        conn.execute("UPDATE work_orders SET status='Completed',completed_at=?,updated_at=? WHERE id=?", (now(), now(), assignment["work_order_id"]))
                    history(conn, assignment_id, "Completed")
                flash("Assignment completed.")
    with board_tab:
        board_state = st.radio("Board state", ["Draft", "Final"], horizontal=True)
        board(board_state)
    with history_tab:
        completed = [j for j in jobs if j["status"] == "Completed"]
        st.subheader("Completed jobs")
        st.dataframe(pd.DataFrame(completed)[["id", "title", "asset", "completed_at"]] if completed else pd.DataFrame(), use_container_width=True, hide_index=True)
        st.subheader("Schedule audit trail")
        st.dataframe(pd.DataFrame(rows("SELECT * FROM schedule_history ORDER BY changed_at DESC LIMIT 100")), use_container_width=True, hide_index=True)
    with data_tab:
        export_rows = rows("SELECT * FROM work_orders ORDER BY id")
        buffer = io.StringIO()
        if export_rows:
            writer = csv.DictWriter(buffer, fieldnames=list(export_rows[0]))
            writer.writeheader(); writer.writerows(export_rows)
        st.download_button("Download work orders CSV", buffer.getvalue(), "maintainly-work-orders.csv", "text/csv", type="primary")

else:
    title("Reports", "Turn maintenance activity into clear operational decisions.")
    jobs = rows("SELECT * FROM work_orders")
    assignments = rows("SELECT * FROM assignments")
    completed = [j for j in jobs if j["status"] == "Completed"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total work orders", len(jobs))
    c2.metric("Completed", len(completed))
    c3.metric("Completion rate", f"{len(completed) / len(jobs) * 100 if jobs else 0:.0f}%")
    c4.metric("Scheduled hours", f"{sum(a['hours'] for a in assignments):.1f}h")
    left, right = st.columns(2)
    with left:
        st.subheader("Jobs by status")
        if jobs:
            st.bar_chart(pd.Series([j["status"] for j in jobs]).value_counts())
    with right:
        st.subheader("Jobs by department")
        if jobs:
            st.bar_chart(pd.Series([j["department"] for j in jobs]).value_counts())
