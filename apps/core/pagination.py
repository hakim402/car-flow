"""Small shared helpers for searchable operational list pages."""

from django.core.paginator import Paginator


DEFAULT_PAGE_SIZE = 15


def pagination_context(request, records, *, page_size=DEFAULT_PAGE_SIZE):
    """Paginate a queryset while preserving every non-page query parameter."""
    page_obj = Paginator(records, page_size).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "page_obj": page_obj,
        "page_range": page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=1, on_ends=1
        ),
        "pagination_query": query.urlencode(),
    }
