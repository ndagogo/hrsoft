# Northbridge HRMS — Enterprise HR Management System

A full-featured HR platform built with **Django** (backend) and **Bootstrap 5**
(frontend), featuring role-based dashboards, biometric attendance integration
(HikVision-compatible), leave management, payroll, and a granular
role/permission builder that admins control entirely through the UI.

---

## ✨ Features

- **5 role-aware dashboards** — Admin, HR Manager, Department Manager, Payroll
  Officer, Employee — each with its own KPI cards and Chart.js visualisations.
- **Role-Based Access Control (RBAC)** — Admins create roles and assign
  granular permissions through a checkbox-matrix "role builder" UI. No code
  changes needed to add a new role or tweak access.
- **Biometric attendance (HikVision)** — supports both:
  - **Pull mode**: Django polls the device's ISAPI endpoint on a schedule.
  - **Push mode**: the device POSTs events to a webhook in real time.
  - Raw punches are kept immutable (`RawPunchLog`) and rolled up into daily
    `AttendanceRecord`s, with manual override for when biometric data is
    missing.
- **Leave management** — configurable leave types, employee self-service
  requests, manager/HR approval queue, automatic balance deduction.
- **Payroll** — period-based payroll runs that pull attendance data (lateness,
  absences) directly into payslip deductions, with manual adjustments and
  printable payslips.
- **Audit log** — every state-changing request is logged with user, IP, path
  and timestamp.
- **Modal-driven forms** throughout (Bootstrap modals + a small reusable AJAX
  helper), so most CRUD doesn't require a full page navigation.
- **Demo data** — one command populates ~40 employees, 60 days of biometric
  attendance history, leave requests in every status, and 3 payroll periods.

---

## 🏗 Architecture

```
hrms_project/
├── config/                # settings, urls, wsgi/asgi
├── apps/
│   ├── accounts/          # custom User model, login/profile/password
│   ├── rbac/               # Role, Permission, AuditLog + role builder UI
│   ├── employees/          # Department, Designation, Employee profile
│   ├── attendance/         # BiometricDevice, RawPunchLog, AttendanceRecord
│   │                        #   + apps/attendance/biometrics.py (HikVision integration)
│   ├── leave/               # LeaveType, LeaveRequest + approval workflow
│   ├── payroll/             # PayrollPeriod, Payslip + payroll run logic
│   ├── dashboard/           # role-aware dashboard router + views
│   └── core/                # shared middleware, permission decorators, context processors
├── templates/               # all HTML, organised by app
├── static/css/hrms.css      # design system (see below)
├── static/js/hrms.js        # sidebar toggle + generic AJAX modal helper
└── fixtures/                 # (optional) JSON fixtures if you prefer over the seed command
```

### Design system

Ink-navy + amber palette, **Space Grotesk** (headings) + **Inter** (body),
with a "punch-card" notch motif on KPI stat cards — a nod to physical
timecards, fitting for an attendance-first HR system. All design tokens live
as CSS variables at the top of `static/css/hrms.css`.

---

## 🚀 Getting started

### 1. Prerequisites
- Python 3.11+
- PostgreSQL 14+ (recommended) — or SQLite for a zero-setup trial run

### 2. Install

```bash
git clone <this-repo> hrms_project && cd hrms_project
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then edit .env
```

### 3. Database

**Option A — PostgreSQL (recommended, production-grade):**

```bash
createdb hrms_db                                       # or via psql/pgAdmin
createuser hrms_user --pwprompt                         # set password to match .env
```
Make sure `.env` has `DJANGO_DB_ENGINE=postgres` (the default) with matching
`DB_NAME` / `DB_USER` / `DB_PASSWORD`.

**Option B — SQLite (fastest way to try it out):**
Set `DJANGO_DB_ENGINE=sqlite` in `.env`. No further setup needed.

### 4. Migrate, seed demo data, and run

```bash
python manage.py migrate
python manage.py seed_demo_data          # populates roles, employees, attendance, leave, payroll
python manage.py createsuperuser         # optional: an additional Django admin account
python manage.py runserver
```

