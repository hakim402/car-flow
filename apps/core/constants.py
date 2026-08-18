"""Project-wide constants shared by money-handling apps (agent.md §9)."""

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
