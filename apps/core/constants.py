"""Project-wide constants shared by money-handling apps (agent.md §9)."""
from django.utils.translation import gettext_lazy as _

# ISO 4217 codes used across the system; import costs arrive in USD while
# local sales run in AFN, so both are first-class.
CURRENCIES = (
    ("AFN", "AFN"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("AED", "AED"),
    ("PKR", "PKR"),
    ("IRR", "IRR"),
)

DEFAULT_CURRENCY = "AFN"

# Countries the business buys vehicles from (ISO alpha-2 codes as values).
# Curated to the realistic import corridors — not a full ISO dump — plus an
# OTHER escape hatch for anything outside the list.
COUNTRIES = (
    ("AF", _("Afghanistan")),
    ("AE", _("United Arab Emirates")),
    ("US", _("United States")),
    ("CA", _("Canada")),
    ("DE", _("Germany")),
    ("JP", _("Japan")),
    ("KR", _("South Korea")),
    ("CN", _("China")),
    ("IR", _("Iran")),
    ("PK", _("Pakistan")),
    ("TR", _("Turkey")),
    ("SA", _("Saudi Arabia")),
    ("QA", _("Qatar")),
    ("KW", _("Kuwait")),
    ("IN", _("India")),
    ("RU", _("Russia")),
    ("GB", _("United Kingdom")),
    ("FR", _("France")),
    ("IT", _("Italy")),
    ("NL", _("Netherlands")),
    ("BE", _("Belgium")),
    ("AU", _("Australia")),
    ("OTHER", _("Other")),
)
