from .models import Shop


def get_current_shopkeeper_shop(user):
    """Return the authenticated shopkeeper's current shop, if they have one."""
    if not getattr(user, 'is_authenticated', False):
        return None
    return Shop.objects.filter(owner_id=user.pk).first()


def is_approved_shop(shop):
    return bool(shop and shop.status == Shop.Status.APPROVED)


def shop_is_owned_by(user, shop):
    return bool(shop and getattr(user, 'is_authenticated', False) and shop.owner_id == user.pk)
