from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.audit import log_change, serialize_instance
from apps.core.permissions import permission_required, user_has_permission
from apps.notifications.services import deliver_notification

from .forms import AnnouncementForm, AnnouncementReviewForm
from .models import Announcement, AnnouncementAttachment, AnnouncementStatus
from .notify import notify_staff_of_published_announcement


def _save_attachments(request, announcement, files):
    for uploaded in files or []:
        if not uploaded:
            continue
        AnnouncementAttachment.objects.create(
            announcement=announcement,
            file=uploaded,
            original_name=getattr(uploaded, "name", "")[:255],
            content_type=getattr(uploaded, "content_type", "")[:120],
            uploaded_by=request.user,
        )


def _announcement_qs():
    return Announcement.objects.select_related("author", "approved_by").prefetch_related(
        "attachments",
        "departments",
        "branches",
        "cadres",
    )


@login_required
def announcement_list(request):
    published = _announcement_qs().visible_to(request.user)[:30]

    mine = Announcement.objects.none()
    if user_has_permission(request.user, "create_announcement"):
        mine = (
            _announcement_qs()
            .filter(author=request.user)
            .exclude(status=AnnouncementStatus.APPROVED, is_active=True)[:20]
        )

    pending_count = 0
    if user_has_permission(request.user, "approve_announcement"):
        pending_count = Announcement.objects.filter(status=AnnouncementStatus.PENDING).count()

    return render(
        request,
        "announcements/list.html",
        {
            "announcements": published,
            "my_announcements": mine,
            "pending_count": pending_count,
            "can_create": user_has_permission(request.user, "create_announcement"),
            "can_approve": user_has_permission(request.user, "approve_announcement"),
        },
    )


@login_required
def announcement_detail(request, pk):
    announcement = get_object_or_404(_announcement_qs(), pk=pk)
    can_approve = user_has_permission(request.user, "approve_announcement")
    is_author = announcement.author_id == request.user.id
    privileged = can_approve or is_author or request.user.is_superuser

    if announcement.is_published:
        if not privileged and not announcement.is_visible_to(request.user):
            messages.error(request, "This announcement is not available to you.")
            return redirect("announcements:list")
    elif not privileged:
        messages.error(request, "This announcement is not available.")
        return redirect("announcements:list")

    return render(
        request,
        "announcements/detail.html",
        {
            "announcement": announcement,
            "can_approve": can_approve,
            "review_form": AnnouncementReviewForm(),
        },
    )


@login_required
@permission_required("create_announcement")
def announcement_create(request):
    if request.method == "POST":
        form = AnnouncementForm(request.POST, request.FILES)
        files = request.FILES.getlist("attachments")
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.author = request.user
            announcement.submit_for_approval()
            publish_now = request.POST.get("publish_now") == "1" and user_has_permission(
                request.user, "approve_announcement"
            )
            if publish_now:
                announcement.approve(request.user, note="Auto-approved by creator with approval rights")
            announcement.save()
            form.save_m2m()
            _save_attachments(request, announcement, files)
            log_change(
                request,
                "announcement_create",
                instance=announcement,
                old_data={},
                new_data=serialize_instance(announcement),
            )
            if announcement.status == AnnouncementStatus.APPROVED:
                count = notify_staff_of_published_announcement(announcement)
                messages.success(
                    request,
                    f"Announcement published to {announcement.audience_label}. "
                    f"Notified {count} staff member{'s' if count != 1 else ''}.",
                )
            else:
                messages.success(
                    request,
                    f"Announcement submitted for approval ({announcement.audience_label}).",
                )
            return redirect("announcements:detail", pk=announcement.pk)
    else:
        form = AnnouncementForm()

    return render(
        request,
        "announcements/form.html",
        {
            "form": form,
            "can_publish_now": user_has_permission(request.user, "approve_announcement"),
        },
    )


@login_required
@permission_required("approve_announcement")
def announcement_approvals(request):
    pending = (
        _announcement_qs()
        .filter(status=AnnouncementStatus.PENDING)
    )
    history = (
        _announcement_qs()
        .filter(status__in=[AnnouncementStatus.APPROVED, AnnouncementStatus.REJECTED])
        .order_by("-approved_at")[:30]
    )
    return render(
        request,
        "announcements/approvals.html",
        {"pending": pending, "history": history, "review_form": AnnouncementReviewForm()},
    )


@login_required
@permission_required("approve_announcement")
@require_POST
def announcement_review(request, pk, action):
    announcement = get_object_or_404(Announcement, pk=pk)
    if announcement.status != AnnouncementStatus.PENDING:
        messages.error(request, "Only pending announcements can be reviewed.")
        return redirect("announcements:approvals")

    form = AnnouncementReviewForm(request.POST)
    note = form.cleaned_data.get("note", "") if form.is_valid() else request.POST.get("note", "")
    old = serialize_instance(announcement)

    if action == "approve":
        announcement.approve(request.user, note=note)
        msg = f'Announcement "{announcement.title}" approved and published.'
        notif_title = "Announcement approved"
    elif action == "reject":
        announcement.reject(request.user, note=note)
        msg = f'Announcement "{announcement.title}" rejected.'
        notif_title = "Announcement rejected"
    else:
        messages.error(request, "Invalid review action.")
        return redirect("announcements:approvals")

    announcement.save()
    log_change(
        request,
        f"announcement_{action}",
        instance=announcement,
        old_data=old,
        new_data=serialize_instance(announcement),
    )

    if announcement.author_id and announcement.author_id != request.user.id:
        deliver_notification(
            announcement.author,
            notif_title,
            f'Your announcement "{announcement.title}" was {action}d. {note}'.strip(),
            category="announcement",
            link=f"/announcements/{announcement.pk}/",
            channels=["email"] if announcement.author.email else [],
        )

    if action == "approve":
        count = notify_staff_of_published_announcement(announcement)
        msg = (
            f'{msg} Audience: {announcement.audience_label}. '
            f'Notified {count} staff member{"s" if count != 1 else ""}.'
        )

    messages.success(request, msg)
    next_url = request.POST.get("next") or "announcements:approvals"
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect(next_url)
