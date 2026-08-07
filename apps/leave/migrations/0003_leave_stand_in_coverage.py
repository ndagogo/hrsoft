# Leave stand-in coverage and approval documents

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0002_enterprise_upgrade"),
        ("leave", "0002_leave_approval_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="leaverequest",
            name="handover_notes",
            field=models.TextField(blank=True, help_text="Tasks, contacts, and instructions for the stand-in officer."),
        ),
        migrations.AddField(
            model_name="leaverequest",
            name="stand_in_employee",
            field=models.ForeignKey(
                blank=True, help_text="Nominated colleague to cover duties during leave.",
                null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="stand_in_for_leave_requests", to="employees.employee",
            ),
        ),
        migrations.AlterField(
            model_name="leaverequest",
            name="status",
            field=models.CharField(choices=[
                ("awaiting_standin", "Awaiting Stand-in"),
                ("pending", "Pending"), ("approved", "Approved"),
                ("rejected", "Rejected"), ("cancelled", "Cancelled"),
            ], default="awaiting_standin", max_length=20),
        ),
        migrations.CreateModel(
            name="LeaveStandInRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[
                    ("pending", "Pending"), ("accepted", "Accepted"), ("declined", "Declined"),
                    ("cancelled", "Cancelled"), ("expired", "Expired"),
                ], default="pending", max_length=20)),
                ("remarks", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("employee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="leave_stand_in_outgoing", to="employees.employee",
                )),
                ("leave_request", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="stand_in_requests", to="leave.leaverequest",
                )),
                ("stand_in_employee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="leave_stand_in_incoming", to="employees.employee",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="LeaveApprovalDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference_number", models.CharField(max_length=30, unique=True)),
                ("verification_code", models.CharField(max_length=64, unique=True)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("leave_request", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="approval_document", to="leave.leaverequest",
                )),
            ],
            options={"ordering": ["-generated_at"]},
        ),
    ]
