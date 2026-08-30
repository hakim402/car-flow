from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, UserFactory
from apps.vehicles.forms import VehicleForm
from apps.vehicles.models import Vehicle


@pytest.mark.django_db
def test_vehicle_supports_extended_identity_fields():
    company = OrganizationFactory()
    with company_scope(company):
        vehicle = Vehicle.objects.create(
            company=company,
            vin="VIN12345678901234",
            make="Toyota",
            model="Corolla",
            year=2022,
            color="Silver",
            mileage=25000,
            plate_number="AB-123-XY",
            registration_number="REG-4401",
            engine_number="2ZR-1234567",
            chassis_number="CHS-987654",
            body_type="sedan",
            fuel_type="petrol",
            transmission="automatic",
            drive_type="fwd",
            model_variant="XLI",
            door_count=4,
            seating_capacity=5,
            country_of_origin="AF",
            first_registration_date="2022-05-12",
        )

    assert vehicle.plate_number == "AB-123-XY"
    assert vehicle.registration_number == "REG-4401"
    assert vehicle.engine_number == "2ZR-1234567"
    assert vehicle.chassis_number == "CHS-987654"
    assert vehicle.body_type == "sedan"
    assert vehicle.fuel_type == "petrol"
    assert vehicle.transmission == "automatic"
    assert vehicle.drive_type == "fwd"
    assert vehicle.model_variant == "XLI"
    assert vehicle.door_count == 4
    assert vehicle.seating_capacity == 5
    assert vehicle.country_of_origin == "AF"
    assert str(vehicle.first_registration_date) == "2022-05-12"


@pytest.mark.django_db
def test_vehicle_form_includes_extended_identity_fields():
    form = VehicleForm()
    assert "plate_number" in form.fields
    assert "registration_number" in form.fields
    assert "engine_number" in form.fields
    assert "chassis_number" in form.fields
    assert "body_type" in form.fields
    assert "fuel_type" in form.fields
    assert "transmission" in form.fields
    assert "drive_type" in form.fields
    assert "model_variant" in form.fields
    assert "door_count" in form.fields
    assert "seating_capacity" in form.fields
    assert "country_of_origin" in form.fields
    assert "first_registration_date" in form.fields


@pytest.mark.django_db
def test_vehicle_form_has_required_help_text_for_core_fields():
    form = VehicleForm()
    for field_name in ["make", "model", "year", "color", "mileage", "branch", "notes"]:
        assert form.fields[field_name].help_text, f"Missing help text for {field_name}"


@pytest.mark.django_db
def test_created_vehicle_appears_in_branch_list(client):
    company = OrganizationFactory()
    branch = Branch.objects.create(company=company, name="Main Yard")
    user = UserFactory(company=company, branch=branch)
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("vehicles.view", "vehicles.add")
    ]
    role, _ = Role.objects.get_or_create(
        key="vehicles_branch_test",
        defaults={"name": "Vehicles branch test"},
    )
    role.permissions.set(permissions)
    user.roles.add(role)

    client.force_login(user)
    response = client.post(
        reverse("vehicles:create"),
        {
            "vin": "VIN12345678901234",
            "plate_number": "AB-123-XY",
            "registration_number": "REG-4401",
            "engine_number": "ENG-10001",
            "chassis_number": "CHS-10001",
            "make": "Toyota",
            "model": "Corolla",
            "model_variant": "XLI",
            "year": "2022",
            "color": "Silver",
            "mileage": "25000",
            "body_type": "sedan",
            "fuel_type": "petrol",
            "transmission": "automatic",
            "drive_type": "fwd",
            "door_count": "4",
            "seating_capacity": "5",
            "country_of_origin": "AF",
            "first_registration_date": "2022-05-12",
            "branch": str(branch.pk),
        },
    )

    assert response.status_code == 302
    with company_scope(company):
        vehicle = Vehicle.objects.get(vin="VIN12345678901234")
        assert vehicle.stock.branch == branch

    list_response = client.get(reverse("vehicles:list"))
    assert list_response.status_code == 200
    assert "VIN12345678901234" in list_response.content.decode()