Visit **http://127.0.0.1:8000** and sign in with any of the demo accounts
(password for all: `Demo@1234`):

| Username          | Role               |
|-------------------|--------------------|
| `admin`           | Admin (superuser)  |
| `hr.manager`      | HR Manager         |
| `dept.manager`     | Department Manager |
| `payroll.officer` | Payroll Officer    |
| any seeded `firstname.lastname` | Employee |

(Run `python manage.py seed_demo_data --employees 50 --days 90` to control
how much demo data is generated.)

---

## 🔌 HikVision biometric device integration

The platform supports **both** integration modes, configured per-device under
**Attendance → Biometric Devices** in the UI (Admin/HR Manager only):

### Pull mode (Django polls the device)
1. Register the device with its IP, ISAPI port (usually 80), and
   admin credentials (HikVision uses HTTP Digest auth by default).
2. Set **Connection mode** to "Pull" or "Both".
3. Run the sync on a schedule via cron (see `scripts/biometric_sync.cron`):
   ```bash
   * * * * * cd /path/to/project && venv/bin/python manage.py sync_biometric_devices
   ```
   Or trigger it on-demand with the **"Sync now"** button on the device card.

This calls `POST /ISAPI/AccessControl/AcsEvent?format=json` on the device to
fetch new access-control events since the last sync.

### Push mode (device posts events to us)
1. Register the device (IP address is used to identify incoming webhook
   calls) and copy its **webhook token** from the device card.
2. On the HikVision device's own web UI: **Configuration → Network →
   Advanced Settings → HTTP Listening** (or configure an event-linkage
   "notify surveillance center" rule), and set the destination URL to:
   ```
   http://<your-server>/api/biometric/webhook/?token=<device-webhook-token>
   ```
3. Events arrive in real time and are matched to employees by the
   `biometric_id` field on their Employee profile (must match the device's
   enrolled Employee No.).

Both modes write to the same `RawPunchLog` table and roll up into daily
`AttendanceRecord`s — see `apps/attendance/biometrics.py` for the full
implementation and inline documentation of the HikVision payload shapes.

> **Note:** the demo device registered by `seed_demo_data` uses a fake IP
> (`192.168.1.201`) and synthetic punch history — it's there so the UI has
> something to show, not a live connection. Point a real device at your
> server's IP and update the device record to go live.

---

## 🔐 Roles & permissions

Admins manage everything through **Roles & Permissions** in the sidebar:

1. **Permissions** are granular, named privileges (`manage_payroll`,
   `approve_leave`, etc.), grouped by category. Admins can add custom ones.
2. **Roles** bundle permissions and determine which dashboard a user lands on
   (`dashboard_key`: admin / hr / manager / payroll / employee).
3. The **Role Builder** (a checkbox matrix grouped by category) is where an
   admin assigns/revokes permissions for a role — changes apply to every user
   with that role immediately.
4. Assign a role to a user when creating/editing their account under
   **Employees**.

System roles (Admin, HR Manager, Department Manager, Payroll Officer,
Employee) ship pre-configured but are fully editable — including by deleting
or completely re-purposing them, with one safety prompt for system roles to
prevent accidental lockouts.

---

## 🧪 Notes on payroll calculations

Payroll is intentionally simple/illustrative (flat 7.5% tax, 8% pension,
₦1,000 per late day) so it's easy to see and adjust — see
`apps/payroll/views.py::run_payroll`. Swap in your real tax bands / pension
rules there; the rest of the pipeline (pulling attendance data, generating
payslips, printable payslip view) doesn't need to change.

---

## 📦 Deployment notes

- Set `DJANGO_DEBUG=False` and a strong `DJANGO_SECRET_KEY` in production.
- `whitenoise` and `gunicorn` are included in `requirements.txt` for a
  straightforward production static-file + WSGI setup.
- Run `python manage.py collectstatic` before deploying.
- The webhook endpoint (`/api/biometric/webhook/`) is CSRF-exempt by
  necessity (the device can't supply a Django CSRF token) but is protected by
  a per-device shared secret token plus source-IP matching — make sure your
  firewall only allows the expected device IPs to reach it in production.
