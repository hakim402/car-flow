"""Shared test factories for the mandatory test gates (agent.md §10 Step 12).

Tenancy rule observed everywhere: a child's `company` follows its parent via
``SelfAttribute("..company")`` so fixtures never mix tenants by accident.
"""
import factory
from django.contrib.auth import get_user_model

from decimal import Decimal

from apps.communications.models import Channel, ChannelType
from apps.customers.models import Customer
from apps.organizations.models import Organization
from apps.sales.models import Sale
from apps.vehicles.models import Vehicle


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Company {chr(65 + n % 26)}{n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: f"user{n}")
    company = factory.SubFactory(OrganizationFactory)
    password = factory.PostGenerationMethodCall("set_password", "test-password-123")


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    company = factory.SubFactory(OrganizationFactory)
    full_name = factory.Sequence(lambda n: f"Customer {n}")
    phone = factory.Sequence(lambda n: f"+937000000{n:02d}")


class VehicleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vehicle

    company = factory.SubFactory(OrganizationFactory)
    vin = factory.Sequence(lambda n: f"VIN{n:014d}")  # exactly 17 chars
    make = "Toyota"
    model = "Corolla"
    year = 2022


class SaleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Sale

    company = factory.SubFactory(OrganizationFactory)
    # Customer and vehicle must belong to the SAME company as the sale.
    customer = factory.SubFactory(
        CustomerFactory, company=factory.SelfAttribute("..company")
    )
    vehicle = factory.SubFactory(
        VehicleFactory, company=factory.SelfAttribute("..company")
    )
    agreed_amount = Decimal("15000.00")
    currency = "USD"
    sale_date = factory.Faker("date_this_year")


class ChannelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Channel

    company = factory.SubFactory(OrganizationFactory)
    type = ChannelType.WHATSAPP
