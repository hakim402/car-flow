from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission

from .forms import DocumentForm
from .models import Document


@require_permission("documents.view")
def document_list(request):
    documents = Document.objects.all().select_related(  # TenantManager scopes.
        "vehicle", "customer"
    )
    return render(request, "documents/list.html", {"documents": documents})


@require_permission("documents.add")
def document_upload(request):
    if request.user.company is None:
        raise PermissionDenied
    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.company = request.user.company
        document.uploaded_by = request.user
        document.save()
        messages.success(request, _("Document uploaded."))
        return redirect("documents:list")
    return render(request, "documents/form.html", {"form": form, "title": _("Upload document")})
