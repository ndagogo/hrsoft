from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.http import JsonResponse

from apps.core.audit import log_change, serialize_instance
from apps.core.permissions import permission_required
from .models import LeaveRequest, LeaveType, LeaveStatus, LeaveStandInStatus, LeaveStandInRequest, LeaveApprovalDocument
from .forms import LeaveRequestForm, LeaveReviewForm, LeaveTypeForm, StandInResponseForm, StandInNomineeForm
from . import workflow
from . import standin
from .approval_letter import approval_letter_pdf_response


@login_required
def my_leave_requests(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account yet.")
        return redirect("dashboard:router")

    requests_qs = (
        employee.leave_requests.select_related("leave_type", "stand_in_employee__user")
        .prefetch_related("approval_steps__acted_by", "stand_in_requests__stand_in_employee__user")
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = LeaveRequestForm(request.POST, employee=employee)
        if form.is_valid():
            leave_request = form.save(commit=False)
            leave_request.employee = employee
            leave_request.status = LeaveStatus.AWAITING_STANDIN
            leave_request.save()
            standin.create_stand_in_request(leave_request, form.cleaned_data["stand_in_employee"])
            log_change(
                request,
                "leave_submit",
                instance=leave_request,
                old_data={},
                new_data=serialize_instance(leave_request),
            )
            messages.success(
                request,
                "Leave request submitted. Your nominated stand-in must accept before approval begins.",
            )
            return redirect("leave:my_requests")
        messages.error(request, "Please fix the errors below.")
    else:
        form = LeaveRequestForm(employee=employee)

    html = render_to_string("leave/_request_modal_body.html", {"form": form}, request=request)
    return render(
        request,
        "leave/my_requests.html",
        {
            "requests": requests_qs,
            "form": form,
            "modal_html": html,
            "balance": employee.leave_balance_days,
        },
    )


@login_required
def leave_request_cancel(request, pk):
    employee = getattr(request.user, "employee_profile", None)
    leave_request = get_object_or_404(LeaveRequest, pk=pk, employee=employee)
    if request.method == "POST" and leave_request.status in (LeaveStatus.PENDING, LeaveStatus.AWAITING_STANDIN):
        if leave_request.approval_steps.filter(status="approved").exists():
            messages.error(request, "This request has already progressed in the approval chain and cannot be cancelled.")
        else:
            leave_request.status = LeaveStatus.CANCELLED
            leave_request.current_stage = ""
            leave_request.save()
            leave_request.approval_steps.filter(status__in=["waiting", "pending"]).update(status="skipped")
            leave_request.stand_in_requests.filter(status=LeaveStandInStatus.PENDING).update(
                status=LeaveStandInStatus.CANCELLED,
            )
            messages.info(request, "Leave request cancelled.")
    return redirect("leave:my_requests")


@login_required
def leave_renominate_standin(request, pk):
    employee = getattr(request.user, "employee_profile", None)
    leave_request = get_object_or_404(LeaveRequest, pk=pk, employee=employee)
    if leave_request.status != LeaveStatus.AWAITING_STANDIN:
        messages.error(request, "You can only change stand-in while awaiting acceptance.")
        return redirect("leave:detail", pk=pk)

    if request.method == "POST":
        form = StandInNomineeForm(request.POST, leave_request=leave_request)
        if form.is_valid():
            standin.create_stand_in_request(leave_request, form.cleaned_data["stand_in_employee"])
            messages.success(request, "New stand-in request sent.")
            return redirect("leave:detail", pk=pk)
        messages.error(request, "Please select a valid stand-in colleague.")
    else:
        form = StandInNomineeForm(leave_request=leave_request)

    return render(request, "leave/renominate_standin.html", {"form": form, "leave_request": leave_request})


@login_required
def stand_in_requests(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")

    pending = standin.pending_stand_in_for(employee)
    history = standin.stand_in_history_for(employee)
    return render(request, "leave/stand_in_requests.html", {
        "pending": pending,
        "history": history,
    })


@login_required
def stand_in_respond(request, pk):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard:router")

    stand_in_req = get_object_or_404(
        LeaveStandInRequest,
        pk=pk,
        stand_in_employee=employee,
        status=LeaveStandInStatus.PENDING,
    )

    if request.method == "POST":
        form = StandInResponseForm(request.POST)
        if form.is_valid():
            try:
                if form.cleaned_data["decision"] == "accepted":
                    standin.accept_stand_in(stand_in_req, request.user, form.cleaned_data.get("remarks", ""))
                    messages.success(request, "You accepted the stand-in request. Managerial approval will now begin.")
                else:
                    standin.decline_stand_in(stand_in_req, request.user, form.cleaned_data.get("remarks", ""))
                    messages.info(request, "You declined the stand-in request.")
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
            return redirect("leave:stand_in")
    else:
        form = StandInResponseForm()

    return render(request, "leave/stand_in_respond.html", {
        "stand_in_request": stand_in_req,
        "leave_request": stand_in_req.leave_request,
        "form": form,
    })


@login_required
def leave_request_detail(request, pk):
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related(
            "employee__user", "employee__department", "leave_type", "stand_in_employee__user",
        ).prefetch_related("approval_steps__acted_by", "stand_in_requests__stand_in_employee__user"),
        pk=pk,
    )
    employee = getattr(request.user, "employee_profile", None)
    is_owner = employee and leave_request.employee_id == employee.pk
    is_stand_in = employee and leave_request.stand_in_employee_id == employee.pk
    can_review = workflow.user_can_review_request(request.user, leave_request)
    is_hr_or_gm = workflow.can_act_as_hr(request.user) or workflow.can_act_as_gm(request.user)
    is_hod_for = workflow.is_department_head_for(request.user, leave_request.employee)

    if not (is_owner or is_stand_in or can_review or is_hr_or_gm or is_hod_for or request.user.is_superuser):
        messages.error(request, "You don't have access to this leave request.")
        return redirect("dashboard:router")

    can_download = leave_request.status == LeaveStatus.APPROVED and (
        is_owner or is_stand_in or is_hr_or_gm or is_hod_for or request.user.is_superuser
    )
    show_renominate = (
        is_owner
        and leave_request.status == LeaveStatus.AWAITING_STANDIN
        and leave_request.active_stand_in_request
        and leave_request.active_stand_in_request.status == LeaveStandInStatus.DECLINED
    )

    return render(
        request,
        "leave/detail.html",
        {
            "leave_request": leave_request,
            "can_review": can_review,
            "is_owner": is_owner,
            "is_stand_in": is_stand_in,
            "can_download": can_download,
            "show_renominate": show_renominate,
            "review_form": LeaveReviewForm() if can_review else None,
        },
    )


@login_required
def leave_approval_letter(request, pk):
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related("employee", "stand_in_employee", "leave_type").prefetch_related("approval_steps"),
        pk=pk,
        status=LeaveStatus.APPROVED,
    )
    employee = getattr(request.user, "employee_profile", None)
    is_owner = employee and leave_request.employee_id == employee.pk
    is_stand_in = employee and leave_request.stand_in_employee_id == employee.pk
    is_hr_or_gm = workflow.can_act_as_hr(request.user) or workflow.can_act_as_gm(request.user)
    is_hod_for = workflow.is_department_head_for(request.user, leave_request.employee)
    if not (is_owner or is_stand_in or is_hr_or_gm or is_hod_for or request.user.is_superuser):
        messages.error(request, "You don't have access to this document.")
        return redirect("dashboard:router")
    return approval_letter_pdf_response(leave_request, request)


@login_required
def leave_verify(request, ref):
    doc = get_object_or_404(
        LeaveApprovalDocument.objects.select_related(
            "leave_request__employee", "leave_request__stand_in_employee", "leave_request__leave_type",
        ),
        reference_number=ref,
    )
    return render(request, "leave/verify.html", {"document": doc, "leave_request": doc.leave_request})


@login_required
@permission_required("approve_leave")
def leave_approvals(request):
    qs = workflow.pending_for_user(request.user)
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    history = workflow.visible_history_for_user(request.user)

    return render(
        request,
        "leave/approvals.html",
        {
            "page_obj": page_obj,
            "history": history,
            "is_hr": workflow.can_act_as_hr(request.user),
            "is_gm": workflow.can_act_as_gm(request.user),
        },
    )


@login_required
@permission_required("approve_leave")
def leave_review(request, pk):
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related(
            "employee__user", "employee__department", "leave_type", "stand_in_employee__user",
        ).prefetch_related("approval_steps", "stand_in_requests"),
        pk=pk,
    )

    if not leave_request.stand_in_accepted:
        messages.error(request, "Cannot approve — stand-in has not accepted this request.")
        return redirect("leave:approvals")

    if not workflow.user_can_review_request(request.user, leave_request):
        messages.error(request, "You cannot action this request at its current approval stage.")
        return redirect("leave:approvals")

    if request.method == "POST":
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            old = serialize_instance(leave_request)
            try:
                msg = workflow.process_decision(
                    leave_request,
                    request.user,
                    form.cleaned_data["decision"],
                    form.cleaned_data.get("review_note", ""),
                )
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
                return redirect("leave:approvals")
            leave_request.refresh_from_db()
            log_change(
                request,
                "leave_review",
                instance=leave_request,
                old_data=old,
                new_data=serialize_instance(leave_request),
            )
            messages.success(request, msg)
            return redirect("leave:approvals")

    form = LeaveReviewForm()
    html = render_to_string(
        "leave/_review_modal_body.html",
        {"form": form, "leave_request": leave_request},
        request=request,
    )
    return JsonResponse({"html": html})


@login_required
@permission_required("manage_leave_types")
def leave_type_list(request):
    leave_types = LeaveType.objects.all()
    form = LeaveTypeForm()
    if request.method == "POST":
        form = LeaveTypeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Leave type added.")
            return redirect("leave:types")
    return render(request, "leave/types.html", {"leave_types": leave_types, "form": form})
