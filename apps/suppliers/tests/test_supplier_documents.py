"""Supplier logo/documents (agent.md §10): logo on the card grid, paperwork
table on the detail page, and the supplier-locked upload route."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import SupplierFactory, UserFactory
from apps.documents.models import Document, DocumentType


@pytest.fixture
def company_user(db):
    """Company user holding the supplier/document permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("suppliers.view", "documents.view", "documents.add")
    ]
    role, _ = Role.objects.get_or_create(
        key="supplier_docs_test", defaults={"name": "Supplier docs test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def supplier_with_files(company_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    supplier = SupplierFactory(company=company_user.company)
    logo = Document.all_objects.create(
        company=company_user.company,
        supplier=supplier,
        doc_type=DocumentType.SUPPLIER_LOGO,
        title="Logo",
        file=SimpleUploadedFile("logo.png", b"fake-logo", "image/png"),
    )
    license_doc = Document.all_objects.create(
        company=company_user.company,
        supplier=supplier,
        doc_type=DocumentType.SUPPLIER_LICENSE,
        title="Business license",
        file=SimpleUploadedFile("license.pdf", b"fake-pdf", "application/pdf"),
    )
    return supplier, logo, license_doc


@pytest.mark.django_db
def test_list_card_shows_logo(client, company_user, supplier_with_files):
    supplier, logo, _ = supplier_with_files
    client.force_login(company_user)

    response = client.get(reverse("suppliers:list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert logo.file.url in content  # logo image replaces the building icon
    assert supplier.name in content
    assert supplier.get_absolute_url() in content


@pytest.mark.django_db
def test_detail_shows_logo_and_documents(client, company_user, supplier_with_files):
    supplier, logo, license_doc = supplier_with_files
    client.force_login(company_user)

    response = client.get(supplier.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert logo.file.url in content  # header logo
    assert license_doc.title in content  # paperwork table row
    assert license_doc.file.url in content  # download link
    assert reverse("documents:upload_for_supplier", args=[supplier.pk]) in content


@pytest.mark.django_db
def test_upload_for_supplier_attaches_document(
    client, company_user, supplier_with_files, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    supplier, _, _ = supplier_with_files
    client.force_login(company_user)

    response = client.post(
        reverse("documents:upload_for_supplier", args=[supplier.pk]),
        {
            "doc_type": DocumentType.SUPPLIER_DOCUMENT,
            "title": "Import contract",
            "supplier": supplier.pk,
            "file": SimpleUploadedFile("contract.pdf", b"pdf-bytes", "application/pdf"),
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == supplier.get_absolute_url()
    document = Document.all_objects.get(title="Import contract")
    assert document.supplier == supplier
    assert document.company == company_user.company
    assert document.uploaded_by == company_user


@pytest.mark.django_db
def test_upload_for_foreign_company_supplier_404s(client, company_user):
    foreign_supplier = SupplierFactory()  # its own (different) company
    client.force_login(company_user)

    response = client.get(
        reverse("documents:upload_for_supplier", args=[foreign_supplier.pk])
    )

    assert response.status_code == 404
