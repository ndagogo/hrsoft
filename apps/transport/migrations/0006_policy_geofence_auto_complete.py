# Generated manually for geofence auto-complete / accuracy policy fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0005_policy_cost_cancel_phase7"),
    ]

    operations = [
        migrations.AddField(
            model_name="transportationpolicy",
            name="auto_complete_enabled",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, complete the ride once all required passengers are ARRIVED "
                "(cancelled/no-show/rejected excluded). Drivers can still End ride manually.",
            ),
        ),
        migrations.AddField(
            model_name="transportationpolicy",
            name="auto_start_max_accuracy_m",
            field=models.PositiveIntegerField(
                default=50,
                help_text="Ignore auto-start if GPS accuracy is worse than this many metres (0 = no check).",
            ),
        ),
        migrations.AddField(
            model_name="transportationpolicy",
            name="auto_start_min_speed_kmh",
            field=models.DecimalField(
                decimal_places=1,
                default=0,
                help_text="Optional: if > 0 and speed is reported, require at least this speed (km/h) when leaving origin.",
                max_digits=5,
            ),
        ),
        migrations.AlterField(
            model_name="transportationpolicy",
            name="auto_arrival_enabled",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, mark passengers arrived when the vehicle enters their destination geofence.",
            ),
        ),
        migrations.AlterField(
            model_name="transportationpolicy",
            name="auto_start_enabled",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, start the journey after the vehicle leaves the origin geofence "
                "(must first have been inside). Requires READY/DRIVER_ACCEPTED; accuracy safeguard applies.",
            ),
        ),
    ]
