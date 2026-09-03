from django.urls import path

from . import views

app_name = "financing"

urlpatterns = [
    path("", views.agreement_list, name="list"),
    path("partners/", views.partner_list, name="partner_list"),
    path("partners/add/", views.partner_create, name="partner_create"),
    path("add/", views.agreement_create, name="create"),
    path("<int:pk>/", views.agreement_detail, name="detail"),
    path("<int:pk>/submit/", views.agreement_submit, name="submit"),
    path("<int:pk>/approve/", views.agreement_approve, name="approve"),
    path("<int:pk>/payment/", views.payment_create, name="payment"),
    path("<int:pk>/lender-disbursement/", views.lender_disbursement_create, name="lender_disbursement"),
    path("<int:pk>/default/", views.agreement_default, name="default"),
    path("<int:pk>/cancel/", views.agreement_cancel, name="cancel"),
    path("<int:pk>/guarantors/add/", views.guarantor_create, name="guarantor_create"),
]
