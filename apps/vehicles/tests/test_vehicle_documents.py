"""Vehicle cards, photo gallery and per-vehicle documents (agent.md §10).

Covers the Phase 2 documents work: the card grid exposes the primary photo,
the detail page splits attachments into gallery vs. paperwork, and the
vehicle-locked upload route attaches files to the right tenant's vehicle.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import UserFactory, VehicleFactory
from apps.documents.models import Document, DocumentType


@pytest.fixture
def company_user(db):
    """Company user holding the vehicle/document permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("vehicles.view", "documents.view", "documents.add")
    ]
    role, _ = Role.objects.get_or_create(key="vehicle_docs_test", defaults={"name": "Vehicle docs test"})
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def vehicle_with_files(company_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    vehicle = VehicleFactory(company=company_user.company)
    photo = Document.all_objects.create(
        company=company_user.company,
        vehicle=vehicle,
        doc_type=DocumentType.VEHICLE_PHOTO,
        title="Front view",
        file=SimpleUploadedFile("front.jpg", b"fake-photo", "image/jpeg"),
    )
    license_doc = Document.all_objects.create(
        company=company_user.company,
        vehicle=vehicle,
        doc_type=DocumentType.LICENSE,
        title="Vehicle license",
        file=SimpleUploadedFile("license.pdf", b"fake-pdf", "application/pdf"),
    )
    return vehicle, photo, license_doc


@pytest.mark.django_db
def test_list_renders_card_with_primary_photo(client, company_user, vehicle_with_files):
    vehicle, photo, _ = vehicle_with_files
    client.force_login(company_user)

    response = client.get(reverse("vehicles:list"))

    assert response.status_code == 200
    content = response.content.decode()
    # Card: photo thumbnail + quick facts + link to the full record.
    assert photo.file.url in content
    assert f"{vehicle.make} {vehicle.model}" in content
    assert vehicle.get_absolute_url() in content


@pytest.mark.django_db
def test_detail_shows_gallery_and_documents(client, company_user, vehicle_with_files):
    vehicle, photo, license_doc = vehicle_with_files
    client.force_login(company_user)

    response = client.get(vehicle.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert photo.file.url in content  # gallery thumbnail
    assert license_doc.title in content  # paperwork table row
    assert license_doc.file.url in content  # download link
    assert reverse("documents:upload_for_vehicle", args=[vehicle.pk]) in content


@pytest.mark.django_db
def test_missing_photo_uses_placeholders_instead_of_broken_media_links(
    client, company_user, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    vehicle = VehicleFactory(company=company_user.company)
    missing_photo = Document.all_objects.create(
        company=company_user.company,
        vehicle=vehicle,
        doc_type=DocumentType.VEHICLE_PHOTO,
        title="Missing front view",
        file="documents/2026/09/missing-front.jpg",
    )
    client.force_login(company_user)

    assert not missing_photo.file_exists

    list_response = client.get(reverse("vehicles:list"))
    detail_response = client.get(vehicle.get_absolute_url())
    document_response = client.get(reverse("documents:list"))

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert document_response.status_code == 200
    assert missing_photo.file.url not in list_response.content.decode()
    assert missing_photo.file.url not in detail_response.content.decode()
    assert missing_photo.file.url not in document_response.content.decode()
    assert "No vehicle photo" in list_response.content.decode()
    assert "No vehicle photos yet" in detail_response.content.decode()
    assert "File missing from storage" in document_response.content.decode()


@pytest.mark.django_db
def test_upload_for_vehicle_attaches_document(client, company_user, vehicle_with_files, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    vehicle, _, _ = vehicle_with_files
    client.force_login(company_user)

    response = client.post(
        reverse("documents:upload_for_vehicle", args=[vehicle.pk]),
        {
            "doc_type": DocumentType.SALE_DOCUMENT,
            "title": "Sale contract",
            "vehicle": vehicle.pk,
            "file": SimpleUploadedFile("contract.pdf", b"pdf-bytes", "application/pdf"),
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == vehicle.get_absolute_url()
    document = Document.all_objects.get(title="Sale contract")
    assert document.vehicle == vehicle
    assert document.company == company_user.company
    assert document.uploaded_by == company_user


@pytest.mark.django_db
def test_upload_for_foreign_company_vehicle_404s(client, company_user):
    foreign_vehicle = VehicleFactory()  # its own (different) company
    client.force_login(company_user)

    response = client.get(reverse("documents:upload_for_vehicle", args=[foreign_vehicle.pk]))

    assert response.status_code == 404
