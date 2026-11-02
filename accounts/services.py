from uuid import uuid4
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import CustomerProfile, UserProfile
from shops.access import is_approved_shop, shop_is_owned_by

User = get_user_model()


@transaction.atomic
def create_customer_for_shopkeeper(shopkeeper, shop, data):
    if not shop_is_owned_by(shopkeeper, shop) or not is_approved_shop(shop):
        raise PermissionDenied('Only the owner of an approved shop can create its customers.')

    first_name, _, last_name = data['name'].partition(' ')
    user = User.objects.create_user(
        username=f'customer_{uuid4().hex}',
        first_name=first_name,
        last_name=last_name,
        email=data.get('email') or '',
        password=data['password'],
    )
    UserProfile.objects.create(user=user, role=UserProfile.Role.CUSTOMER)
    customer = CustomerProfile.objects.create(
        user=user,
        connected_shop=shop,
        phone=data['phone'],
        address=data.get('address') or '',
        image=data.get('image'),
    )
    from wallet.models import Wallet
    Wallet.objects.create(customer=customer)
    return customer


@transaction.atomic
def deactivate_customer_account(user):
    user = User.objects.select_for_update().get(pk=user.pk)
    customer = CustomerProfile.objects.select_for_update().get(user=user)
    if customer.is_deleted:
        return customer
    from wallet.models import CoinLedger, Wallet
    from wallet.services import get_coin_source_summary
    wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=customer)
    before = wallet.balance
    balance = before
    for source, data in get_coin_source_summary(wallet).items():
        coins = data['coins']
        if not coins:
            continue
        unit_value = (data['value'] / coins).quantize(Decimal('0.01'))
        next_balance = max(0, balance - coins)
        CoinLedger.objects.create(
            wallet=wallet, shop=customer.connected_shop,
            entry_type=CoinLedger.EntryType.ACCOUNT_DELETION,
            coin_source=source, coin_value_per_coin=unit_value,
            coin_delta=-coins, balance_before=balance, balance_after=next_balance,
            description='Balance reset when customer account was deleted.',
        )
        balance = next_balance
    wallet.balance = 0
    wallet.save(update_fields=('balance', 'updated_at'))
    customer.is_deleted = True
    customer.save(update_fields=('is_deleted', 'updated_at'))
    profile = user.profile
    profile.is_deleted = True
    profile.deleted_at = timezone.now()
    profile.deleted_by = user
    profile.save(update_fields=('is_deleted', 'deleted_at', 'deleted_by', 'updated_at'))
    user.is_active = False
    user.save(update_fields=('is_active',))
    return customer
