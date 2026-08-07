from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import permission_required, user_has_permission
from apps.notifications.services import deliver_notification

from .forms import (
    ApplicationForm,
    AssessmentForm,
    InterviewFeedbackForm,
    InterviewForm,
    NoteForm,
    OfferForm,
    PublicApplicationForm,
    ReferenceForm,
    RequisitionForm,
    ReviewNoteForm,
    ScorecardForm,
    StatusChangeForm,
    VacancyForm,
)
from .models import (
    PIPELINE_ACTIVE,
    Application,
    ApplicationSource,
    ApplicationStatus,
    Assessment,
    Interview,
    InterviewScorecard,
    JobRequisition,
    OfferLetter,
    OfferStatus,
    ReferenceCheck,
    RequisitionStatus,
    Vacancy,
    VacancyStatus,
)
from . import services


def _can_manage(user):
    return user_has_permission(user, "manage_recruitment")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def dashboard(request):
    open_vacancies = Vacancy.objects.filter(status=VacancyStatus.OPEN).count()
    active_apps = Application.objects.filter(status__in=PIPELINE_ACTIVE).count()
    upcoming = Interview.objects.filter(
        completed=False, scheduled_at__gte=timezone.now()
    ).count()
    pending_reqs = JobRequisition.objects.filter(
        status__in=[RequisitionStatus.PENDING_HR, RequisitionStatus.PENDING_GM]
    ).count()
    offers_out = OfferLetter.objects.filter(status=OfferStatus.SENT).count()
    hired_month = Application.objects.filter(
        status=ApplicationStatus.HIRED,
        status_changed_at__month=timezone.localdate().month,
        status_changed_at__year=timezone.localdate().year,
    ).count()

    pipeline = (
        Application.objects.filter(status__in=PIPELINE_ACTIVE)
        .values("status")
        .annotate(n=Count("id"))
    )
    pipeline_map = {row["status"]: row["n"] for row in pipeline}

    return render(
        request,
        "recruitment/dashboard.html",
        {
            "can_manage": _can_manage(request.user),
            "open_vacancies": open_vacancies,
            "active_apps": active_apps,
            "upcoming_interviews": upcoming,
            "pending_reqs": pending_reqs,
            "offers_out": offers_out,
            "hired_month": hired_month,
            "pipeline_map": pipeline_map,
            "pipeline_stages": [
                (s.value, s.label, pipeline_map.get(s.value, 0))
                for s in ApplicationStatus
                if s.value in PIPELINE_ACTIVE
            ],
            "recent_applications": Application.objects.select_related("vacancy").order_by(
                "-applied_at"
            )[:8],
            "upcoming_interview_list": Interview.objects.select_related(
                "application", "application__vacancy"
            )
            .filter(completed=False, scheduled_at__gte=timezone.now())
            .order_by("scheduled_at")[:8],
            "pending_requisitions": JobRequisition.objects.select_related(
                "department", "requested_by"
            )
            .filter(status__in=[RequisitionStatus.PENDING_HR, RequisitionStatus.PENDING_GM])
            .order_by("-created_at")[:5],
        },
    )


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def requisition_list(request):
    qs = JobRequisition.objects.select_related("department", "branch", "requested_by")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "recruitment/requisition_list.html",
        {
            "requisitions": qs,
            "can_manage": _can_manage(request.user),
            "status_filter": status or "",
            "statuses": RequisitionStatus.choices,
        },
    )


@login_required
@permission_required("manage_recruitment")
def requisition_create(request):
    if request.method == "POST":
        form = RequisitionForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.requested_by = request.user
            req.status = RequisitionStatus.DRAFT
            req.save()
            if request.POST.get("submit_now"):
                services.submit_requisition(req, request.user)
                messages.success(request, "Requisition submitted for HR approval.")
            else:
                messages.success(request, "Requisition saved as draft.")
            return redirect("recruitment:requisition_detail", pk=req.pk)
    else:
        form = RequisitionForm()
    return render(request, "recruitment/requisition_form.html", {"form": form, "mode": "create"})


