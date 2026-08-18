from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .forms import ChannelForm, ChannelUpdateForm, ReplyForm
from .models import Channel, Conversation
from .services import send_reply


@require_permission("communications.view")
def conversation_list(request):
    conversations = Conversation.objects.all().select_related(  # tenant-scoped
        "customer", "channel", "assigned_to"
    )
    return render(request, "communications/conversation_list.html", {"conversations": conversations})


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
    channels = Channel.objects.all()  # TenantManager filters by company.
    return render(request, "communications/channel_list.html", {"channels": channels})


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
