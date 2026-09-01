from django.utils import timezone
import pytest
from django.test import override_settings

from apps.accounts.models import Role
from apps.communications.models import Notification, NotificationEvent, NotificationStatus
from apps.communications.services import notify_internal_users
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, UserFactory


@pytest.mark.django_db
def test_notify_internal_users_routes_by_role():
    company = OrganizationFactory()
    sales_role, _ = Role.objects.get_or_create(key="sales", defaults={"name": "Sales"})
    inventory_role, _ = Role.objects.get_or_create(key="inventory", defaults={"name": "Inventory"})

    sales_user = UserFactory(company=company)
    sales_user.roles.add(sales_role)
    inventory_user = UserFactory(company=company)
    inventory_user.roles.add(inventory_role)

    with company_scope(company):
        notifications = notify_internal_users(
            company=company,
            event_key="new_vehicle_added",
            roles=["sales"],
            context={"vehicle": "Toyota Corolla 2024"},
        )

    assert len(notifications) == 1
    assert notifications[0].recipient == sales_user
    assert notifications[0].company == company
    assert "Toyota Corolla 2024" in notifications[0].message
    with company_scope(company):
        assert Notification.objects.filter(company=company, recipient=sales_user).exists()
        assert not Notification.objects.filter(company=company, recipient=inventory_user).exists()


@pytest.mark.django_db
def test_user_unread_notifications_count_ignores_read_items():
    company = OrganizationFactory()
    user = UserFactory(company=company)
    event = NotificationEvent.objects.create(key="invoice_ready", label="Invoice ready")

    with company_scope(company):
        Notification.objects.create(
            company=company,
            recipient=user,
            event=event,
            title="First alert",
            message="Unread",
            channel="in_app",
        )
        Notification.objects.create(
            company=company,
            recipient=user,
            event=event,
            title="Second alert",
            message="Already read",
            channel="in_app",
            read_at=timezone.now(),
        )

    assert user.unread_notifications_count == 1


@pytest.mark.django_db
@override_settings(EMAIL_ENABLED=False, SMS_ENABLED=False, META_ENABLED=False)
def test_disabled_provider_channels_are_skipped_without_crashing():
    company = OrganizationFactory()
    user = UserFactory(company=company)

    with company_scope(company):
        notifications = notify_internal_users(
            company=company,
            event_key="payment_received",
            users=[user],
            context={"amount": "5000", "currency": "USD"},
            channel="email",
        )

    assert len(notifications) == 1
    assert notifications[0].status == NotificationStatus.SKIPPED_DISABLED
    assert notifications[0].channel == "email"
