from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.html import format_html

from company.models import Company
from subscriptions.models import Subscription

from .forms import CustomUserChangeForm, CustomUserCreationForm
from .models import User, VerificationCode, WorksIn, PasswordResetToken
from .models_invitation import CompanyInvitation


class SubscriptionInfoListFilter(admin.SimpleListFilter):
    title = "Subscription Status"
    parameter_name = "subscription_status"

    def lookups(self, request, model_admin):
        return (
            ("active", "Active"),
            ("trialing", "Trialing"),
            ("canceled", "Canceled"),
            ("no_subscription", "No Subscription"),
        )

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(companies__subscription__status="active")
        if self.value() == "trialing":
            return queryset.filter(companies__subscription__status="trialing")
        if self.value() == "canceled":
            return queryset.filter(companies__subscription__status="canceled")
        if self.value() == "no_subscription":
            return queryset.filter(companies__subscription__isnull=True)


class RoleInline(admin.TabularInline):
    model = WorksIn
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "company":
            kwargs["queryset"] = Company.objects.prefetch_related("subscription").all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class CompanyWithSubscriptionInline(admin.TabularInline):
    model = User.companies.through
    extra = 0
    readonly_fields = (
        "company",
        "role",
        "subscription_status",
        "plan_name",
        "current_period_end",
        "manage_subscription",
    )
    fields = ("company", "role", "subscription_status", "plan_name", "current_period_end", "manage_subscription")
    verbose_name = "Company & Subscription"
    verbose_name_plural = "Companies & Subscriptions"

    def subscription_status(self, obj):
        if hasattr(obj.company, "subscription") and obj.company.subscription:
            status = obj.company.subscription.status
            status_classes = {
                "active": "success",
                "trialing": "info",
                "canceled": "danger",
                "past_due": "warning",
                "unpaid": "warning",
                "incomplete": "warning",
            }
            status_class = status_classes.get(status, "default")
            return format_html('<span class="badge badge-{}">{}</span>', status_class, status.title())
        return format_html('<span class="badge badge-secondary">None</span>')

    subscription_status.short_description = "Status"

    def plan_name(self, obj):
        if hasattr(obj.company, "subscription") and obj.company.subscription:
            return obj.company.subscription.plan.name
        return "N/A"

    plan_name.short_description = "Plan"

    def current_period_end(self, obj):
        if hasattr(obj.company, "subscription") and obj.company.subscription:
            end_date = obj.company.subscription.current_period_end
            if end_date:
                return end_date.strftime("%d %b %Y")
        return "N/A"

    current_period_end.short_description = "Renewal Date"

    def manage_subscription(self, obj):
        if hasattr(obj.company, "subscription") and obj.company.subscription:
            sub = obj.company.subscription
            sub_id = sub.id
            company_id = obj.company.id

            cancel_url = f"/admin/subscriptions/subscription/{sub_id}/change/"
            view_url = f"/admin/subscriptions/subscription/{sub_id}/change/"
            delete_url = f"/admin/subscriptions/subscription/{sub_id}/delete/"

            buttons = f"""
            <a href="{view_url}" class="button" style="margin-right: 5px;">View</a>
            """

            if sub.status in ["active", "trialing"]:
                buttons += f"""
                <a href="{cancel_url}" class="button" style="margin-right: 5px; background-color: #FFA500;">Cancel</a>
                """

            buttons += f"""
            <a href="{delete_url}" class="button" style="background-color: #FF4136;">Delete</a>
            """

            return format_html(buttons)

        # If no subscription exists, offer to create one
        company_id = obj.company.id
        create_url = f"/admin/subscriptions/subscription/add/?company={company_id}"
        return format_html(f'<a href="{create_url}" class="button">Create Subscription</a>')

    manage_subscription.short_description = "Actions"

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User
    list_display_links = ["email"]
    search_fields = ("email",)
    ordering = ("email",)
    inlines = (RoleInline, CompanyWithSubscriptionInline)
    list_display = (
        "email",
        "is_staff",
        "is_active",
        "is_superuser",
        "subscription_status",
    )
    list_filter = ("email", "is_staff", "is_active", "is_superuser", "user_type", SubscriptionInfoListFilter)
    actions = ["cancel_all_subscriptions", "reactivate_subscriptions"]

    def subscription_status(self, obj):
        companies = obj.companies.all()
        if not companies:
            return "No Company"

        active_subscriptions = companies.filter(subscription__status="active").count()
        trial_subscriptions = companies.filter(subscription__status="trialing").count()

        if active_subscriptions:
            return format_html('<span style="color: green;">Active ({})</span>', active_subscriptions)
        if trial_subscriptions:
            return format_html('<span style="color: blue;">Trial ({})</span>', trial_subscriptions)
        return format_html('<span style="color: gray;">Inactive</span>')

    subscription_status.short_description = "Subscription"

    def cancel_all_subscriptions(self, request, queryset):
        """Admin action to cancel all active subscriptions for selected users"""
        cancelled_count = 0
        for user in queryset:
            companies = user.companies.all()
            for company in companies:
                try:
                    subscription = company.subscription
                    if subscription and subscription.status in ["active", "trialing"]:
                        subscription.status = "canceled"
                        subscription.cancel_at_period_end = True
                        subscription.save()
                        cancelled_count += 1
                except Subscription.DoesNotExist:
                    continue

        if cancelled_count:
            messages.success(request, f"Successfully cancelled {cancelled_count} subscription(s).")
        else:
            messages.info(request, "No active subscriptions to cancel.")

    cancel_all_subscriptions.short_description = "Cancel all subscriptions for selected users"

    def reactivate_subscriptions(self, request, queryset):
        """Admin action to reactivate cancelled subscriptions for selected users"""
        reactivated_count = 0
        for user in queryset:
            companies = user.companies.all()
            for company in companies:
                try:
                    subscription = company.subscription
                    if subscription and subscription.status == "canceled":
                        subscription.status = "active"
                        subscription.cancel_at_period_end = False
                        subscription.save()
                        reactivated_count += 1
                except Subscription.DoesNotExist:
                    continue

        if reactivated_count:
            messages.success(request, f"Successfully reactivated {reactivated_count} subscription(s).")
        else:
            messages.info(request, "No cancelled subscriptions to reactivate.")

    reactivate_subscriptions.short_description = "Reactivate cancelled subscriptions for selected users"

    fieldsets = (
        # (None, {'fields': ('email', 'password')}),
        (
            ("Personal info"),
            {"fields": ("first_name", "last_name", "email", "user_type")},
        ),
        (
            ("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                    "user_type",
                ),
            },
        ),
    )

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super(CustomUserAdmin, self).get_inline_instances(request, obj)


