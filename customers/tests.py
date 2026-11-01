from io import BytesIO
from datetime import date, timedelta
from tempfile import gettempdir
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from accounts.models import CustomerProfile, UserProfile
from wallet.models import CoinLedger, CoinRule, CoinValue, Wallet
from offers.models import ShopAd, ShopOffer
from shops.models import Product, Shop
from .services import connect_customer_to_shop

User = get_user_model()


class CustomerShopExperienceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('buyer', password='StrongPass!482', email='buyer@example.com', first_name='Rahul')
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.CUSTOMER)
        self.profile = CustomerProfile.objects.create(user=self.user, phone='9876543210')
        self.shop = self.make_shop('ABC Fashion', 'abc-fashion')
        self.other_shop = self.make_shop('XYZ Fashion', 'xyz-fashion')
        self.product = Product.objects.create(shop=self.shop, name='Linen Shirt', slug='linen-shirt', price='999.00', discount_price='799.00', category='Shirts', sizes='S, M, L', colors='Blue', stock=4, is_new=True)
        self.other_product = Product.objects.create(shop=self.other_shop, name='Other Shirt', slug='other-shirt', price='1000.00')
        self.client.force_login(self.user)

    def make_shop(self, name, slug):
        owner = User.objects.create_user(f'owner-{slug}', password='StrongPass!482')
        UserProfile.objects.create(user=owner, role=UserProfile.Role.SHOPKEEPER)
        from accounts.models import ShopkeeperProfile
        ShopkeeperProfile.objects.create(user=owner, phone='9111111111')
        return Shop.objects.create(
            owner=owner, name=name, slug=slug, phone='9876543210', address='10 Main Road',
            city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED,
        )

    def test_customer_can_only_be_connected_to_one_shop(self):
        connect_customer_to_shop(self.profile, self.shop)
        with self.assertRaisesMessage(ValidationError, 'You are already connected to ABC Fashion'):
            connect_customer_to_shop(self.profile, self.other_shop)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.connected_shop, self.shop)

    def test_shopkeeper_connection_request_cannot_move_customer_to_second_shop(self):
        connect_customer_to_shop(self.profile, self.shop)
        self.client.force_login(self.other_shop.owner)
        response = self.client.post(reverse('shops:customer_create'), {
            'name': 'Copy Customer', 'phone': self.profile.phone, 'password': 'StrongPass!482',
            'confirm_password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This mobile number is already registered with another shop.')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.connected_shop, self.shop)

    def test_customer_home_shows_connected_shop_and_only_its_products_and_offers(self):
        connect_customer_to_shop(self.profile, self.shop)
        own_offer = ShopOffer.objects.create(shop=self.shop, title='Winter collection', badge='20% OFF')
        ShopOffer.objects.create(shop=self.other_shop, title='Other shop offer', badge='50% OFF')
        today = timezone.localdate()
        ShopAd.objects.create(shop=self.shop, image='', title='Connected shop ad', description='Sample ad', offer_text='20% OFF', start_date=today, end_date=today + timedelta(days=5), is_active=True)
        ShopAd.objects.create(shop=self.other_shop, image='', title='Other shop ad', description='Not for this customer', start_date=today, end_date=today + timedelta(days=5), is_active=True)
        response = self.client.get(reverse('customers:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ABC Fashion')
        self.assertContains(response, self.product.name)
        self.assertContains(response, own_offer.title)
        self.assertContains(response, 'Connected shop ad')
        self.assertNotContains(response, self.other_product.name)
        self.assertNotContains(response, 'Other shop offer')
        self.assertNotContains(response, 'Other shop ad')
        self.assertNotContains(response, 'Nearby Shops')

    def test_expired_and_inactive_shop_ads_are_not_shown(self):
        connect_customer_to_shop(self.profile, self.shop)
        today = timezone.localdate()
        ShopAd.objects.create(shop=self.shop, image='', title='Expired sale', description='Expired', start_date=today - timedelta(days=6), end_date=today - timedelta(days=1), is_active=True)
        ShopAd.objects.create(shop=self.shop, image='', title='Inactive sale', description='Inactive', start_date=today, end_date=today + timedelta(days=5), is_active=False)
        ShopAd.objects.create(shop=self.shop, image='', title='Current sale', description='Current', start_date=today, end_date=today + timedelta(days=5), is_active=True)
        response = self.client.get(reverse('customers:dashboard'))
        self.assertContains(response, 'Current sale')
        self.assertNotContains(response, 'Expired sale')
        self.assertNotContains(response, 'Inactive sale')

    def test_customer_shop_page_lists_only_connected_shop_products(self):
        connect_customer_to_shop(self.profile, self.shop)
        response = self.client.get(reverse('customers:shop'))
        self.assertContains(response, self.product.name)
        self.assertNotContains(response, self.other_product.name)
        self.assertContains(response, 'ABC Fashion')

    def test_customer_coin_rules_only_show_connected_shop_rules(self):
        connect_customer_to_shop(self.profile, self.shop)
        CoinRule.objects.create(shop=self.shop, purchase_amount='500.00', coins_awarded=5)
        CoinRule.objects.create(shop=self.other_shop, purchase_amount='100.00', coins_awarded=99)
        response = self.client.get(reverse('customers:coin_rules'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '0–99 coins')
        self.assertContains(response, '₹10.00 per coin')
        self.assertNotContains(response, '₹100.00')
        self.assertNotContains(response, 'Earn 99 coins')

    def test_direct_product_url_cannot_access_another_shops_product(self):
        connect_customer_to_shop(self.profile, self.shop)
        response = self.client.get(reverse('customers:product_detail', args=[self.other_product.slug]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse('customers:product_detail', args=[self.product.slug])).status_code, 200)

    def test_product_detail_shows_product_information(self):
        connect_customer_to_shop(self.profile, self.shop)
        response = self.client.get(reverse('customers:product_detail', args=[self.product.slug]))
        self.assertContains(response, '₹799.00')
        self.assertContains(response, 'S, M, L')
        self.assertContains(response, 'Blue')
        self.assertContains(response, 'In stock')

    def test_dashboard_wallet_and_shop_pages_load(self):
        connect_customer_to_shop(self.profile, self.shop)
        for name in ('customers:dashboard', 'customers:wallet', 'customers:shop'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_bottom_navigation_marks_current_customer_page_active(self):
        response = self.client.get(reverse('customers:wallet'))
        self.assertContains(response, 'Wallet</span></a>')
        self.assertContains(response, 'class="active" href="/customer/wallet/"')
        self.assertContains(response, '>Shop</span>')
        self.assertNotContains(response, '>Rewards</span>')
        self.assertContains(response, 'Coin Rules</span>')

    def test_customer_can_update_notification_preferences(self):
        response = self.client.post(reverse('customers:notifications'), {})
        self.assertRedirects(response, reverse('customers:notifications'))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.notifications_enabled)
        self.assertContains(self.client.get(reverse('customers:privacy')), 'Show my name to my connected shop')

    @override_settings(MEDIA_ROOT=gettempdir())
    def test_customer_can_upload_profile_photo(self):
        from PIL import Image
        connect_customer_to_shop(self.profile, self.shop)
        image_data = BytesIO()
        Image.new('RGB', (2, 2), color='green').save(image_data, format='PNG')
        upload = SimpleUploadedFile('profile.png', image_data.getvalue(), content_type='image/png')
        response = self.client.post(reverse('customers:edit_profile'), {
            'first_name': 'Rahul', 'last_name': 'Kumar', 'email': 'buyer@example.com',
            'phone': '9876543210', 'address': '10 Main Road', 'city': 'Pune', 'state': 'Maharashtra',
            'pincode': '411001', 'notifications_enabled': 'on', 'image': upload,
        })
        self.assertRedirects(response, reverse('customers:profile'))
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.image.name.endswith('.png'))
        self.assertContains(self.client.get(reverse('customers:profile')), 'ABC Fashion')


class CustomerDeletionAndWalletTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('wallet-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        from accounts.models import ShopkeeperProfile
        ShopkeeperProfile.objects.create(user=self.owner, phone='9112345678')
        self.shop = Shop.objects.create(owner=self.owner, name='Wallet Shop', slug='wallet-shop', phone='9112345678', address='1 Main', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.user = User.objects.create_user('wallet-customer', password='StrongPass!482', first_name='Mira')
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.CUSTOMER)
        self.profile = CustomerProfile.objects.create(user=self.user, connected_shop=self.shop, phone='9000000001')
        self.wallet = Wallet.objects.create(customer=self.profile, balance=120)
        self.client.force_login(self.user)

    def test_wallet_uses_current_coin_balance_slab_instead_of_single_shop_coin_value(self):
        CoinValue.objects.create(shop=self.shop, value_per_coin='10.00')
        response = self.client.get(reverse('customers:wallet'))
        self.assertContains(response, 'Total Active Coins')
        self.assertContains(response, 'Your current coin balance determines the per-coin slab.')
        self.assertContains(response, '₹12.00 / coin')
        self.assertContains(response, '100–499 coins')
        self.assertContains(response, '₹1440.00')

    def test_customer_deletion_deactivates_resets_balance_and_preserves_ledger(self):
        self.assertEqual(self.client.get(reverse('customers:delete_account')).status_code, 200)
        response = self.client.post(reverse('customers:delete_account'), {'confirm_delete': 'yes'})
        self.assertRedirects(response, reverse('core:home'))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.profile.is_deleted)
        self.assertEqual(self.wallet.balance, 0)
        entry = CoinLedger.objects.get(wallet=self.wallet)
        self.assertEqual(entry.entry_type, CoinLedger.EntryType.ACCOUNT_DELETION)
        self.assertEqual(entry.coin_delta, -120)
        self.assertEqual(entry.balance_after, 0)
        self.assertTrue(UserProfile.objects.get(user=self.user).deleted_at)
        self.assertEqual(self.client.post(reverse('accounts:login'), {'username': '9000000001', 'password': 'StrongPass!482'}).status_code, 200)

    def test_phone_is_available_after_soft_deletion_and_new_wallet_is_separate(self):
        from accounts.services import deactivate_customer_account
        deactivate_customer_account(self.user)
        other_owner = User.objects.create_user('other-wallet-owner', password='StrongPass!482')
        UserProfile.objects.create(user=other_owner, role=UserProfile.Role.SHOPKEEPER)
        from accounts.models import ShopkeeperProfile
        ShopkeeperProfile.objects.create(user=other_owner, phone='9112345677')
        other_shop = Shop.objects.create(owner=other_owner, name='Other Wallet Shop', slug='other-wallet-shop', phone='9112345677', address='2 Main', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.client.force_login(other_owner)
        response = self.client.post(reverse('shops:customer_create'), {'name': 'New Mira', 'phone': '9000000001', 'email': '', 'password': 'StrongPass!482', 'confirm_password': 'StrongPass!482'})
        self.assertRedirects(response, reverse('shops:customers'))
        new_profile = CustomerProfile.objects.get(phone='9000000001', is_deleted=False)
        self.assertNotEqual(new_profile.pk, self.profile.pk)
        self.assertEqual(new_profile.connected_shop, other_shop)
        self.assertEqual(new_profile.wallet.balance, 0)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)
