"""
Public board (M8). No login required.

Templates here receive ONLY dicts produced by public.to_public().
"""

import hashlib

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from apps.catalog.models import Category, Location
from apps.items.models import Item

from .public import VIEWABLE_STATES, to_public
from .search import board_queryset

PAGE_SIZE = 12
FILTER_KEYS = ("q", "kind", "category", "location", "from", "to")


def _cached_page(params, page_number):
    """Cache each page of public results (data only, not the user-specific HTML)."""
    raw = "&".join(f"{k}={params.get(k, '')}" for k in FILTER_KEYS) + f"&p={page_number}"
    key = "board:" + hashlib.md5(raw.encode()).hexdigest()
    data = cache.get(key)
    if data is None:
        page = Paginator(board_queryset(params), PAGE_SIZE).get_page(page_number)
        data = {
            "items": [to_public(i) for i in page.object_list],
            "has_next": page.has_next(),
            "next": page.next_page_number() if page.has_next() else None,
            "count": page.paginator.count,
        }
        cache.set(key, data, settings.BOARD_CACHE_SECONDS)
    return data


def board_list(request):
    params = request.GET
    data = _cached_page(params, request.GET.get("page") or 1)
    querystring = "&".join(f"{k}={params[k]}" for k in FILTER_KEYS if params.get(k))
    ctx = {"page": data, "querystring": querystring, "filters": {k: params.get(k, "") for k in FILTER_KEYS}}
    if request.headers.get("HX-Request") and request.GET.get("page"):
        return render(request, "board/_cards.html", ctx)  # infinite scroll fragment
    ctx.update(
        categories=Category.objects.filter(is_active=True),
        buildings=Location.objects.filter(kind=Location.Kind.BUILDING, is_active=True),
    )
    return render(request, "board/list.html", ctx)


def board_detail(request, pk):
    item = (
        Item.objects.filter(pk=pk, status__in=VIEWABLE_STATES)
        .select_related("category", "location").prefetch_related("photos").first()
    )
    if item is None:
        raise Http404
    public = to_public(item)
    owns = request.user.is_authenticated and item.reporter_id == request.user.pk
    return render(request, "board/detail.html", {"item": public, "is_own_report": owns})
