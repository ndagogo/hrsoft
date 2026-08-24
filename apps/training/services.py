"""Business logic for Learning & Development."""
from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.employees.models import Employee

from .models import (
    CertificateStatus,
    Competency,
    Course,
    CourseCompetency,
    CourseLesson,
    CourseLessonProgress,
    EmployeeCompetency,
    EnrollmentStatus,
    PositionCompetency,
    SessionStatus,
    TrainingAssignment,
    TrainingAssignmentRule,
    TrainingAttendance,
    TrainingAuditLog,
    TrainingCertificate,
    TrainingEnrollment,
    TrainingNeed,
    TrainingSchedule,
)

ELEARNING_SCHEDULE_TITLE = "Self-paced e-learning"
WATCH_COMPLETE_PERCENT = 90


def audit(actor, action, object_type="", object_id="", detail=""):
    TrainingAuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id or ""),
        detail=detail[:2000],
    )


def enroll_employee(schedule: TrainingSchedule, employee: Employee, *, user=None, force=False):
    """Enroll or waitlist an employee on a session."""
    existing = TrainingEnrollment.objects.filter(schedule=schedule, employee=employee).first()
    if existing and existing.status not in (
        EnrollmentStatus.CANCELLED,
        EnrollmentStatus.WITHDRAWN,
    ):
        return existing, False

    if schedule.is_full and not force:
        position = schedule.waitlisted_count + 1
        enrollment = TrainingEnrollment.objects.create(
            schedule=schedule,
            employee=employee,
            status=EnrollmentStatus.WAITLISTED,
            waitlist_position=position,
            enrolled_by=user if getattr(user, "is_authenticated", False) else None,
        )
        audit(user, "waitlisted", "TrainingEnrollment", enrollment.pk, f"{employee} on {schedule}")
        return enrollment, True

    if existing:
        existing.status = EnrollmentStatus.ENROLLED
        existing.waitlist_position = None
        existing.enrolled_by = user if getattr(user, "is_authenticated", False) else None
        existing.save()
        enrollment = existing
        created = False
    else:
        enrollment = TrainingEnrollment.objects.create(
            schedule=schedule,
            employee=employee,
            status=EnrollmentStatus.ENROLLED,
            enrolled_by=user if getattr(user, "is_authenticated", False) else None,
        )
        created = True
    audit(user, "enrolled", "TrainingEnrollment", enrollment.pk, f"{employee} on {schedule}")
    return enrollment, created


@transaction.atomic
def promote_from_waitlist(schedule: TrainingSchedule, *, user=None):
    """Move the next waitlisted employee into an open seat."""
    if schedule.is_full:
        return None
    nxt = (
        schedule.enrollments.filter(status=EnrollmentStatus.WAITLISTED)
        .order_by("waitlist_position", "enrolled_at")
        .first()
    )
    if not nxt:
        return None
    nxt.status = EnrollmentStatus.ENROLLED
    nxt.waitlist_position = None
    nxt.save(update_fields=["status", "waitlist_position", "updated_at"])
    audit(user, "waitlist_promoted", "TrainingEnrollment", nxt.pk)
    return nxt


def record_assessment(enrollment, score, *, assessment_type="final", max_score=100, user=None, notes=""):
    from .models import AssessmentType, TrainingAssessment

    course = enrollment.schedule.course
    pct = (Decimal(score) / Decimal(max_score)) * Decimal("100") if max_score else Decimal("0")
    passed = pct >= Decimal(course.pass_mark)
    attempt = enrollment.assessments.filter(assessment_type=assessment_type).count() + 1
    result = TrainingAssessment.objects.create(
        enrollment=enrollment,
        assessment_type=assessment_type,
        score=score,
        max_score=max_score,
        passed=passed,
        attempt_number=attempt,
        notes=notes,
        assessed_by=user if getattr(user, "is_authenticated", False) else None,
    )
    if assessment_type == AssessmentType.FINAL:
        enrollment.evaluation_score = pct
        if passed:
            maybe_complete_enrollment(enrollment, user=user)
        else:
            enrollment.status = EnrollmentStatus.FAILED
            enrollment.save(update_fields=["evaluation_score", "status", "updated_at"])
    return result


def attendance_complete(enrollment) -> bool:
    course = enrollment.schedule.course
    if not course.require_full_attendance:
        return True
    days = enrollment.attendance_days.all()
    if not days.exists():
        # If no day records yet, do not block completion on attendance alone
        return True
    return not days.exclude(
        mark__in=["present", "late", "excused"]
    ).exists()


