"""Fixtures del inicio.

Se reutilizan las de `contracts` (que a su vez reutiliza las de `employees`) en
lugar de duplicar fábricas: el inicio se alimenta de ambas apps.
"""

from __future__ import annotations

from apps.contracts.tests import conftest as contract_fixtures

department = contract_fixtures.department
draft = contract_fixtures.draft
grade = contract_fixtures.grade
hire = contract_fixtures.hire
make_employee = contract_fixtures.make_employee
make_person = contract_fixtures.make_person
other_position = contract_fixtures.other_position
position = contract_fixtures.position
