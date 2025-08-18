from django.urls import path

from .views_invitation import (
    accept_invitation,
    cancel_invitation,
    create_invitation,
    decline_invitation,
    get_invitation_details,
    list_invitations,
    resend_invitation,
    signup_with_invitation,
)

urlpatterns = [
    # Company invitation management
    path("invitations/", list_invitations, name="list_invitations"),
    path("invitations/create/", create_invitation, name="create_invitation"),
    path("invitations/<int:invitation_id>/resend/", resend_invitation, name="resend_invitation"),
    path("invitations/<int:invitation_id>/cancel/", cancel_invitation, name="cancel_invitation"),
    # Invitation acceptance/decline (public endpoints)
    path("invitation/<str:invitation_code>/", get_invitation_details, name="get_invitation_details"),
    path("invitation/<str:invitation_code>/accept/", accept_invitation, name="accept_invitation"),
    path("invitation/<str:invitation_code>/decline/", decline_invitation, name="decline_invitation"),
    # Signup with invitation (public endpoint)
    path("auth/signup-with-invitation/", signup_with_invitation, name="signup_with_invitation"),
]
