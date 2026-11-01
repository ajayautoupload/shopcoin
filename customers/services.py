from django.core.exceptions import ValidationError
from django.db import transaction
from accounts.models import CustomerProfile
from shops.models import Shop


@transaction.atomic
def connect_customer_to_shop(profile, shop):
    customer = CustomerProfile.objects.select_for_update().get(pk=profile.pk)
    if customer.connected_shop_id:
        if customer.connected_shop_id != shop.pk:
            current_name = customer.connected_shop.name
            raise ValidationError(f'You are already connected to {current_name}. You cannot connect to another shop.')
        return customer
    if shop.status != Shop.Status.APPROVED:
        raise ValidationError('This shop is not available for customer connections yet.')
    customer.connected_shop = shop
    customer.save(update_fields=('connected_shop', 'updated_at'))
    return customer
