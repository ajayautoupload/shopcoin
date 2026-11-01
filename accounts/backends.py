from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .models import CustomerProfile, UserProfile


class MobileOrUsernameBackend(ModelBackend):
    """Authenticate customers by mobile and shopkeepers by username."""

    def authenticate_customer_mobile(self, mobile, password):
        """Customer-only credential check used by the dedicated customer login."""
        if not mobile or password is None:
            return None
        customer = CustomerProfile.objects.select_related('user', 'user__profile').filter(
            phone=mobile, is_deleted=False, user__is_active=True,
            user__profile__role=UserProfile.Role.CUSTOMER,
            user__profile__is_deleted=False,
        ).first()
        if customer and customer.user.check_password(password) and self.user_can_authenticate(customer.user):
            customer.user.backend = 'accounts.backends.MobileOrUsernameBackend'
            return customer.user
        return None

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username or kwargs.get(User.USERNAME_FIELD)
        if not identifier or password is None:
            return None
        customer = self.authenticate_customer_mobile(identifier, password)
        if customer:
            return customer
        user = User.objects.filter(**{User.USERNAME_FIELD: identifier}).first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            profile = getattr(user, 'profile', None)
            if user.is_superuser or (profile and profile.role == UserProfile.Role.SHOPKEEPER and not profile.is_deleted):
                return user
        return None
