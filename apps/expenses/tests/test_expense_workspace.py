from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import UserFactory
from apps.expenses.models import ExpenseCategory
from apps.expenses.services import record_expense
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry


@pytest.fixture
def expense_user(db):
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in (
            "expenses.view",
            "expenses.add",
            "expenses.reverse",
            "expenses.manage_categories",
            "payments.view",
        )
    ]
    role, _ = Role.objects.get_or_create(
        key="expense_workspace_test", defaults={"name": "Expense workspace test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def expense_setup(expense_user):
    with company_scope(expense_user.company):
        branch = Branch.objects.create(company=expense_user.company, name="Kabul")
        account = FinancialAccount.objects.create(
            company=expense_user.company,
            branch=branch,
            name="Kabul AFN cashbox",
            currency="AFN",
            active=True,
        )
        category = ExpenseCategory.objects.create(
            company=expense_user.company,
            name="Office operations",
            code="OFFICE",
        )
    return branch, account, category


@pytest.mark.django_db
def test_expense_inherits_account_branch(expense_user, expense_setup):
    branch, account, category = expense_setup
    with company_scope(expense_user.company):
        entry = record_expense(
            expense_user.company,
            Decimal("250.00"),
            "AFN",
            category=category,
            account=account,
            user=expense_user,
        )
    assert entry.branch == branch
    assert entry.type == EntryType.EXPENSE


@pytest.mark.django_db
def test_expense_rejects_account_currency_mismatch(expense_user, expense_setup):
    _, account, category = expense_setup
    with company_scope(expense_user.company):
        with pytest.raises(ValidationError, match="account currency"):
            record_expense(
                expense_user.company,
                Decimal("250.00"),
                "USD",
                category=category,
                account=account,
                user=expense_user,
            )


@pytest.mark.django_db
def test_expense_create_and_reversal_keep_a_complete_audit_trail(
    client, expense_user, expense_setup
):
    branch, account, category = expense_setup
    client.force_login(expense_user)
    response = client.post(
        reverse("expenses:create"),
        {
            "transaction_date": date.today().isoformat(),
            "category": category.pk,
            "amount": "500.00",
            "currency": "AFN",
            "account": account.pk,
            "branch": branch.pk,
            "vendor": "Office supplier",
            "reference": "EXP-001",
            "description": "Printer supplies",
        },
    )
    assert response.status_code == 302
    expense = LedgerEntry.all_objects.get(reference="EXP-001")
    assert response.headers["Location"] == reverse("expenses:detail", args=[expense.pk])

    response = client.post(
        reverse("expenses:reverse", args=[expense.pk]),
        {"reason": "Duplicate vendor invoice"},
    )
    assert response.status_code == 302
    reversal = LedgerEntry.all_objects.get(reversal_of=expense)
    assert response.headers["Location"] == reverse("expenses:detail", args=[reversal.pk])
    assert reversal.amount == expense.amount
    assert LedgerEntry.all_objects.filter(pk=expense.pk).exists()