def maybe_complete_enrollment(enrollment, *, user=None):
    """Mark completed only when configured completion rules pass."""
    course = enrollment.schedule.course
    if course.require_full_attendance and not attendance_complete(enrollment):
        return False
    if course.require_assessment:
        final_ok = enrollment.assessments.filter(assessment_type="final", passed=True).exists()
        if not final_ok:
            return False

    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.completion_date = timezone.localdate()
    enrollment.save(update_fields=["status", "completion_date", "updated_at"])
    if course.issues_certificate:
        issue_certificate(enrollment, user=user)
    update_competencies_from_course(enrollment.employee, course, user=user)
    # Close related assignments / needs
    TrainingAssignment.objects.filter(
        employee=enrollment.employee, course=course
    ).exclude(status=TrainingAssignment.AssignmentStatus.COMPLETED).update(
        status=TrainingAssignment.AssignmentStatus.COMPLETED,
        completed_at=timezone.now(),
        enrollment=enrollment,
    )
    TrainingNeed.objects.filter(
        employee=enrollment.employee, recommended_course=course, status=TrainingNeed.NeedStatus.OPEN
    ).update(status=TrainingNeed.NeedStatus.CLOSED)
    audit(user, "completed", "TrainingEnrollment", enrollment.pk)
    return True


def issue_certificate(enrollment, *, user=None):
    course = enrollment.schedule.course
    # Supersede previous active certs for same course/employee
    TrainingCertificate.objects.filter(
        enrollment__employee=enrollment.employee,
        enrollment__schedule__course=course,
        status=CertificateStatus.ACTIVE,
    ).update(status=CertificateStatus.SUPERSEDED)

    version = (
        TrainingCertificate.objects.filter(
            enrollment__employee=enrollment.employee,
            enrollment__schedule__course=course,
        ).count()
        + 1
    )
    issued = timezone.localdate()
    expiry = None
    if course.certificate_validity_months:
        # Approximate months as 30 days * n for simplicity
        expiry = issued + timedelta(days=30 * course.certificate_validity_months)

    cert = TrainingCertificate.objects.create(
        enrollment=enrollment,
        certificate_number=f"CERT-{issued.year}-{secrets.token_hex(3).upper()}{enrollment.pk}",
        issued_date=issued,
        expiry_date=expiry,
        status=CertificateStatus.ACTIVE,
        version=version,
        verification_code=secrets.token_urlsafe(16),
        issued_by=user if getattr(user, "is_authenticated", False) else None,
    )
    audit(user, "certificate_issued", "TrainingCertificate", cert.pk, cert.certificate_number)
    return cert


def update_competencies_from_course(employee, course, *, user=None):
    for link in course.competency_links.select_related("competency"):
        ec, _ = EmployeeCompetency.objects.get_or_create(
            employee=employee,
            competency=link.competency,
            defaults={"current_level": 1, "source": "training"},
        )
        if link.develops_to_level > ec.current_level:
            ec.current_level = link.develops_to_level
            ec.source = "training"
            ec.assessed_at = timezone.localdate()
            ec.assessed_by = user if getattr(user, "is_authenticated", False) else None
            ec.save()


def competency_gaps_for_employee(employee: Employee):
    """Return gap rows for the employee's designation requirements."""
    if not employee.designation_id:
        return []
    requirements = PositionCompetency.objects.filter(
        designation=employee.designation
    ).select_related("competency")
    current = {
        ec.competency_id: ec.current_level
        for ec in EmployeeCompetency.objects.filter(employee=employee)
    }
    gaps = []
    for req in requirements:
        level = current.get(req.competency_id, 0)
        gap = max(0, req.required_level - level)
        if gap > 0:
            # recommend a course that develops this competency
            course = (
                Course.objects.filter(
                    is_active=True,
                    competency_links__competency=req.competency,
                    competency_links__develops_to_level__gte=req.required_level,
                )
                .order_by("title")
                .first()
            )
            gaps.append(
                {
                    "competency": req.competency,
                    "required_level": req.required_level,
                    "current_level": level,
                    "gap": gap,
                    "recommended_course": course,
                }
            )
    return sorted(gaps, key=lambda g: -g["gap"])


def sync_training_needs_from_gaps(employee: Employee, *, user=None):
    created = 0
    for gap in competency_gaps_for_employee(employee):
        obj, was_created = TrainingNeed.objects.get_or_create(
            employee=employee,
            competency=gap["competency"],
            status=TrainingNeed.NeedStatus.OPEN,
            defaults={
                "source": TrainingNeed.NeedSource.COMPETENCY_GAP,
                "required_level": gap["required_level"],
                "current_level": gap["current_level"],
                "gap": gap["gap"],
                "recommended_course": gap["recommended_course"],
                "rationale": (
                    f"Position requires {gap['competency'].name} level "
                    f"{gap['required_level']}; current level is {gap['current_level']}."
                ),
            },
        )
        if was_created:
            created += 1
        else:
            obj.gap = gap["gap"]
            obj.current_level = gap["current_level"]
            obj.required_level = gap["required_level"]
            obj.recommended_course = gap["recommended_course"]
            obj.save()
    return created


