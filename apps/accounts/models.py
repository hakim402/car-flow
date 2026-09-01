"""Users, roles, and granular permissions (agent.md §8).

- Django Admin (/admin/) is Super Admin only: `is_staff` is kept in sync with
  the Super Admin role and forced False for every other role (§8.1).
- Custom roles are supported from day one: Role/Permission are plain tables
  seeded with the six Phase 1 built-ins; later roles are just new rows.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

SUPER_ADMIN_KEY = "super_admin"

BUILTIN_ROLES = (
    (SUPER_ADMIN_KEY, _("Super Admin")),
    ("org_admin", _("Organization Admin")),
    ("branch_manager", _("Branch Manager")),
    ("sales", _("Sales")),
    ("inventory", _("Inventory")),
    ("accountant", _("Accountant")),
)


class Permission(models.Model):
    """Granular, tenant-scoped permission token (beyond Django's app-level
    permissions). Business views check these for object-level access."""

    codename = models.CharField(_("codename"), max_length=100, unique=True)
    description = models.CharField(_("description"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("permission")
        verbose_name_plural = _("permissions")
        ordering = ["codename"]

    def __str__(self):
        return self.codename


class Role(models.Model):
    """Named bundle of Permissions. The six Phase 1 roles are seeded with
    system=True; custom roles (Phase 2) are added as regular rows."""

    key = models.SlugField(_("key"), max_length=50, unique=True)
    name = models.CharField(_("name"), max_length=100)
    system = models.BooleanField(_("system role"), default=False, editable=False)
    permissions = models.ManyToManyField(
        Permission, blank=True, related_name="roles", verbose_name=_("permissions")
    )

    class Meta:
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        ordering = ["name"]

    def __str__(self):
        return str(self.name)


class UserManager(BaseUserManager):
    """Manager keyed on the email login identifier (§8). Replaces
    AbstractUser's default UserManager, whose `create_superuser(username, ...)`
    signature is incompatible with `USERNAME_FIELD = "email"` — the built-in
    `createsuperuser` command passes `email=` and crashed without this."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Internal staff/dealer user. Belongs to one company (tenant) and
    optionally one branch; Super Admin users have no company.

    Login identifier is the **email address** (§8); `username` survives only
    as an optional display/legacy label."""

    username = models.CharField(
        _("username"), max_length=150, blank=True, null=True
    )
    email = models.EmailField(_("email"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    company = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="users",
        verbose_name=_("company"),
        null=True,
        blank=True,
        help_text=_("Blank only for Super Admin users."),
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="users",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    roles = models.ManyToManyField(Role, blank=True, related_name="users", verbose_name=_("roles"))
    # Drives the session language (§11.2) — not IP/browser detection.
    preferred_language = models.CharField(
        _("preferred language"),
        max_length=8,
        default="en",
        choices=settings.LANGUAGES,
    )

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["email"]

    def has_role(self, role_key: str) -> bool:
        return self.roles.filter(key=role_key).exists()

    @property
    def is_super_admin(self) -> bool:
        return self.has_role(SUPER_ADMIN_KEY)

    @property
    def unread_notifications_count(self) -> int:
        """Count unread in-app notifications without using queryset filters in templates."""
        if not hasattr(self, "notifications"):
            return 0
        return self.notifications.filter(read_at__isnull=True).count()

    def permission_codenames(self) -> set[str]:
        """Return the effective permission set for the user.

        Users without an explicit role are treated as having standard company
        access until a role is intentionally assigned. This preserves the
        project workflow where a company user can use the ERP immediately while
        still enforcing strict section gating once role membership is set.
        """
        if self.is_superuser or self.is_super_admin or not self.roles.exists():
            return set(Permission.objects.values_list("codename", flat=True))
        return set(
            self.roles.values_list("permissions__codename", flat=True).exclude(
                permissions__codename__isnull=True
            )
        )

    def has_permission(self, codename: str) -> bool:
        """Tenant-scoped permission check used by business views (§8).

        A Super Admin user has platform-wide access even when the role is stored
        as a database row rather than a Django `is_superuser` flag. Users with no
        assigned role remain open to standard company operations until a role is
        configured.
        """
        if self.is_superuser or self.is_super_admin or not self.roles.exists():
            return True
        return self.roles.filter(permissions__codename=codename).exists()

    def _normalize_email(self):
        """Protect the unique email login field from blank or malformed values.

        Some legacy rows or admin submissions can contain `''`, `None`, or a
        malformed sentinel such as `()`. This normalizes them to a safe local
        placeholder before the database unique index is hit.
        """
        raw = self.email
        if not isinstance(raw, str):
            raw = ""
        cleaned = raw.strip()
        if not cleaned or cleaned in {"()", "[]", "NULL", "None"}:
            base = (self.username or self.first_name or self.last_name or f"user{self.pk or 'new'}").strip()
            base = base.replace(" ", "_")
            if not base:
                base = f"user{self.pk or 'new'}"
            cleaned = f"{base}@automex.local"
        self.email = cleaned

    def save(self, *args, **kwargs):
        """Keep is_staff in lockstep with Super Admin access (§8.1):
        True for Super Admin role holders and Django superusers
        (`createsuperuser` sets is_superuser without attaching roles),
        False for every other role — Django's own admin login check then
        locks everyone else by default.
        """
        self._normalize_email()
        if self.pk:
            has_super_admin = self.roles.filter(key=SUPER_ADMIN_KEY).exists() or self.is_superuser
        else:
            # New user: roles are attached after first save; default to locked out.
            has_super_admin = self.is_superuser
        self.is_staff = has_super_admin
        super().save(*args, **kwargs)


@receiver(m2m_changed, sender=User.roles.through)
def sync_super_admin_staff_flag(sender, instance, action, **kwargs):
    """Ensure admin access follows role changes even when roles are assigned via
    the M2M manager (`user.roles.add(...)` / `remove(...)`)."""
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    user = instance
    has_super_admin = user.is_superuser or user.roles.filter(key=SUPER_ADMIN_KEY).exists()
    User.objects.filter(pk=user.pk).update(is_staff=has_super_admin)
