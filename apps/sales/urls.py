from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    # Leads
    path("leads/", views.lead_list, name="lead_list"),
    path("leads/add/", views.lead_create, name="lead_create"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/status/", views.lead_update_status, name="lead_update_status"),
    # Quotations
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/add/", views.quotation_create, name="quotation_create"),
    path("quotations/<int:pk>/", views.quotation_detail, name="quotation_detail"),
    path("quotations/<int:pk>/status/", views.quotation_update_status, name="quotation_update_status"),
    # Reservations
    path("reservations/", views.reservation_list, name="reservation_list"),
    path("reservations/add/", views.reservation_create, name="reservation_create"),
    path("reservations/<int:pk>/cancel/", views.reservation_cancel, name="reservation_cancel"),
    # Sales + invoices
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/add/", views.sale_create, name="sale_create"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/complete/", views.sale_complete, name="sale_complete"),
    path("sales/<int:pk>/deliver/", views.sale_deliver, name="sale_deliver"),
    path("sales/<int:pk>/invoice/", views.sale_issue_invoice, name="sale_issue_invoice"),
]
