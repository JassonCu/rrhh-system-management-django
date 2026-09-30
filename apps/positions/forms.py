"""Formularios del catálogo de puestos."""

from __future__ import annotations

from django import forms

from apps.departments.selectors import departments_visible_for
from apps.positions.models import JobGrade, Position


class JobGradeForm(forms.ModelForm):
    class Meta:
        model = JobGrade
        fields = ["code", "name", "level", "min_salary", "max_salary", "currency"]


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ["department", "job_grade", "code", "title", "description"]

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        departments = departments_visible_for(user) if user else Position.objects.none()
        self.fields["department"].queryset = departments.filter(is_active=True)
        self.fields["job_grade"].queryset = JobGrade.objects.filter(is_active=True)
