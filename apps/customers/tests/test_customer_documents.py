"""Customer cards, photo gallery and per-customer documents (agent.md §10).

Mirrors the vehicle documents work: the card grid exposes the customer photo,
the detail page splits attachments into gallery vs. paperwork (tazkera,
passport, bills), and the customer-locked upload route attaches files to the
right tenant's customer.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import CustomerFactory, UserFactory
from apps.documents.models import Document, DocumentType


@pytest.fixture
def company_user(db):
    """Company user holding the customer/document permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("customers.view", "documents.view", "documents.add")
    ]
    role, _ = Role.objects.get_or_create(
        key="customer_docs_test", defaults={"name": "Customer docs test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def customer_with_files(company_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    customer = CustomerFactory(company=company_user.company)
    photo = Document.all_objects.create(
        company=company_user.company,
        customer=customer,
        doc_type=DocumentType.CUSTOMER_PHOTO,
        title="Portrait",
        file=SimpleUploadedFile("portrait.jpg", b"fake-photo", "image/jpeg"),
    )
    tazkera = Document.all_objects.create(
        company=company_user.company,
        customer=customer,
        doc_type=DocumentType.TAZKERA,
        title="Tazkera scan",
        file=SimpleUploadedFile("tazkera.pdf", b"fake-pdf", "application/pdf"),
    )
    return customer, photo, tazkera


@pytest.mark.django_db
def test_list_renders_card_with_photo(client, company_user, customer_with_files):
    customer, photo, _ = customer_with_files
    client.force_login(company_user)

    response = client.get(reverse("customers:list"))

    assert response.status_code == 200
    content = response.content.decode()
    # Card: photo avatar + quick facts + link to the full record.
    assert photo.file.url in content
    assert customer.full_name in content
    assert customer.phone in content
    assert customer.get_absolute_url() in content


@pytest.mark.django_db
def test_detail_shows_gallery_and_documents(client, company_user, customer_with_files):
    customer, photo, tazkera = customer_with_files
    client.force_login(company_user)

    response = client.get(customer.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert photo.file.url in content  # gallery thumbnail
    assert tazkera.title in content  # paperwork table row
    assert tazkera.file.url in content  # download link
    assert reverse("documents:upload_for_customer", args=[customer.pk]) in content


@pytest.mark.django_db
def test_upload_for_customer_attaches_document(
    client, company_user, customer_with_files, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    customer, _, _ = customer_with_files
    client.force_login(company_user)

    response = client.post(
        reverse("documents:upload_for_customer", args=[customer.pk]),
        {
            "doc_type": DocumentType.ELECTRICITY_BILL,
            "title": "Electricity bill",
            "customer": customer.pk,
            "file": SimpleUploadedFile("bill.pdf", b"pdf-bytes", "application/pdf"),
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == customer.get_absolute_url()
    document = Document.all_objects.get(title="Electricity bill")
    assert document.customer == customer
    assert document.company == company_user.company
    assert document.uploaded_by == company_user


@pytest.mark.django_db
def test_upload_for_foreign_company_customer_404s(client, company_user):
    foreign_customer = CustomerFactory()  # its own (different) company
    client.force_login(company_user)

    response = client.get(
        reverse("documents:upload_for_customer", args=[foreign_customer.pk])
    )

    assert response.status_code == 404
