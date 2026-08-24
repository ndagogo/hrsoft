"""Learning & Development views."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import permission_required, user_has_permission
from apps.employees.models import Employee
from apps.notifications.services import deliver_notification

from .forms import (
    AssessmentForm,
    AttendanceForm,
    CategoryForm,
    CompetencyForm,
    CourseForm,
    CourseLessonForm,
    EmployeeCompetencyForm,
    EnrollmentForm,
    EvaluationForm,
    InstructorForm,
    PositionCompetencyForm,
    ProgramForm,
    ProviderForm,
    SessionForm,
    TrainingRequestForm,
)
from .models import (
    CertificateStatus,
    Competency,
    Course,
    CourseLesson,
    EnrollmentStatus,
    LearningPath,
    RequestStatus,
    TrainingApproval,
    TrainingAssignment,
    TrainingAttendance,
    TrainingBudget,
    TrainingCertificate,
    TrainingEnrollment,
    TrainingExpense,
    TrainingNeed,
    TrainingProgram,
    TrainingProgramCourse,
    TrainingProvider,
    TrainingInstructor,
    TrainingCategory,
    TrainingRequest,
    TrainingSchedule,
    PositionCompetency,
    EmployeeCompetency,
)
from . import services


def _employee_for(user):
    return getattr(user, "employee_profile", None)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
@permission_required("view_training")
def dashboard(request):
    services.refresh_overdue_assignments()
    services.refresh_expired_certificates()
    stats = services.dashboard_stats()
    stats["pending_requests"] = TrainingRequest.objects.filter(
        status__in=[
            RequestStatus.SUBMITTED,
            RequestStatus.MANAGER_REVIEW,
            RequestStatus.HR_REVIEW,
            RequestStatus.FINANCE_REVIEW,
        ]
    ).count()

    today = timezone.localdate()
    upcoming = TrainingSchedule.objects.filter(
        start_date__gte=today, status="published"
    ).select_related("course")[:8]
    overdue = TrainingAssignment.objects.filter(
        status=TrainingAssignment.AssignmentStatus.OVERDUE
    ).select_related("employee__user", "course")[:10]
    expiring = TrainingCertificate.objects.filter(
        status=CertificateStatus.ACTIVE,
        expiry_date__isnull=False,
        expiry_date__lte=today + timedelta(days=30),
        expiry_date__gte=today,
    ).select_related("enrollment__employee__user", "enrollment__schedule__course")[:10]
    open_needs = TrainingNeed.objects.filter(status=TrainingNeed.NeedStatus.OPEN).select_related(
        "employee__user", "competency", "recommended_course"
    )[:10]

    by_dept = (
        TrainingEnrollment.objects.filter(status=EnrollmentStatus.COMPLETED)
        .values("employee__department__name")
        .annotate(c=Count("id"))
        .order_by("-c")[:8]
    )
    my_employee = _employee_for(request.user)
    my_assignments = []
    my_gaps = []
    if my_employee:
        my_assignments = TrainingAssignment.objects.filter(
            employee=my_employee
        ).exclude(status=TrainingAssignment.AssignmentStatus.COMPLETED).select_related("course")[:8]
        my_gaps = services.competency_gaps_for_employee(my_employee)[:5]

    return render(
        request,
        "training/dashboard.html",
        {
            "stats": stats,
            "upcoming": upcoming,
            "overdue": overdue,
            "expiring": expiring,
            "open_needs": open_needs,
            "by_dept": by_dept,
            "my_assignments": my_assignments,
            "my_gaps": my_gaps,
            "can_manage": user_has_permission(request.user, "manage_training"),
        },
    )


# Keep old name as alias
training_overview = dashboard


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@login_required
@permission_required("view_training")
def catalogue(request):
    qs = (
        Course.objects.filter(is_archived=False)
        .select_related("category", "provider_org")
        .annotate(video_lesson_count=Count("lessons", filter=Q(lessons__is_published=True)))
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    if request.GET.get("mandatory") == "1":
        qs = qs.filter(is_mandatory=True)
    if request.GET.get("category"):
        qs = qs.filter(category_id=request.GET["category"])
    return render(
        request,
        "training/catalogue.html",
        {
            "courses": qs,
            "categories": TrainingCategory.objects.filter(is_active=True),
            "can_manage": user_has_permission(request.user, "manage_training"),
            "q": q,
        },
    )


@login_required
@permission_required("manage_training")
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = form.save()
        messages.success(request, f"Course '{course.title}' created.")
        return redirect("training:catalogue")
    return render(request, "training/course_form.html", {"form": form, "title": "New Course"})


@login_required
@permission_required("manage_training")
def course_edit(request, pk):
    course = get_object_or_404(Course, pk=pk)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Course updated.")
        return redirect("training:course_detail", pk=pk)
    return render(request, "training/course_form.html", {"form": form, "title": f"Edit {course.title}", "course": course})


@login_required
@permission_required("view_training")
def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("category", "provider_org"), pk=pk)
    sessions = course.schedules.order_by("-start_date")[:20]
    lessons = course.lessons.all()
    can_manage = user_has_permission(request.user, "manage_training")
    lesson_form = CourseLessonForm() if can_manage else None
    employee = _employee_for(request.user)
    video_summary = services.course_video_progress_summary(course, employee) if employee else None
    return render(
        request,
        "training/course_detail.html",
        {
            "course": course,
            "sessions": sessions,
            "lessons": lessons,
            "lesson_form": lesson_form,
            "video_summary": video_summary,
            "competencies": course.competency_links.select_related("competency"),
            "can_manage": can_manage,
        },
    )


@login_required
@permission_required("manage_training")
@require_POST
def lesson_create(request, pk):
    course = get_object_or_404(Course, pk=pk)
    form = CourseLessonForm(request.POST, request.FILES)
    if form.is_valid():
        lesson = form.save(commit=False)
        lesson.course = course
        lesson.uploaded_by = request.user
        if not lesson.sort_order:
            lesson.sort_order = (course.lessons.count() + 1) * 10
        lesson.save()
        if course.delivery_method not in ("elearning", "blended"):
            course.delivery_method = "elearning"
            course.save(update_fields=["delivery_method", "updated_at"])
        messages.success(request, f"Video lesson '{lesson.title}' uploaded.")
    else:
        for err in form.non_field_errors():
            messages.error(request, err)
        for field, errs in form.errors.items():
            if field == "__all__":
                continue
            for err in errs:
                messages.error(request, f"{field}: {err}")
    return redirect("training:course_detail", pk=pk)


@login_required
@permission_required("manage_training")
@require_POST
def lesson_delete(request, pk, lesson_id):
    course = get_object_or_404(Course, pk=pk)
    lesson = get_object_or_404(CourseLesson, pk=lesson_id, course=course)
    title = lesson.title
    if lesson.video:
        lesson.video.delete(save=False)
    lesson.delete()
    messages.success(request, f"Removed lesson '{title}'.")
    return redirect("training:course_detail", pk=pk)


@login_required
def watch_course(request, pk):
    """Staff player for self-paced video courses."""
    course = get_object_or_404(
        Course.objects.filter(is_active=True, is_archived=False).prefetch_related("lessons"),
        pk=pk,
    )
    employee = _employee_for(request.user)
    if not employee:
        messages.info(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")
    lessons = list(course.lessons.filter(is_published=True))
    if not lessons:
        messages.warning(request, "This course has no published video lessons yet.")
        return redirect("training:course_detail", pk=pk)

    services.ensure_elearning_enrollment(course, employee, user=request.user)
    summary = services.course_video_progress_summary(course, employee)

    lesson_id = request.GET.get("lesson")
    current = None
    if lesson_id:
        current = next((l for l in lessons if str(l.pk) == str(lesson_id)), None)
    if current is None:
        # Resume first incomplete lesson
        for row in summary["lessons"]:
            if not row["completed"]:
                current = row["lesson"]
                break
        current = current or lessons[0]

    progress_map = {row["lesson"].pk: row for row in summary["lessons"]}
    current_row = progress_map.get(current.pk) or {}
    return render(
        request,
        "training/watch_course.html",
        {
            "course": course,
            "lessons": lessons,
            "current": current,
            "summary": summary,
            "progress_map": progress_map,
            "current_watched_seconds": int(current_row.get("watched_seconds") or 0),
            "can_manage": user_has_permission(request.user, "manage_training"),
        },
    )


@login_required
@require_POST
def lesson_progress(request, pk, lesson_id):
    """AJAX endpoint: save watch position / completion for a lesson."""
    import json

    course = get_object_or_404(Course, pk=pk, is_active=True, is_archived=False)
    lesson = get_object_or_404(CourseLesson, pk=lesson_id, course=course, is_published=True)
    employee = _employee_for(request.user)
    if not employee:
        return JsonResponse({"ok": False, "detail": "No employee profile."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = request.POST

    watched = int(payload.get("watched_seconds") or 0)
    duration = payload.get("duration_seconds")
    duration = int(duration) if duration not in (None, "", False) else None
    completed = bool(payload.get("completed"))

    progress = services.record_lesson_progress(
        lesson,
        employee,
        watched_seconds=watched,
        duration_seconds=duration,
        completed=completed,
        user=request.user,
    )
    summary = services.course_video_progress_summary(course, employee)
    return JsonResponse(
        {
            "ok": True,
            "lesson_id": lesson.pk,
            "percent": progress.percent,
            "completed": progress.completed,
            "course_percent": summary["percent"],
            "course_completed": summary["completed"] >= summary["total"] > 0,
        }
    )


# ---------------------------------------------------------------------------
# Programs / Sessions
# ---------------------------------------------------------------------------

@login_required
@permission_required("view_training")
def programs(request):
    return render(
        request,
        "training/programs.html",
        {
            "programs": TrainingProgram.objects.prefetch_related("program_courses__course"),
            "all_courses": Course.objects.filter(is_active=True, is_archived=False).order_by("title"),
            "can_manage": user_has_permission(request.user, "manage_training"),
            "form": ProgramForm() if user_has_permission(request.user, "manage_training") else None,
        },
    )


@login_required
@permission_required("manage_training")
def program_create(request):
    form = ProgramForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        prog = form.save()
        messages.success(request, f"Program '{prog.title}' created.")
    return redirect("training:programs")


@login_required
@permission_required("manage_training")
def program_add_course(request, pk):
    prog = get_object_or_404(TrainingProgram, pk=pk)
    course_id = request.POST.get("course")
    if course_id:
        course = get_object_or_404(Course, pk=course_id)
        seq = prog.program_courses.count() + 1
        TrainingProgramCourse.objects.get_or_create(
            program=prog, course=course, defaults={"sequence": seq}
        )
        messages.success(request, f"Added {course.title} to program.")
    return redirect("training:programs")


@login_required
@permission_required("view_training")
def sessions(request):
    qs = TrainingSchedule.objects.select_related("course", "instructor").order_by("-start_date")
    if request.GET.get("upcoming") == "1":
        qs = qs.filter(start_date__gte=timezone.localdate())
    return render(
        request,
        "training/sessions.html",
        {"sessions": qs[:100], "can_manage": user_has_permission(request.user, "manage_training")},
    )


@login_required
@permission_required("manage_training")
def session_create(request):
    form = SessionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        session = form.save()
        messages.success(request, "Training session scheduled.")
        return redirect("training:session_detail", pk=session.pk)
    return render(request, "training/session_form.html", {"form": form, "title": "Schedule Session"})


@login_required
@permission_required("view_training")
def session_detail(request, pk):
    session = get_object_or_404(
        TrainingSchedule.objects.select_related("course", "instructor"), pk=pk
    )
    enrollments = session.enrollments.select_related("employee__user").order_by("status", "employee__employee_id")
    return render(
        request,
        "training/session_detail.html",
        {
            "session": session,
            "enrollments": enrollments,
            "enroll_form": EnrollmentForm(initial={"schedule": session})
            if user_has_permission(request.user, "manage_training")
            else None,
            "can_manage": user_has_permission(request.user, "manage_training"),
        },
    )


# ---------------------------------------------------------------------------
# Enrollment / attendance / assessment
# ---------------------------------------------------------------------------

@login_required
@permission_required("manage_training")
def enroll(request):
    if request.method != "POST":
        return redirect("training:sessions")
    form = EnrollmentForm(request.POST)
    if form.is_valid():
        enrollment, _ = services.enroll_employee(
            form.cleaned_data["schedule"],
            form.cleaned_data["employee"],
            user=request.user,
        )
        messages.success(
            request,
            f"{form.cleaned_data['employee']} → {enrollment.get_status_display()}.",
        )
        return redirect("training:session_detail", pk=form.cleaned_data["schedule"].pk)
    messages.error(request, "Could not enroll employee.")
    return redirect("training:sessions")


@login_required
@permission_required("manage_training")
def mark_attendance(request, enrollment_id):
    enrollment = get_object_or_404(TrainingEnrollment, pk=enrollment_id)
    form = AttendanceForm(request.POST or None, initial={"session_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        att = form.save(commit=False)
        att.enrollment = enrollment
        att.recorded_by = request.user
        att.save()
        if enrollment.status == EnrollmentStatus.ENROLLED:
            enrollment.status = EnrollmentStatus.ATTENDED
            enrollment.save(update_fields=["status", "updated_at"])
        messages.success(request, "Attendance recorded.")
        return redirect("training:session_detail", pk=enrollment.schedule_id)
    return render(
        request,
        "training/simple_form.html",
        {"form": form, "title": f"Attendance — {enrollment.employee}", "action": ""},
    )


@login_required
@permission_required("manage_training")
def record_assessment_view(request, enrollment_id):
    enrollment = get_object_or_404(TrainingEnrollment, pk=enrollment_id)
    form = AssessmentForm(request.POST or None, initial={"max_score": 100})
    if request.method == "POST" and form.is_valid():
        services.record_assessment(
            enrollment,
            form.cleaned_data["score"],
            assessment_type=form.cleaned_data["assessment_type"],
            max_score=form.cleaned_data["max_score"],
            user=request.user,
            notes=form.cleaned_data.get("notes") or "",
        )
        messages.success(request, "Assessment recorded.")
        return redirect("training:session_detail", pk=enrollment.schedule_id)
    return render(
        request,
        "training/simple_form.html",
        {"form": form, "title": f"Assessment — {enrollment.employee}"},
    )


@login_required
@permission_required("manage_training")
def complete_enrollment(request, enrollment_id):
    enrollment = get_object_or_404(TrainingEnrollment, pk=enrollment_id)
    if request.method == "POST":
        ok = services.maybe_complete_enrollment(enrollment, user=request.user)
        if ok:
            messages.success(request, "Enrollment marked complete; certificate issued if configured.")
        else:
            messages.warning(
                request,
                "Completion requirements not met (attendance and/or assessment).",
            )
    return redirect("training:session_detail", pk=enrollment.schedule_id)


# ---------------------------------------------------------------------------
# My learning / requests
# ---------------------------------------------------------------------------

@login_required
def my_learning(request):
    employee = _employee_for(request.user)
    if not employee:
        messages.info(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")
    enrollments = TrainingEnrollment.objects.filter(employee=employee).select_related(
        "schedule__course"
    )
    assignments = TrainingAssignment.objects.filter(employee=employee).select_related("course")
    certificates = TrainingCertificate.objects.filter(
        enrollment__employee=employee
    ).select_related("enrollment__schedule__course")
    gaps = services.competency_gaps_for_employee(employee)
    video_courses = []
    for course in (
        Course.objects.filter(is_active=True, is_archived=False, lessons__is_published=True)
        .distinct()
        .prefetch_related("lessons")
        .order_by("title")
    ):
        video_courses.append(
            {
                "course": course,
                "progress": services.course_video_progress_summary(course, employee),
            }
        )
    return render(
        request,
        "training/my_learning.html",
        {
            "employee": employee,
            "enrollments": enrollments,
            "assignments": assignments,
            "certificates": certificates,
            "gaps": gaps,
            "video_courses": video_courses,
            "request_form": TrainingRequestForm(),
            "can_manage": user_has_permission(request.user, "manage_training"),
        },
    )


@login_required
def request_training(request):
    employee = _employee_for(request.user)
    if not employee:
        messages.error(request, "No employee profile found.")
        return redirect("dashboard:router")
    form = TrainingRequestForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        req = form.save(commit=False)
        req.employee = employee
        if req.course and not req.course_title:
            req.course_title = req.course.title
        req.status = RequestStatus.MANAGER_REVIEW
        req.current_step = "manager"
        req.save()
        TrainingApproval.objects.create(request=req, step="manager", decision="pending")
        if employee.manager_id and employee.manager.user_id:
            deliver_notification(
                employee.manager.user,
                "Training request pending your approval",
                f"{employee} requested {req.course_title or 'training'}.",
                category="system",
                link="/training/approvals/",
                channels=[],
            )
        messages.success(request, "Training request submitted.")
        return redirect("training:my_learning")
    return render(request, "training/request_form.html", {"form": form})


@login_required
@permission_required("manage_training")
def approvals(request):
    pending = TrainingRequest.objects.exclude(
        status__in=[
            RequestStatus.APPROVED,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
            RequestStatus.WITHDRAWN,
            RequestStatus.COMPLETED,
        ]
    ).select_related("employee__user", "course")
    return render(request, "training/approvals.html", {"requests": pending})


@login_required
def approve_request(request, pk):
    req = get_object_or_404(TrainingRequest, pk=pk)
    if request.method != "POST":
        return redirect("training:approvals")

    decision = request.POST.get("decision")
    note = request.POST.get("note", "")
    can_hr = user_has_permission(request.user, "manage_training")
    employee = _employee_for(request.user)
    is_manager = bool(
        employee
        and req.employee.manager_id == employee.pk
    )

    if not (can_hr or is_manager):
        messages.error(request, "You are not allowed to approve this request.")
        return redirect("dashboard:router")

    step = req.current_step or "manager"
    TrainingApproval.objects.create(
        request=req,
        step=step,
        approver=request.user,
        decision="approved" if decision == "approved" else "rejected",
        note=note,
        decided_at=timezone.now(),
    )

    if decision != "approved":
        req.status = RequestStatus.REJECTED
        req.save(update_fields=["status", "updated_at"])
        deliver_notification(
            req.employee.user,
            "Training request rejected",
            note or "Your training request was rejected.",
            category="system",
            link="/training/my/",
            channels=[],
        )
        messages.info(request, "Request rejected.")
        return redirect("training:approvals" if can_hr else "training:my_learning")

    # Simple configurable path: manager → HR → approved
    if step == "manager" and not can_hr:
        req.status = RequestStatus.HR_REVIEW
        req.current_step = "hr"
        req.save(update_fields=["status", "current_step", "updated_at"])
        messages.success(request, "Approved — forwarded to HR.")
    else:
        req.status = RequestStatus.APPROVED
        req.current_step = "done"
        req.save(update_fields=["status", "current_step", "updated_at"])
        # Auto-enroll into next published session if course selected
        if req.course_id:
            session = (
                TrainingSchedule.objects.filter(
                    course=req.course, status="published", start_date__gte=timezone.localdate()
                )
                .order_by("start_date")
                .first()
            )
            if session:
                services.enroll_employee(session, req.employee, user=request.user)
                req.status = RequestStatus.ENROLLED
                req.schedule = session
                req.save(update_fields=["status", "schedule", "updated_at"])
        deliver_notification(
            req.employee.user,
            "Training request approved",
            f"Your request for {req.course_title or 'training'} was approved.",
            category="system",
            link="/training/my/",
            channels=[],
        )
        messages.success(request, "Request approved.")
    return redirect("training:approvals" if can_hr else "training:my_learning")


# ---------------------------------------------------------------------------
# Competencies / needs / certificates / calendar / reports
# ---------------------------------------------------------------------------

@login_required
@permission_required("view_training")
def competencies(request):
    return render(
        request,
        "training/competencies.html",
        {
            "competencies": Competency.objects.filter(is_active=True),
            "position_reqs": PositionCompetency.objects.select_related("designation", "competency")[:100],
            "can_manage": user_has_permission(request.user, "manage_training"),
            "comp_form": CompetencyForm() if user_has_permission(request.user, "manage_training") else None,
            "pos_form": PositionCompetencyForm() if user_has_permission(request.user, "manage_training") else None,
            "emp_form": EmployeeCompetencyForm() if user_has_permission(request.user, "manage_training") else None,
        },
    )


@login_required
@permission_required("manage_training")
def competency_create(request):
    form = CompetencyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Competency created.")
    return redirect("training:competencies")


@login_required
@permission_required("manage_training")
def position_competency_create(request):
    form = PositionCompetencyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Position competency requirement saved.")
    return redirect("training:competencies")


@login_required
@permission_required("manage_training")
def employee_competency_set(request):
    form = EmployeeCompetencyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ec = form.save(commit=False)
        ec.source = "manual"
        ec.assessed_at = timezone.localdate()
        ec.assessed_by = request.user
        ec.save()
        services.sync_training_needs_from_gaps(ec.employee, user=request.user)
        messages.success(request, "Employee competency updated; training needs refreshed.")
    return redirect("training:competencies")


@login_required
@permission_required("view_training")
def needs(request):
    qs = TrainingNeed.objects.filter(status=TrainingNeed.NeedStatus.OPEN).select_related(
        "employee__user", "competency", "recommended_course"
    )
    return render(
        request,
        "training/needs.html",
        {"needs": qs, "can_manage": user_has_permission(request.user, "manage_training")},
    )


@login_required
@permission_required("manage_training")
def scan_gaps(request):
    if request.method == "POST":
        count = 0
        for emp in Employee.objects.filter(status="active", designation__isnull=False):
            count += services.sync_training_needs_from_gaps(emp, user=request.user)
        messages.success(request, f"Gap analysis complete. {count} new training need(s) opened.")
    return redirect("training:needs")


@login_required
@permission_required("view_training")
def certificates(request):
    qs = TrainingCertificate.objects.select_related(
        "enrollment__employee__user", "enrollment__schedule__course"
    )
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return render(request, "training/certificates.html", {"certificates": qs[:200]})


@login_required
@permission_required("view_training")
def calendar(request):
    import json

    sessions = TrainingSchedule.objects.filter(
        start_date__gte=timezone.localdate() - timedelta(days=30)
    ).select_related("course")[:100]
    events = [
        {
            "title": s.title or s.course.title,
            "start": s.start_date.isoformat(),
            "end": (s.end_date + timedelta(days=1)).isoformat(),
            "url": f"/training/sessions/{s.pk}/",
        }
        for s in sessions
    ]
    return render(
        request,
        "training/calendar.html",
        {"events_json": json.dumps(events), "sessions": sessions},
    )


@login_required
@permission_required("view_training")
def reports(request):
    today = timezone.localdate()
    compliance = {
        "assigned": TrainingAssignment.objects.filter(is_mandatory=True).count(),
        "completed": TrainingAssignment.objects.filter(
            is_mandatory=True, status=TrainingAssignment.AssignmentStatus.COMPLETED
        ).count(),
        "overdue": TrainingAssignment.objects.filter(
            is_mandatory=True, status=TrainingAssignment.AssignmentStatus.OVERDUE
        ).count(),
    }
    costs = (
        TrainingExpense.objects.values("department__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:10]
    )
    dept_hours = (
        TrainingEnrollment.objects.filter(status=EnrollmentStatus.COMPLETED)
        .values("employee__department__name")
        .annotate(hours=Sum("schedule__course__duration_hours"), people=Count("employee", distinct=True))
        .order_by("-hours")[:10]
    )
    return render(
        request,
        "training/reports.html",
        {
            "compliance": compliance,
            "costs": costs,
            "dept_hours": dept_hours,
            "stats": services.dashboard_stats(),
            "year": today.year,
        },
    )


@login_required
@permission_required("manage_training")
def providers(request):
    form = ProviderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Provider saved.")
        return redirect("training:providers")
    return render(
        request,
        "training/providers.html",
        {"providers": TrainingProvider.objects.all(), "form": form, "instructors": TrainingInstructor.objects.all(), "instructor_form": InstructorForm()},
    )


@login_required
@permission_required("manage_training")
def instructor_create(request):
    form = InstructorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Instructor saved.")
    return redirect("training:providers")


@login_required
@permission_required("manage_training")
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category created.")
        return redirect("training:catalogue")
    return render(request, "training/simple_form.html", {"form": form, "title": "New Category"})


@login_required
def evaluate_training(request, enrollment_id):
    enrollment = get_object_or_404(TrainingEnrollment, pk=enrollment_id)
    employee = _employee_for(request.user)
    if not (
        user_has_permission(request.user, "manage_training")
        or (employee and enrollment.employee_id == employee.pk)
    ):
        messages.error(request, "Not allowed.")
        return redirect("training:my_learning")
    if hasattr(enrollment, "evaluation"):
        messages.info(request, "Evaluation already submitted.")
        return redirect("training:my_learning")
    form = EvaluationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ev = form.save(commit=False)
        ev.enrollment = enrollment
        ev.save()
        messages.success(request, "Thank you for your evaluation.")
        return redirect("training:my_learning")
    return render(
        request,
        "training/simple_form.html",
        {"form": form, "title": f"Evaluate — {enrollment.schedule.course.title}"},
    )
