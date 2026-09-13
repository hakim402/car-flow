from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context

from .forms import ChannelForm, ChannelUpdateForm, ReplyForm
from .models import Channel, Conversation, ConversationStatus
from .services import send_reply


@require_permission("communications.view")
def conversation_list(request):
    base_queryset = Conversation.objects.all().select_related(  # tenant-scoped
        "customer", "channel", "assigned_to"
    )
    metrics = {
        "total": base_queryset.count(),
        "open": base_queryset.filter(status=ConversationStatus.OPEN).count(),
        "closed": base_queryset.filter(status=ConversationStatus.CLOSED).count(),
        "unassigned": base_queryset.filter(assigned_to__isnull=True).count(),
    }
    conversations = base_queryset
    q = request.GET.get("q", "").strip()
    if q:
        conversations = conversations.filter(
            Q(customer__full_name__icontains=q)
            | Q(customer__phone__icontains=q)
            | Q(external_thread_id__icontains=q)
            | Q(assigned_to__email__icontains=q)
        )
    status = request.GET.get("status", "")
    if status in ConversationStatus.values:
        conversations = conversations.filter(status=status)
    channel = request.GET.get("channel", "")
    if channel.isdigit():
        conversations = conversations.filter(channel_id=channel)
    page = pagination_context(request, conversations, page_size=15)
    return render(
        request,
        "communications/conversation_list.html",
        {
            **page,
            "conversations": page["page_obj"],
            "metrics": metrics,
            "statuses": ConversationStatus.choices,
            "channels": Channel.objects.all(),
            "filters": request.GET,
        },
    )


@require_permission("communications.view")
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk)
    return render(
        request,
        "communications/conversation_detail.html",
        {
            "conversation": conversation,
            "conversation_messages": conversation.messages.all(),
            "reply_form": ReplyForm(),
        },
    )


@require_permission("communications.add")
@require_POST
def conversation_reply(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk)
    form = ReplyForm(request.POST)
    if form.is_valid():
        send_reply(conversation, form.cleaned_data["body"])
        messages.success(request, _("Reply sent through the channel adapter."))
    else:
        messages.error(request, _("Could not send the reply."))
    return redirect(conversation)


@require_permission("communications.view")
def channel_list(request):
    channels = Channel.objects.annotate(  # TenantManager filters by company.
        conversation_count=Count("conversations", distinct=True),
        identity_count=Count("identities", distinct=True),
    )
    metrics = {
        "total": channels.count(),
        "active": channels.filter(active=True).count(),
        "inactive": channels.filter(active=False).count(),
    }
    return render(
        request,
        "communications/channel_list.html",
        {
            "channels": channels,
            "metrics": metrics,
            "can_add": request.user.has_permission("communications.add"),
        },
    )


@require_permission("communications.add")
def channel_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = ChannelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        Channel.objects.create(
            company=request.user.company,
            type=form.cleaned_data["type"],
            active=form.cleaned_data["active"],
            credentials=form.cleaned_data["credentials"],
        )
        messages.success(request, _("Channel created."))
        return redirect("communications:channel_list")
    return render(request, "communications/channel_form.html", {"form": form, "title": _("Add channel")})


@require_permission("communications.change")
def channel_edit(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    form = ChannelUpdateForm(request.POST or None, instance=channel)
    if request.method == "POST" and form.is_valid():
        channel.type = form.cleaned_data["type"]
        channel.active = form.cleaned_data["active"]
        channel.credentials = form.cleaned_data["credentials"]
        channel.save()
        messages.success(request, _("Channel updated."))
        return redirect("communications:channel_list")
    return render(
        request,
        "communications/channel_form.html",
        {"form": form, "title": _("Edit channel"), "channel": channel},
    )
