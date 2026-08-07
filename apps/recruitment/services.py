"""Recruitment pipeline transitions, logging, and notifications."""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.core.permissions import user_has_permission
from apps.notifications.services import deliver_notification

from .models import (
    Application,
    ApplicationActivity,
    ApplicationStatus,
    OfferLetter,
    OfferStatus,
    RequisitionStatus,
    Vacancy,
    VacancyStatus,
)

User = get_user_model()


def log_activity(application, actor, event, detail="", from_status="", to_status=""):
    return ApplicationActivity.objects.create(
        application=application,
        actor=actor,
        event=event,
        detail=detail,
        from_status=from_status or "",
        to_status=to_status or "",
    )


def users_with_recruitment_manage():
    return User.objects.filter(
        Q(is_superuser=True)
        | Q(role__permissions__codename="manage_recruitment")
        | Q(role__permissions__codename="view_recruitment")
    ).distinct().filter(is_active=True)


def notify_recruiters(title, message, link="", exclude=None):
    for user in users_with_recruitment_manage():
        if exclude and user.pk == getattr(exclude, "pk", None):
            continue
        deliver_notification(
            user,
            title=title,
            message=message,
            category="recruitment",
            link=link,
            channels=[],
        )


def set_application_status(application, new_status, actor, note=""):
    """Move candidate through the pipeline with audit + side effects."""
    old = application.status
    if old == new_status:
        return application

    application.status = new_status
    application.status_changed_at = timezone.now()
    if new_status == ApplicationStatus.REJECTED and note:
        application.rejection_notes = note
    application.save(
        update_fields=["status", "status_changed_at", "rejection_notes", "updated_at"]
        if note and new_status == ApplicationStatus.REJECTED
        else ["status", "status_changed_at", "updated_at"]
    )

    label = dict(ApplicationStatus.choices).get(new_status, new_status)
    log_activity(
        application,
        actor,
        event="status_change",
        detail=note or f"Moved to {label}",
        from_status=old,
        to_status=new_status,
    )

    # Vacancy filled when hired count meets positions
    if new_status == ApplicationStatus.HIRED:
        vacancy = application.vacancy
        if vacancy.hired_count >= vacancy.positions:
            vacancy.status = VacancyStatus.FILLED
            vacancy.save(update_fields=["status", "updated_at"])
            if vacancy.requisition_id:
                vacancy.requisition.status = RequisitionStatus.FULFILLED
                vacancy.requisition.save(update_fields=["status", "updated_at"])

    return application


def publish_vacancy(vacancy, actor):
    vacancy.status = VacancyStatus.OPEN
    if not vacancy.posted_date:
        vacancy.posted_date = timezone.localdate()
    vacancy.save(update_fields=["status", "posted_date", "updated_at"])
    notify_recruiters(
        title=f"Vacancy open: {vacancy.title}",
        message=f"{vacancy.positions} position(s) posted for {vacancy.department or 'organisation'}.",
        link=f"/recruitment/vacancies/{vacancy.pk}/",
        exclude=actor,
    )
    return vacancy


def submit_requisition(requisition, actor):
    requisition.status = RequisitionStatus.PENDING_HR
    requisition.save(update_fields=["status", "updated_at"])
    notify_recruiters(
        title=f"Requisition pending: {requisition.title}",
        message=f"{actor.get_full_name() or actor.username} submitted a hire request.",
        link=f"/recruitment/requisitions/{requisition.pk}/",
        exclude=actor,
    )
    return requisition