def apply_assignment_rules_for_employee(employee: Employee, *, user=None):
    """Auto-assign mandatory courses matching org rules (e.g. on hire)."""
    rules = TrainingAssignmentRule.objects.filter(is_active=True, course__is_active=True)
    assigned = 0
    for rule in rules:
        if rule.department_id and employee.department_id != rule.department_id:
            continue
        if rule.designation_id and employee.designation_id != rule.designation_id:
            continue
        if rule.employment_type and employee.employment_type != rule.employment_type:
            continue
        if rule.branch_id and not employee.branches.filter(pk=rule.branch_id).exists():
            continue
        exists = TrainingAssignment.objects.filter(
            employee=employee,
            course=rule.course,
            status__in=[
                TrainingAssignment.AssignmentStatus.ASSIGNED,
                TrainingAssignment.AssignmentStatus.IN_PROGRESS,
                TrainingAssignment.AssignmentStatus.OVERDUE,
            ],
        ).exists()
        if exists:
            continue
        # Skip if already completed this course
        completed = TrainingEnrollment.objects.filter(
            employee=employee,
            schedule__course=rule.course,
            status=EnrollmentStatus.COMPLETED,
        ).exists()
        if completed:
            continue
        TrainingAssignment.objects.create(
            employee=employee,
            course=rule.course,
            rule=rule,
            due_date=timezone.localdate() + timedelta(days=30),
            is_mandatory=rule.course.is_mandatory or True,
        )
        assigned += 1
    if assigned:
        audit(user, "auto_assigned", "Employee", employee.pk, f"{assigned} course(s)")
    return assigned


def dashboard_stats():
    today = timezone.localdate()
    soon = today + timedelta(days=30)
    active_employees = Employee.objects.filter(status="active").count()
    trained = (
        TrainingEnrollment.objects.filter(status=EnrollmentStatus.COMPLETED)
        .values("employee")
        .distinct()
        .count()
    )
    return {
        "total_employees": active_employees,
        "employees_trained": trained,
        "active_courses": Course.objects.filter(is_active=True, is_archived=False).count(),
        "upcoming_sessions": TrainingSchedule.objects.filter(
            start_date__gte=today, status="published"
        ).count(),
        "pending_requests": 0,  # filled in view
        "mandatory_overdue": TrainingAssignment.objects.filter(
            is_mandatory=True,
            status__in=["assigned", "in_progress", "overdue"],
            due_date__lt=today,
        ).count(),
        "certs_expiring": TrainingCertificate.objects.filter(
            status=CertificateStatus.ACTIVE,
            expiry_date__isnull=False,
            expiry_date__lte=soon,
            expiry_date__gte=today,
        ).count(),
        "cost_ytd": TrainingEnrollment.objects.filter(
            enrolled_at__year=today.year
        ).aggregate(total=Sum("schedule__course__budget_cost"))["total"]
        or Decimal("0"),
        "completion_rate": round((trained / active_employees) * 100, 1) if active_employees else 0,
        "open_needs": TrainingNeed.objects.filter(status=TrainingNeed.NeedStatus.OPEN).count(),
        "avg_score": TrainingEnrollment.objects.filter(
            evaluation_score__isnull=False
        ).aggregate(avg=Avg("evaluation_score"))["avg"],
    }


def refresh_overdue_assignments():
    today = timezone.localdate()
    return TrainingAssignment.objects.filter(
        due_date__lt=today,
        status__in=[
            TrainingAssignment.AssignmentStatus.ASSIGNED,
            TrainingAssignment.AssignmentStatus.IN_PROGRESS,
        ],
    ).update(status=TrainingAssignment.AssignmentStatus.OVERDUE)


def refresh_expired_certificates():
    today = timezone.localdate()
    return TrainingCertificate.objects.filter(
        status=CertificateStatus.ACTIVE,
        expiry_date__isnull=False,
        expiry_date__lt=today,
    ).update(status=CertificateStatus.EXPIRED)


def get_or_create_elearning_schedule(course: Course) -> TrainingSchedule:
    """Perpetual published session used for self-paced video course enrolments."""
    existing = course.schedules.filter(title=ELEARNING_SCHEDULE_TITLE, location="Online").first()
    if existing:
        return existing
    today = timezone.localdate()
    return TrainingSchedule.objects.create(
        course=course,
        title=ELEARNING_SCHEDULE_TITLE,
        start_date=today,
        end_date=today + timedelta(days=3650),
        location="Online",
        max_participants=9999,
        status=SessionStatus.PUBLISHED,
        notes="Auto-created for video / e-learning progress tracking.",
    )


