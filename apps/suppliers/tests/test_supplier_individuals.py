"""Individual (private-person) suppliers: cars are sometimes bought from
people, so a supplier can be a person carrying tazkera/national ID data and
personal paperwork instead of business details."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import SupplierFactory, UserFactory
from apps.documents.models import Document, DocumentType
from apps.suppliers.models import Supplier, SupplierKind


@pytest.fixture
def company_user(db):
    """Company user holding the supplier/document permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in (
            "suppliers.view",
            "suppliers.add",
            "documents.view",
            "documents.add",
        )
    ]
    role, _ = Role.objects.get_or_create(
        key="individual_supplier_test", defaults={"name": "Individual supplier test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def individual(company_user):
    return SupplierFactory(
        company=company_user.company,
        name="Ahmad Wali",
        kind=SupplierKind.INDIVIDUAL,
        national_id="1399-0001-23456",
    )


@pytest.mark.django_db
def test_create_individual_supplier(client, company_user):
    client.force_login(company_user)

    response = client.post(
        reverse("suppliers:create"),
        {
            "name": "Fatema Noori",
            "kind": SupplierKind.INDIVIDUAL,
            "supplier_type": "other",
            "national_id": "1400-1111-77777",
            "country": "",
            "contact_person": "",
            "phone": "+93700000000",
            "email": "",
            "address": "",
            "notes": "",
        },
    )

    assert response.status_code == 302
    supplier = Supplier.all_objects.get(name="Fatema Noori")
    assert supplier.kind == SupplierKind.INDIVIDUAL
    assert supplier.national_id == "1400-1111-77777"
    assert supplier.company == company_user.company


@pytest.mark.django_db
def test_card_shows_individual_badge_and_tazkera(client, company_user, individual):
    client.force_login(company_user)

    response = client.get(reverse("suppliers:list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert individual.name in content
    assert individual.get_kind_display() in content  # "Individual (person)" badge
    assert individual.national_id in content  # tazkera number on the card


@pytest.mark.django_db
def test_detail_shows_kind_and_national_id(client, company_user, individual):
    client.force_login(company_user)

    response = client.get(individual.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert individual.get_kind_display() in content
    assert individual.national_id in content


@pytest.mark.django_db
def test_upload_tazkera_for_individual_supplier(
    client, company_user, individual, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(company_user)

    response = client.post(
        reverse("documents:upload_for_supplier", args=[individual.pk]),
        {
            "doc_type": DocumentType.TAZKERA,
            "title": "Tazkera scan",
            "supplier": individual.pk,
            "file": SimpleUploadedFile("tazkera.pdf", b"pdf-bytes", "application/pdf"),
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == individual.get_absolute_url()
    document = Document.all_objects.get(title="Tazkera scan")
    assert document.supplier == individual
    assert document.doc_type == DocumentType.TAZKERA
