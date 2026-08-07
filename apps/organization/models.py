from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    registration_number = models.CharField(max_length=50, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    logo = models.ImageField(upload_to="company/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Region(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="regions")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("company", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.company.code})"


class Branch(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="branches")
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True, related_name="branches")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_head_office = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("company", "code")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Unit(models.Model):
    """Sub-unit within a department."""
    department = models.ForeignKey("employees.Department", on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("department", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.department.code})"
