from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import permission_required, user_has_permission
from apps.employees.scoping import user_can_view_employee

from .forms import DocumentUploadForm
from .models import Document


def _can_view_employee_docs(user, employee) -> bool:
    if user.is_superuser:
        return True
    if user_has_permission(user, "view_employee_documentation") or user_has_permission(user, "manage_documents"):
        return user_can_view_employee(user, employee) or user_has_permission(user, "manage_employees")
    profile = getattr(user, "employee_profile", None)
    return bool(profile and profile.pk == employee.pk)


def _can_manage_employee_docs(user, employee) -> bool:
    if user.is_superuser or user_has_permission(user, "manage_documents"):
        return True
    if user_has_permission(user, "manage_employees") and user_can_view_employee(user, employee):
        return True
    return False


@login_required
@permission_required("view_documents")
def document_list(request):
    qs = Document.objects.select_related("employee__user", "uploaded_by").all()
    if not (
        request.user.is_superuser
        or user_has_permission(request.user, "view_employee_documentation")
        or user_has_permission(request.user, "manage_documents")
    ):
        profile = getattr(request.user, "employee_profile", None)
        qs = qs.filter(employee=profile) if profile else qs.none()
    return render(request, "documents/list.html", {
        "documents": qs[:200],
        "can_manage": user_has_permission(request.user, "manage_documents"),
    })


@login_required
def my_documents(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")

    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES, employee_self_upload=True)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.employee = employee
            doc.uploaded_by = request.user
            doc.is_confidential = False
            doc.save()
            messages.success(request, "Document uploaded successfully.")
            return redirect("documents:my")
        messages.error(request, "Please fix the errors below.")
    else:
        form = DocumentUploadForm(employee_self_upload=True)

    docs = employee.documents.select_related("uploaded_by").all()
    return render(request, "documents/my_documents.html", {
        "employee": employee,
        "documents": docs,
        "form": form,
    })


@login_required
def employee_documents(request, emp_pk):
    from apps.employees.models import Employee
    employee = get_object_or_404(Employee.objects.select_related("user"), pk=emp_pk)
    if not _can_view_employee_docs(request.user, employee):
        messages.error(request, "You don't have permission to view this employee's documents.")
        return redirect("employees:detail", pk=emp_pk)

    can_manage = _can_manage_employee_docs(request.user, employee)
    if request.method == "POST" and can_manage:
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.employee = employee
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, "Document uploaded.")
            return redirect("documents:employee", emp_pk=emp_pk)
        messages.error(request, "Please fix the upload form errors.")
    else:
        form = DocumentUploadForm() if can_manage else None

    return render(request, "documents/employee_documents.html", {
        "employee": employee,
        "documents": employee.documents.select_related("uploaded_by").all(),
        "form": form,
        "can_manage": can_manage,
    })


def _user_can_access_document(user, doc) -> bool:
    if doc.employee_id:
        return _can_view_employee_docs(user, doc.employee)
    return (
        user.is_superuser
        or user_has_permission(user, "view_documents")
        or user_has_permission(user, "manage_documents")
    )


@login_required
def document_download(request, pk):
    doc = get_object_or_404(Document.objects.select_related("employee"), pk=pk)
    if not _user_can_access_document(request.user, doc):
        messages.error(request, "You don't have permission to download this document.")
        return redirect("dashboard:router")
    if not doc.file:
        raise Http404("File not found.")
    return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.file.name.split("/")[-1])


@login_required
def document_view(request, pk):
    """Open / preview a document in the browser (inline)."""
    doc = get_object_or_404(Document.objects.select_related("employee__user", "uploaded_by"), pk=pk)
    if not _user_can_access_document(request.user, doc):
        messages.error(request, "You don't have permission to view this document.")
        return redirect("dashboard:router")
    if not doc.file:
        raise Http404("File not found.")

    name = (doc.file.name or "").lower()
    previewable = name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt"))
    if request.GET.get("raw") == "1" or not previewable:
        response = FileResponse(doc.file.open("rb"), as_attachment=False, filename=doc.file.name.split("/")[-1])
        # Encourage browsers to display rather than download when possible
        response["Content-Disposition"] = f'inline; filename="{doc.file.name.split("/")[-1]}"'
        return response

    return render(request, "documents/view.html", {
        "document": doc,
        "file_url": f"{request.path}?raw=1",
        "is_pdf": name.endswith(".pdf"),
        "is_image": name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")),
        "is_text": name.endswith(".txt"),
    })


@login_required
def document_delete(request, pk):
    doc = get_object_or_404(Document.objects.select_related("employee"), pk=pk)
    employee = doc.employee
    profile = getattr(request.user, "employee_profile", None)
    allowed = False
    if request.user.is_superuser or user_has_permission(request.user, "manage_documents"):
        allowed = True
    elif employee and profile and employee.pk == profile.pk and doc.uploaded_by_id == request.user.pk:
        allowed = True
    elif employee and _can_manage_employee_docs(request.user, employee):
        allowed = True

    if not allowed:
        messages.error(request, "You cannot delete this document.")
        return redirect("dashboard:router")

    if request.method == "POST":
        emp_pk = employee.pk if employee else None
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, "Document deleted.")
        if emp_pk and profile and emp_pk == profile.pk:
            return redirect("documents:my")
        if emp_pk:
            return redirect("documents:employee", emp_pk=emp_pk)
        return redirect("documents:list")
    return redirect("documents:list")