@login_required
@permission_required("view_recruitment")
def requisition_detail(request, pk):
    req = get_object_or_404(
        JobRequisition.objects.select_related(
            "department", "branch", "requested_by", "hr_reviewed_by", "gm_reviewed_by"
        ),
        pk=pk,
    )
    return render(
        request,
        "recruitment/requisition_detail.html",
        {
            "requisition": req,
            "can_manage": _can_manage(request.user),
            "review_form": ReviewNoteForm(),
        },
    )


@login_required
@permission_required("manage_recruitment")
@require_POST
def requisition_submit(request, pk):
    req = get_object_or_404(JobRequisition, pk=pk)
    if req.status != RequisitionStatus.DRAFT:
        messages.error(request, "Only draft requisitions can be submitted.")
    else:
        services.submit_requisition(req, request.user)
        messages.success(request, "Submitted to HR.")
    return redirect("recruitment:requisition_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def requisition_hr_action(request, pk):
    req = get_object_or_404(JobRequisition, pk=pk)
    form = ReviewNoteForm(request.POST)
    note = form["note"].value() if form.is_valid() else ""
    action = request.POST.get("action")
    if req.status != RequisitionStatus.PENDING_HR:
        messages.error(request, "This requisition is not awaiting HR.")
    elif action == "approve":
        services.approve_requisition_hr(req, request.user, note or "")
        messages.success(request, "Advanced to GM approval.")
    elif action == "reject":
        services.reject_requisition(req, request.user, note or "", stage="hr")
        messages.warning(request, "Requisition rejected.")
    return redirect("recruitment:requisition_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def requisition_gm_action(request, pk):
    req = get_object_or_404(JobRequisition, pk=pk)
    form = ReviewNoteForm(request.POST)
    note = form["note"].value() if form.is_valid() else ""
    action = request.POST.get("action")
    if req.status != RequisitionStatus.PENDING_GM:
        messages.error(request, "This requisition is not awaiting GM.")
    elif action == "approve":
        services.approve_requisition_gm(req, request.user, note or "")
        messages.success(request, "Requisition approved. You can create a vacancy.")
    elif action == "reject":
        services.reject_requisition(req, request.user, note or "", stage="gm")
        messages.warning(request, "Requisition rejected by GM.")
    return redirect("recruitment:requisition_detail", pk=pk)


# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def vacancy_list(request):
    qs = Vacancy.objects.select_related("department", "branch", "recruiter")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    return render(
        request,
        "recruitment/vacancy_list.html",
        {
            "vacancies": qs.annotate(app_count=Count("applications")),
            "can_manage": _can_manage(request.user),
            "status_filter": status or "",
            "q": q,
            "statuses": VacancyStatus.choices,
        },
    )


@login_required
@permission_required("manage_recruitment")
def vacancy_create(request):
    initial = {}
    req_id = request.GET.get("requisition")
    if req_id:
        req = JobRequisition.objects.filter(pk=req_id, status=RequisitionStatus.APPROVED).first()
        if req:
            initial = {
                "title": req.title,
                "department": req.department,
                "branch": req.branch,
                "positions": req.positions,
                "employment_type": req.employment_type,
                "description": req.job_description or req.justification,
                "requirements": req.requirements,
                "min_salary": req.min_salary,
                "max_salary": req.max_salary,
                "requisition": req,
                "status": VacancyStatus.DRAFT,
            }
    if request.method == "POST":
        form = VacancyForm(request.POST)
        if form.is_valid():
            vac = form.save(commit=False)
            vac.created_by = request.user
            if not vac.recruiter_id:
                vac.recruiter = request.user
            vac.save()
            if request.POST.get("publish"):
                services.publish_vacancy(vac, request.user)
                messages.success(request, f"Vacancy “{vac.title}” published.")
            else:
                messages.success(request, f"Vacancy “{vac.title}” saved as draft.")
            return redirect("recruitment:vacancy_detail", pk=vac.pk)
    else:
        form = VacancyForm(initial=initial)
    return render(request, "recruitment/vacancy_form.html", {"form": form, "mode": "create"})


@login_required
@permission_required("manage_recruitment")
def vacancy_edit(request, pk):
    vac = get_object_or_404(Vacancy, pk=pk)
    if request.method == "POST":
        form = VacancyForm(request.POST, instance=vac)
        if form.is_valid():
            form.save()
            messages.success(request, "Vacancy updated.")
            return redirect("recruitment:vacancy_detail", pk=pk)
    else:
        form = VacancyForm(instance=vac)
    return render(
        request, "recruitment/vacancy_form.html", {"form": form, "mode": "edit", "vacancy": vac}
    )


@login_required
@permission_required("view_recruitment")
def vacancy_detail(request, pk):
    vac = get_object_or_404(
        Vacancy.objects.select_related(
            "department", "branch", "requisition", "hiring_manager", "recruiter", "created_by"
        ),
        pk=pk,
    )
    apps = vac.applications.select_related("assigned_recruiter").order_by("-applied_at")
    by_status = {s.value: [] for s in ApplicationStatus if s.value in PIPELINE_ACTIVE}
    for app in apps.filter(status__in=PIPELINE_ACTIVE):
        by_status.setdefault(app.status, []).append(app)
    return render(
        request,
        "recruitment/vacancy_detail.html",
        {
            "vacancy": vac,
            "applications": apps,
            "by_status": by_status,
            "can_manage": _can_manage(request.user),
            "pipeline_stages": [(s.value, s.label) for s in ApplicationStatus if s.value in PIPELINE_ACTIVE],
        },
    )


@login_required
@permission_required("manage_recruitment")
@require_POST
def vacancy_publish(request, pk):
    vac = get_object_or_404(Vacancy, pk=pk)
    services.publish_vacancy(vac, request.user)
    messages.success(request, "Vacancy is now open.")
    return redirect("recruitment:vacancy_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def vacancy_close(request, pk):
    vac = get_object_or_404(Vacancy, pk=pk)
    vac.status = VacancyStatus.CLOSED
    vac.save(update_fields=["status", "updated_at"])
    messages.info(request, "Vacancy closed.")
    return redirect("recruitment:vacancy_detail", pk=pk)


# ---------------------------------------------------------------------------
# Applications / pipeline
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def application_list(request):
    qs = Application.objects.select_related("vacancy", "assigned_recruiter")
    status = request.GET.get("status")
    vacancy_id = request.GET.get("vacancy")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if vacancy_id:
        qs = qs.filter(vacancy_id=vacancy_id)
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(vacancy__title__icontains=q)
        )
    return render(
        request,
        "recruitment/application_list.html",
        {
            "applications": qs,
            "can_manage": _can_manage(request.user),
            "status_filter": status or "",
            "vacancy_filter": vacancy_id or "",
            "q": q,
            "statuses": ApplicationStatus.choices,
            "vacancies": Vacancy.objects.all().order_by("title"),
        },
    )


@login_required
@permission_required("view_recruitment")
def pipeline(request):
    """Kanban board across active pipeline stages."""
    vacancy_id = request.GET.get("vacancy")
    qs = Application.objects.select_related("vacancy").filter(status__in=PIPELINE_ACTIVE)
    if vacancy_id:
        qs = qs.filter(vacancy_id=vacancy_id)
    columns = []
    for stage in ApplicationStatus:
        if stage.value not in PIPELINE_ACTIVE:
            continue
        columns.append(
            {
                "key": stage.value,
                "label": stage.label,
                "items": list(qs.filter(status=stage.value).order_by("-applied_at")[:40]),
            }
        )
    return render(
        request,
        "recruitment/pipeline.html",
        {
            "columns": columns,
            "can_manage": _can_manage(request.user),
            "vacancies": Vacancy.objects.filter(
                status__in=[VacancyStatus.OPEN, VacancyStatus.DRAFT, VacancyStatus.ON_HOLD]
            ),
            "vacancy_filter": vacancy_id or "",
        },
    )


@login_required
@permission_required("manage_recruitment")
def application_create(request):
    vacancy_id = request.GET.get("vacancy")
    vacancy = Vacancy.objects.filter(pk=vacancy_id).first() if vacancy_id else None
    if request.method == "POST":
        form = ApplicationForm(request.POST, request.FILES, vacancy=vacancy)
        if form.is_valid():
            app = form.save(commit=False)
            if not app.source:
                app.source = ApplicationSource.MANUAL
            app.save()
            services.log_activity(app, request.user, "created", "Application added by HR")
            services.notify_recruiters(
                title=f"New applicant: {app.full_name}",
                message=f"Applied for {app.vacancy.title}",
                link=f"/recruitment/applications/{app.pk}/",
                exclude=request.user,
            )
            messages.success(request, "Application created.")
            return redirect("recruitment:application_detail", pk=app.pk)
    else:
        form = ApplicationForm(vacancy=vacancy)
    return render(
        request,
        "recruitment/application_form.html",
        {"form": form, "vacancy": vacancy},
    )


@login_required
@permission_required("view_recruitment")
def application_detail(request, pk):
    app = get_object_or_404(
        Application.objects.select_related("vacancy", "vacancy__department", "assigned_recruiter"),
        pk=pk,
    )
    offer = getattr(app, "offer", None)
    return render(
        request,
        "recruitment/application_detail.html",
        {
            "application": app,
            "can_manage": _can_manage(request.user),
            "status_form": StatusChangeForm(initial={"status": app.status}),
            "note_form": NoteForm(),
            "interview_form": InterviewForm(),
            "assessment_form": AssessmentForm(),
            "reference_form": ReferenceForm(),
            "offer_form": OfferForm(instance=offer) if offer else OfferForm(),
            "offer": offer,
            "interviews": app.interviews.prefetch_related("panel_members", "scorecards").all(),
            "assessments": app.assessments.all(),
            "references": app.references.all(),
            "notes": app.notes.select_related("author").all(),
            "activities": app.activities.select_related("actor").all()[:30],
        },
    )


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_set_status(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = StatusChangeForm(request.POST)
    if form.is_valid():
        new_status = form.cleaned_data["status"]
        note = form.cleaned_data.get("note") or ""
        reason = form.cleaned_data.get("rejection_reason") or ""
        if new_status == ApplicationStatus.REJECTED and reason:
            app.rejection_reason = reason
            app.save(update_fields=["rejection_reason", "updated_at"])
        services.set_application_status(app, new_status, request.user, note=note)
        messages.success(request, f"Status updated to {app.get_status_display()}.")
    else:
        messages.error(request, "Could not update status.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_add_note(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.application = app
        note.author = request.user
        note.save()
        services.log_activity(app, request.user, "note", note.body[:200])
        messages.success(request, "Note added.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_schedule_interview(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = InterviewForm(request.POST)
    if form.is_valid():
        interview = form.save(commit=False)
        interview.application = app
        interview.created_by = request.user
        interview.save()
        form.save_m2m()
        if app.status in (ApplicationStatus.NEW, ApplicationStatus.SCREENING, ApplicationStatus.PHONE_SCREEN):
            services.set_application_status(app, ApplicationStatus.INTERVIEW, request.user, "Interview scheduled")
        services.log_activity(
            app,
            request.user,
            "interview_scheduled",
            f"{interview.get_interview_type_display()} on {interview.scheduled_at}",
        )
        for member in interview.panel_members.all():
            deliver_notification(
                member,
                title=f"Interview: {app.full_name}",
                message=f"{app.vacancy.title} — {interview.scheduled_at}",
                category="recruitment",
                link=f"/recruitment/interviews/{interview.pk}/",
                channels=[],
            )
        messages.success(request, "Interview scheduled.")
    else:
        messages.error(request, "Could not schedule interview. Check the form.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_add_assessment(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = AssessmentForm(request.POST)
    if form.is_valid():
        assessment = form.save(commit=False)
        assessment.application = app
        assessment.created_by = request.user
        assessment.save()
        if app.status not in (
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.OFFER,
            ApplicationStatus.HIRED,
        ):
            services.set_application_status(
                app, ApplicationStatus.ASSESSMENT, request.user, f"Assessment: {assessment.title}"
            )
        messages.success(request, "Assessment recorded.")
    else:
        messages.error(request, "Could not save assessment.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_add_reference(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = ReferenceForm(request.POST)
    if form.is_valid():
        ref = form.save(commit=False)
        ref.application = app
        ref.verified_by = request.user
        ref.save()
        if app.status not in (ApplicationStatus.REFERENCE_CHECK, ApplicationStatus.OFFER, ApplicationStatus.HIRED):
            services.set_application_status(
                app, ApplicationStatus.REFERENCE_CHECK, request.user, "Reference check added"
            )
        messages.success(request, "Reference saved.")
    else:
        messages.error(request, "Could not save reference.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def application_save_offer(request, pk):
    app = get_object_or_404(Application, pk=pk)
    offer = getattr(app, "offer", None)
    form = OfferForm(request.POST, request.FILES, instance=offer)
    if form.is_valid():
        offer = form.save(commit=False)
        offer.application = app
        if not offer.created_by_id:
            offer.created_by = request.user
        if not offer.status:
            offer.status = OfferStatus.DRAFT
        offer.save()
        action = request.POST.get("action")
        if action == "send":
            services.send_offer(offer, request.user)
            messages.success(request, "Offer issued and candidate moved to Offer stage.")
        else:
            messages.success(request, "Offer saved as draft.")
            services.log_activity(app, request.user, "offer_draft", f"Salary {offer.salary_offered}")
    else:
        messages.error(request, "Could not save offer. Check required fields.")
    return redirect("recruitment:application_detail", pk=pk)


@login_required
@permission_required("manage_recruitment")
@require_POST
def offer_respond(request, pk):
    """HR records candidate accept/decline."""
    offer = get_object_or_404(OfferLetter, pk=pk)
    action = request.POST.get("action")
    if action == "accept":
        services.accept_offer(offer, request.user)
        messages.success(request, "Offer marked accepted.")
    elif action == "decline":
        services.decline_offer(offer, request.user, request.POST.get("note", ""))
        messages.warning(request, "Offer declined.")
    elif action == "hire":
        if offer.status != OfferStatus.ACCEPTED and not offer.accepted:
            services.accept_offer(offer, request.user)
        services.set_application_status(
            offer.application, ApplicationStatus.HIRED, request.user, "Marked hired"
        )
        messages.success(request, "Candidate marked as hired.")
    return redirect("recruitment:application_detail", pk=offer.application_id)


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def interview_list(request):
    qs = Interview.objects.select_related(
        "application", "application__vacancy"
    ).prefetch_related("panel_members")
    show = request.GET.get("show", "upcoming")
    if show == "completed":
        qs = qs.filter(completed=True)
    elif show == "all":
        pass
    else:
        qs = qs.filter(completed=False)
    return render(
        request,
        "recruitment/interview_list.html",
        {
            "interviews": qs.order_by("scheduled_at" if show != "completed" else "-scheduled_at"),
            "can_manage": _can_manage(request.user),
            "show": show,
        },
    )


@login_required
@permission_required("view_recruitment")
def interview_detail(request, pk):
    interview = get_object_or_404(
        Interview.objects.select_related("application", "application__vacancy").prefetch_related(
            "panel_members", "scorecards__reviewer"
        ),
        pk=pk,
    )
    my_score = None
    if request.user.is_authenticated:
        my_score = interview.scorecards.filter(reviewer=request.user).first()
    return render(
        request,
        "recruitment/interview_detail.html",
        {
            "interview": interview,
            "can_manage": _can_manage(request.user),
            "feedback_form": InterviewFeedbackForm(instance=interview),
            "scorecard_form": ScorecardForm(instance=my_score),
            "my_score": my_score,
        },
    )


@login_required
@permission_required("manage_recruitment")
@require_POST
def interview_feedback(request, pk):
    interview = get_object_or_404(Interview, pk=pk)
    form = InterviewFeedbackForm(request.POST, instance=interview)
    if form.is_valid():
        form.save()
        services.log_activity(
            interview.application,
            request.user,
            "interview_feedback",
            f"Round {interview.round_number}: {interview.get_recommendation_display() or 'updated'}",
        )
        messages.success(request, "Interview feedback saved.")
    else:
        messages.error(request, "Could not save feedback.")
    return redirect("recruitment:interview_detail", pk=pk)


@login_required
@permission_required("view_recruitment")
@require_POST
def interview_scorecard(request, pk):
    interview = get_object_or_404(Interview, pk=pk)
    # Panel members or recruiters can score
    is_panel = interview.panel_members.filter(pk=request.user.pk).exists()
    if not (_can_manage(request.user) or is_panel):
        messages.error(request, "You are not on this interview panel.")
        return redirect("recruitment:interview_detail", pk=pk)
    existing = interview.scorecards.filter(reviewer=request.user).first()
    form = ScorecardForm(request.POST, instance=existing)
    if form.is_valid():
        card = form.save(commit=False)
        card.interview = interview
        card.reviewer = request.user
        card.save()
        messages.success(request, "Scorecard submitted.")
    else:
        messages.error(request, "Could not save scorecard.")
    return redirect("recruitment:interview_detail", pk=pk)


# ---------------------------------------------------------------------------
# Offers list
# ---------------------------------------------------------------------------


@login_required
@permission_required("view_recruitment")
def offer_list(request):
    offers = OfferLetter.objects.select_related(
        "application", "application__vacancy", "created_by"
    ).order_by("-created_at")
    status = request.GET.get("status")
    if status:
        offers = offers.filter(status=status)
    return render(
        request,
        "recruitment/offer_list.html",
        {
            "offers": offers,
            "can_manage": _can_manage(request.user),
            "status_filter": status or "",
            "statuses": OfferStatus.choices,
        },
    )


# ---------------------------------------------------------------------------
# Public careers portal
# ---------------------------------------------------------------------------


def careers_list(request):
    vacancies = (
        Vacancy.objects.filter(status=VacancyStatus.OPEN, is_public=True)
        .select_related("department", "branch")
        .order_by("-posted_date")
    )
    # Hide past closing date
    today = timezone.localdate()
    vacancies = [v for v in vacancies if not v.closing_date or v.closing_date >= today]
    return render(request, "recruitment/careers_list.html", {"vacancies": vacancies})


def careers_detail(request, slug):
    vac = get_object_or_404(
        Vacancy.objects.select_related("department", "branch"),
        slug=slug,
    )
    # Closed, filled, draft, private, or past closing date — friendly page, not 404
    if not vac.is_public or not vac.is_accepting_applications:
        reason = "closed"
        if not vac.is_public:
            reason = "unavailable"
        elif vac.status == VacancyStatus.FILLED:
            reason = "filled"
        elif vac.closing_date and vac.closing_date < timezone.localdate():
            reason = "expired"
        return render(
            request,
            "recruitment/careers_closed.html",
            {"vacancy": vac, "reason": reason},
            status=410 if vac.status in (VacancyStatus.CLOSED, VacancyStatus.FILLED, VacancyStatus.CANCELLED) else 200,
        )

    if request.method == "POST":
        form = PublicApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            email = form.cleaned_data["email"]
            if Application.objects.filter(vacancy=vac, email__iexact=email).exists():
                messages.error(request, "An application with this email already exists for this role.")
            else:
                app = form.save(commit=False)
                app.vacancy = vac
                app.source = ApplicationSource.CAREERS
                app.save()
                services.log_activity(app, None, "applied", "Submitted via careers portal")
                services.notify_recruiters(
                    title=f"New application: {app.full_name}",
                    message=f"Applied for {vac.title} via careers portal.",
                    link=f"/recruitment/applications/{app.pk}/",
                )
                messages.success(
                    request,
                    "Thank you — your application has been received. We will be in touch.",
                )
                return redirect("recruitment:careers_thanks", slug=vac.slug)
    else:
        form = PublicApplicationForm()
    return render(
        request,
        "recruitment/careers_detail.html",
        {"vacancy": vac, "form": form},
    )


def careers_thanks(request, slug):
    vac = get_object_or_404(Vacancy, slug=slug)
    return render(request, "recruitment/careers_thanks.html", {"vacancy": vac})