@admin.register(CompanyInvitation)
class CompanyInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "invitee_name",
        "company",
        "role",
        "status",
        "created_at",
        "expires_at",
        "inviter",
        "is_expired_display",
    )
    list_filter = ("status", "role", "created_at", "expires_at", "company")
    search_fields = ("email", "invitee_name", "company__name", "inviter__email", "invitation_code")
    readonly_fields = (
        "invitation_code",
        "created_at",
        "updated_at",
        "accepted_at",
        "accepted_by",
        "is_expired_display",
        "invitation_link",
    )
    fieldsets = (
        (
            "Invitation Details",
            {"fields": ("email", "invitee_name", "company", "role", "establishments", "invitation_message")},
        ),
        ("Metadata", {"fields": ("inviter", "invitation_code", "invitation_link", "status", "expires_at")}),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at", "accepted_at", "accepted_by", "is_expired_display"),
                "classes": ("collapse",),
            },
        ),
    )
    filter_horizontal = ("establishments",)
    actions = ["mark_as_expired", "resend_invitations", "extend_expiration"]

    def is_expired_display(self, obj):
        """Display if invitation is expired with visual indicator"""
        if obj.is_expired():
            return format_html('<span style="color: red; font-weight: bold;">✗ Expired</span>')
        else:
            days_left = (obj.expires_at - timezone.now()).days
            if days_left <= 1:
                return format_html('<span style="color: orange;">⚠ Expires soon ({} days)</span>', days_left)
            return format_html('<span style="color: green;">✓ Active ({} days left)</span>', days_left)

    is_expired_display.short_description = "Expiration Status"

    def invitation_link(self, obj):
        """Display the invitation link"""
        if obj.invitation_code:
            link = obj.get_invitation_link()
            return format_html('<a href="{}" target="_blank">{}</a>', link, link)
        return "N/A"

    invitation_link.short_description = "Invitation Link"

    def mark_as_expired(self, request, queryset):
        """Admin action to mark invitations as expired"""
        updated = queryset.filter(status=CompanyInvitation.STATUS_PENDING).update(
            status=CompanyInvitation.STATUS_EXPIRED
        )
        messages.success(request, f"Marked {updated} invitation(s) as expired.")

    mark_as_expired.short_description = "Mark selected invitations as expired"

    def resend_invitations(self, request, queryset):
        """Admin action to resend invitations (for pending ones)"""
        pending_invitations = queryset.filter(status=CompanyInvitation.STATUS_PENDING)
        count = pending_invitations.count()

        if count > 0:
            # Here you would implement the actual email sending logic
            messages.success(request, f"Resent {count} invitation(s). (Email sending needs to be implemented)")
        else:
            messages.warning(request, "No pending invitations to resend.")

    resend_invitations.short_description = "Resend selected pending invitations"

    def extend_expiration(self, request, queryset):
        """Admin action to extend expiration by 7 days"""
        from datetime import timedelta

        pending_invitations = queryset.filter(status=CompanyInvitation.STATUS_PENDING)
        updated = 0

        for invitation in pending_invitations:
            invitation.expires_at = invitation.expires_at + timedelta(days=7)
            invitation.save()
            updated += 1

        if updated > 0:
            messages.success(request, f"Extended expiration for {updated} invitation(s) by 7 days.")
        else:
            messages.warning(request, "No pending invitations to extend.")

    extend_expiration.short_description = "Extend expiration by 7 days"

    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return (
            super()
            .get_queryset(request)
            .select_related("company", "inviter", "accepted_by")
            .prefetch_related("establishments")
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Optimize foreign key fields"""
        if db_field.name == "company":
            kwargs["queryset"] = Company.objects.all().order_by("name")
        elif db_field.name == "inviter":
            kwargs["queryset"] = User.objects.filter(is_active=True).order_by("email")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """
    Admin interface for managing password reset tokens
    Useful for debugging rate limiting and token management during development
    """
    list_display = (
        "user_email",
        "token_preview",
        "created_at",
        "expires_at", 
        "status_display",
        "used_at",
        "ip_address",
    )
    list_filter = (
        "created_at",
        "expires_at", 
        "used_at",
        "user__user_type",
    )
    search_fields = ("user__email", "token", "ip_address")
    readonly_fields = (
        "token", 
        "created_at", 
        "expires_at",
        "used_at",
        "ip_address", 
        "user_agent",
        "status_display",
        "time_remaining",
    )
    fieldsets = (
        (
            "Token Details",
            {"fields": ("user", "token", "status_display", "time_remaining")}
        ),
        (
            "Timestamps", 
            {"fields": ("created_at", "expires_at", "used_at")}
        ),
        (
            "Security Info",
            {
                "fields": ("ip_address", "user_agent"),
                "classes": ("collapse",),
            }
        ),
    )
    ordering = ("-created_at",)
    actions = ["mark_as_used", "delete_tokens", "clear_expired_tokens"]
    
    def user_email(self, obj):
        """Display user email with link to user admin"""
        return format_html(
            '<a href="/admin/users/user/{}/change/">{}</a>',
            obj.user.id,
            obj.user.email
        )
    user_email.short_description = "User"
    user_email.admin_order_field = "user__email"
    
    def token_preview(self, obj):
        """Show first 20 characters of token"""
        return f"{obj.token[:20]}..."
    token_preview.short_description = "Token"
    
    def status_display(self, obj):
        """Visual status indicator"""
        now = timezone.now()
        
        if obj.used_at:
            return format_html(
                '<span style="color: gray; font-weight: bold;">✓ Used</span><br>'
                '<small>{}</small>',
                obj.used_at.strftime("%m/%d %H:%M")
            )
        elif obj.expires_at < now:
            return format_html(
                '<span style="color: red; font-weight: bold;">✗ Expired</span><br>'
                '<small>{}</small>',
                obj.expires_at.strftime("%m/%d %H:%M")
            )
        else:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Valid</span><br>'
                '<small>Expires {}</small>',
                obj.expires_at.strftime("%m/%d %H:%M")
            )
    status_display.short_description = "Status"
    
    def time_remaining(self, obj):
        """Show time remaining until expiration"""
        if obj.used_at:
            return "Used"
            
        now = timezone.now()
        if obj.expires_at < now:
            delta = now - obj.expires_at
            return format_html('<span style="color: red;">Expired {} ago</span>', delta)
        else:
            delta = obj.expires_at - now
            minutes = int(delta.total_seconds() / 60)
            return format_html('<span style="color: green;">{} minutes left</span>', minutes)
    time_remaining.short_description = "Time Remaining"
    
    def mark_as_used(self, request, queryset):
        """Mark selected tokens as used (prevents rate limiting)"""
        count = queryset.filter(used_at__isnull=True).update(used_at=timezone.now())
        if count:
            messages.success(request, f"Marked {count} token(s) as used.")
        else:
            messages.info(request, "No unused tokens selected.")
    mark_as_used.short_description = "Mark selected tokens as used"
    
    def delete_tokens(self, request, queryset):
        """Delete selected tokens (clears rate limiting)"""
        count = queryset.count()
        queryset.delete()
        messages.success(request, f"Deleted {count} password reset token(s).")
    delete_tokens.short_description = "Delete selected tokens"
    
    def clear_expired_tokens(self, request, queryset):
        """Delete all expired tokens"""
        now = timezone.now()
        expired_tokens = PasswordResetToken.objects.filter(expires_at__lt=now)
        count = expired_tokens.count()
        expired_tokens.delete()
        
        if count:
            messages.success(request, f"Deleted {count} expired token(s).")
        else:
            messages.info(request, "No expired tokens to delete.")
    clear_expired_tokens.short_description = "Clear all expired tokens"
    
    def has_add_permission(self, request):
        """Prevent manual token creation"""
        return False
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related("user")


admin.site.register(User, CustomUserAdmin)
admin.site.register(VerificationCode)
admin.site.register(WorksIn)