def approve_requisition_hr(requisition, actor, note=""):
    requisition.status = RequisitionStatus.PENDING_GM
    requisition.hr_reviewed_by = actor
    requisition.hr_reviewed_at = timezone.now()
    requisition.hr_note = note
    requisition.save(
        update_fields=["status", "hr_reviewed_by", "hr_reviewed_at", "hr_note", "updated_at"]
    )
    # Notify GM-capable users (manage_recruitment + superusers)
    for user in User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(role__name__icontains="General Manager") | Q(role__name__icontains="GM")
    ).distinct():
        deliver_notification(
            user,
            title=f"Requisition awaiting GM: {requisition.title}",
            message="HR approved — awaiting final headcount approval.",
            category="recruitment",
            link=f"/recruitment/requisitions/{requisition.pk}/",
            channels=[],
        )
    if requisition.requested_by_id:
        deliver_notification(
            requisition.requested_by,
            title=f"Requisition advanced: {requisition.title}",
            message="HR approved your request. Awaiting GM.",
            category="recruitment",
            link=f"/recruitment/requisitions/{requisition.pk}/",
            channels=[],
        )
    return requisition


def approve_requisition_gm(requisition, actor, note=""):
    requisition.status = RequisitionStatus.APPROVED
    requisition.gm_reviewed_by = actor
    requisition.gm_reviewed_at = timezone.now()
    requisition.gm_note = note
    requisition.save(
        update_fields=["status", "gm_reviewed_by", "gm_reviewed_at", "gm_note", "updated_at"]
    )
    notify_recruiters(
        title=f"Requisition approved: {requisition.title}",
        message="You can now create and publish a vacancy.",
        link=f"/recruitment/requisitions/{requisition.pk}/",
    )
    if requisition.requested_by_id:
        deliver_notification(
            requisition.requested_by,
            title=f"Requisition approved: {requisition.title}",
            message="GM approved your headcount request.",
            category="recruitment",
            link=f"/recruitment/requisitions/{requisition.pk}/",
            channels=[],
        )
    return requisition


def reject_requisition(requisition, actor, note="", stage="hr"):
    requisition.status = RequisitionStatus.REJECTED
    if stage == "gm":
        requisition.gm_reviewed_by = actor
        requisition.gm_reviewed_at = timezone.now()
        requisition.gm_note = note
        fields = ["status", "gm_reviewed_by", "gm_reviewed_at", "gm_note", "updated_at"]
    else:
        requisition.hr_reviewed_by = actor
        requisition.hr_reviewed_at = timezone.now()
        requisition.hr_note = note
        fields = ["status", "hr_reviewed_by", "hr_reviewed_at", "hr_note", "updated_at"]
    requisition.save(update_fields=fields)
    if requisition.requested_by_id:
        deliver_notification(
            requisition.requested_by,
            title=f"Requisition rejected: {requisition.title}",
            message=note or "Your hire request was not approved.",
            category="recruitment",
            link=f"/recruitment/requisitions/{requisition.pk}/",
            channels=[],
        )
    return requisition


def send_offer(offer: OfferLetter, actor):
    offer.status = OfferStatus.SENT
    offer.issued_at = timezone.localdate()
    offer.accepted = False
    offer.save(update_fields=["status", "issued_at", "accepted", "updated_at"])
    set_application_status(offer.application, ApplicationStatus.OFFER, actor, note="Offer issued")
    return offer


def accept_offer(offer: OfferLetter, actor=None):
    offer.status = OfferStatus.ACCEPTED
    offer.accepted = True
    offer.responded_at = timezone.localdate()
    offer.save(update_fields=["status", "accepted", "responded_at", "updated_at"])
    set_application_status(
        offer.application, ApplicationStatus.OFFER_ACCEPTED, actor, note="Candidate accepted offer"
    )
    notify_recruiters(
        title=f"Offer accepted: {offer.application.full_name}",
        message=f"Accepted offer for {offer.application.vacancy.title}. Ready to mark as hired.",
        link=f"/recruitment/applications/{offer.application.pk}/",
        exclude=actor,
    )
    return offer


def decline_offer(offer: OfferLetter, actor=None, note=""):
    offer.status = OfferStatus.DECLINED
    offer.accepted = False
    offer.responded_at = timezone.localdate()
    offer.save(update_fields=["status", "accepted", "responded_at", "updated_at"])
    set_application_status(
        offer.application,
        ApplicationStatus.REJECTED,
        actor,
        note=note or "Candidate declined offer",
    )
    return offer


def can_manage_recruitment(user):
    return user_has_permission(user, "manage_recruitment")