def ensure_elearning_enrollment(course: Course, employee: Employee, *, user=None) -> TrainingEnrollment:
    schedule = get_or_create_elearning_schedule(course)
    enrollment, _ = enroll_employee(schedule, employee, user=user, force=True)
    if enrollment.status == EnrollmentStatus.WAITLISTED:
        enrollment.status = EnrollmentStatus.ENROLLED
        enrollment.waitlist_position = None
        enrollment.save(update_fields=["status", "waitlist_position", "updated_at"])
    return enrollment


def course_video_progress_summary(course: Course, employee: Employee) -> dict:
    lessons = list(course.lessons.filter(is_published=True))
    total = len(lessons)
    if not total:
        return {"total": 0, "completed": 0, "percent": 0, "lessons": []}
    progress_map = {
        p.lesson_id: p
        for p in CourseLessonProgress.objects.filter(employee=employee, lesson__in=lessons)
    }
    rows = []
    completed = 0
    for lesson in lessons:
        p = progress_map.get(lesson.id)
        done = bool(p and p.completed)
        if done:
            completed += 1
        rows.append(
            {
                "lesson": lesson,
                "percent": p.percent if p else 0,
                "completed": done,
                "watched_seconds": p.watched_seconds if p else 0,
            }
        )
    percent = int(round((completed / total) * 100)) if total else 0
    return {"total": total, "completed": completed, "percent": percent, "lessons": rows}


@transaction.atomic
def record_lesson_progress(
    lesson: CourseLesson,
    employee: Employee,
    *,
    watched_seconds: int = 0,
    duration_seconds: int | None = None,
    completed: bool = False,
    user=None,
) -> CourseLessonProgress:
    """Update watch progress; mark lesson (and course) complete when thresholds met."""
    watched_seconds = max(0, int(watched_seconds or 0))
    if duration_seconds and duration_seconds > 0:
        if not lesson.duration_seconds or abs(lesson.duration_seconds - duration_seconds) > 2:
            lesson.duration_seconds = int(duration_seconds)
            lesson.save(update_fields=["duration_seconds", "updated_at"])

    duration = lesson.duration_seconds or duration_seconds or 0
    percent = 0
    if duration > 0:
        percent = min(100, int(round((watched_seconds / duration) * 100)))
    elif completed:
        percent = 100

    is_complete = bool(completed) or percent >= WATCH_COMPLETE_PERCENT
    if is_complete:
        percent = max(percent, 100)

    progress, _ = CourseLessonProgress.objects.select_for_update().get_or_create(
        lesson=lesson, employee=employee
    )
    progress.watched_seconds = max(progress.watched_seconds, watched_seconds)
    progress.percent = max(progress.percent, percent)
    if is_complete and not progress.completed:
        progress.completed = True
        progress.completed_at = timezone.now()
    progress.save()

    ensure_elearning_enrollment(lesson.course, employee, user=user)
    if progress.completed:
        maybe_complete_elearning(lesson.course, employee, user=user)
    return progress


def maybe_complete_elearning(course: Course, employee: Employee, *, user=None) -> bool:
    """Complete self-paced enrolment when every published lesson is watched."""
    published = course.lessons.filter(is_published=True)
    total = published.count()
    if not total:
        return False
    done = CourseLessonProgress.objects.filter(
        employee=employee, lesson__in=published, completed=True
    ).count()
    if done < total:
        return False

    enrollment = ensure_elearning_enrollment(course, employee, user=user)
    if enrollment.status == EnrollmentStatus.COMPLETED:
        return True

    # Video completion satisfies attendance for e-learning / blended courses
    course_for_rules = course
    if course.require_full_attendance:
        # Temporarily bypass attendance gate for self-paced video path
        enrollment.status = EnrollmentStatus.ATTENDED
        enrollment.save(update_fields=["status", "updated_at"])

    if course_for_rules.require_assessment:
        final_ok = enrollment.assessments.filter(assessment_type="final", passed=True).exists()
        if not final_ok:
            return False

    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.completion_date = timezone.localdate()
    enrollment.save(update_fields=["status", "completion_date", "updated_at"])
    if course.issues_certificate:
        issue_certificate(enrollment, user=user)
    update_competencies_from_course(employee, course, user=user)
    TrainingAssignment.objects.filter(employee=employee, course=course).exclude(
        status=TrainingAssignment.AssignmentStatus.COMPLETED
    ).update(
        status=TrainingAssignment.AssignmentStatus.COMPLETED,
        completed_at=timezone.now(),
        enrollment=enrollment,
    )
    TrainingNeed.objects.filter(
        employee=employee, recommended_course=course, status=TrainingNeed.NeedStatus.OPEN
    ).update(status=TrainingNeed.NeedStatus.CLOSED)
    audit(user, "elearning_completed", "Course", course.pk, f"employee={employee.pk}")
    return True
