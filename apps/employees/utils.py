from .models import Employee


def generate_employee_id():
    last = Employee.objects.order_by("-id").first()
    next_num = (last.id + 1) if last else 1
    return f"EMP-{next_num:04d}"
