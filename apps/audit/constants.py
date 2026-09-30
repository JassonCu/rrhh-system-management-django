"""Catálogo cerrado de acciones auditables.

Los **valores** son ASCII estable y nunca se traducen: entran en consultas,
filtros e informes, y deben ser idénticos sea cual sea el idioma del actor. Solo
se traduce la etiqueta (§O.3.1).

Ver docs/database/06-diccionario-de-datos.md §G.17.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    # --- Autenticación (Fase 2) ---
    LOGIN = "LOGIN", _("Sign in")
    LOGIN_FAILED = "LOGIN_FAILED", _("Failed sign-in")
    LOGOUT = "LOGOUT", _("Sign out")
    PASSWORD_CHANGE = "PASSWORD_CHANGE", _("Password change")
    PASSWORD_RESET_REQUEST = "PASSWORD_RESET_REQUEST", _("Password reset requested")
    PASSWORD_RESET_COMPLETE = "PASSWORD_RESET_COMPLETE", _("Password reset completed")
    EMAIL_VERIFIED = "EMAIL_VERIFIED", _("Email verified")

    # --- Cuentas y permisos ---
    USER_CREATE = "USER_CREATE", _("User created")
    USER_DEACTIVATE = "USER_DEACTIVATE", _("User deactivated")
    ACTIVATION_CODE_ISSUE = "ACTIVATION_CODE_ISSUE", _("Activation code issued")
    ACTIVATION_CODE_REDEEM = "ACTIVATION_CODE_REDEEM", _("Activation code redeemed")
    ACTIVATION_CODE_FAILED = "ACTIVATION_CODE_FAILED", _("Activation code rejected")
    ACTIVATION_CODE_REVOKE = "ACTIVATION_CODE_REVOKE", _("Activation code revoked")
    ROLE_CHANGE = "ROLE_CHANGE", _("Role changed")
    PERMISSION_CHANGE = "PERMISSION_CHANGE", _("Permission changed")
    PERMISSION_DENIED = "PERMISSION_DENIED", _("Permission denied")

    # --- Organización (Fase 3) ---
    DEPARTMENT_CREATE = "DEPARTMENT_CREATE", _("Department created")
    DEPARTMENT_UPDATE = "DEPARTMENT_UPDATE", _("Department updated")
    DEPARTMENT_DEACTIVATE = "DEPARTMENT_DEACTIVATE", _("Department deactivated")
    POSITION_CREATE = "POSITION_CREATE", _("Position created")
    POSITION_UPDATE = "POSITION_UPDATE", _("Position updated")
    POSITION_DEACTIVATE = "POSITION_DEACTIVATE", _("Position deactivated")
    COMPANY_CREATE = "COMPANY_CREATE", _("Company created")
    COMPANY_UPDATE = "COMPANY_UPDATE", _("Company updated")
    HEADSHIP_ASSIGN = "HEADSHIP_ASSIGN", _("Department head appointed")
    HEADSHIP_END = "HEADSHIP_END", _("Department headship ended")
    JOB_GRADE_CREATE = "JOB_GRADE_CREATE", _("Job grade created")
    JOB_GRADE_UPDATE = "JOB_GRADE_UPDATE", _("Job grade updated")

    # --- Recursos humanos (Fases 3-4) ---
    EMPLOYEE_CREATE = "EMPLOYEE_CREATE", _("Employee created")
    EMPLOYEE_UPDATE = "EMPLOYEE_UPDATE", _("Employee updated")
    EMPLOYEE_VIEW_SENSITIVE = "EMPLOYEE_VIEW_SENSITIVE", _("Sensitive employee data viewed")
    CONTRACT_CREATE = "CONTRACT_CREATE", _("Contract created")
    CONTRACT_UPDATE = "CONTRACT_UPDATE", _("Contract updated")
    CONTRACT_TERMINATE = "CONTRACT_TERMINATE", _("Contract terminated")
    SALARY_CHANGE = "SALARY_CHANGE", _("Salary changed")
    SALARY_VIEW = "SALARY_VIEW", _("Salary history viewed")
    ASSIGNMENT_CREATE = "ASSIGNMENT_CREATE", _("Assignment created")
    ASSIGNMENT_END = "ASSIGNMENT_END", _("Assignment ended")

    # --- Fases 5-8 ---
    LEAVE_CREATE = "LEAVE_CREATE", _("Leave request drafted")
    LEAVE_SUBMIT = "LEAVE_SUBMIT", _("Leave request submitted")
    LEAVE_APPROVE = "LEAVE_APPROVE", _("Leave request approved")
    LEAVE_REJECT = "LEAVE_REJECT", _("Leave request rejected")
    LEAVE_CANCEL = "LEAVE_CANCEL", _("Leave request cancelled")
    LEAVE_BALANCE_ADJUST = "LEAVE_BALANCE_ADJUST", _("Leave balance adjusted")
    LEAVE_ACCRUAL = "LEAVE_ACCRUAL", _("Leave accrued")
    LEAVE_TYPE_CREATE = "LEAVE_TYPE_CREATE", _("Leave type created")
    LEAVE_TYPE_UPDATE = "LEAVE_TYPE_UPDATE", _("Leave type updated")
    ATTENDANCE_PUNCH_FOR_OTHER = (
        "ATTENDANCE_PUNCH_FOR_OTHER",
        _("Attendance recorded for another person"),
    )
    ATTENDANCE_ADJUST = "ATTENDANCE_ADJUST", _("Attendance adjusted")
    ATTENDANCE_INCIDENT_RESOLVE = "ATTENDANCE_INCIDENT_RESOLVE", _("Attendance incident resolved")
    WORK_SCHEDULE_CREATE = "WORK_SCHEDULE_CREATE", _("Work schedule created")
    WORK_SCHEDULE_ASSIGN = "WORK_SCHEDULE_ASSIGN", _("Work schedule assigned")
    DOCUMENT_TYPE_CREATE = "DOCUMENT_TYPE_CREATE", _("Document type created")
    DOCUMENT_TYPE_UPDATE = "DOCUMENT_TYPE_UPDATE", _("Document type updated")
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD", _("Document uploaded")
    DOCUMENT_DOWNLOAD = "DOCUMENT_DOWNLOAD", _("Document downloaded")
    DOCUMENT_DELETE = "DOCUMENT_DELETE", _("Document archived")
    PAYROLL_RUN_EXECUTE = "PAYROLL_RUN_EXECUTE", _("Payroll run executed")
    PAYROLL_RUN_APPROVE = "PAYROLL_RUN_APPROVE", _("Payroll run approved")
    EXPORT_DATA = "EXPORT_DATA", _("Data exported")


class AuditOutcome(models.TextChoices):
    SUCCESS = "SUCCESS", _("Success")
    FAILURE = "FAILURE", _("Failure")
    DENIED = "DENIED", _("Denied")
