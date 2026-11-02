from django.contrib.auth import get_user_model
from datetime import date, timedelta
from io import BytesIO
from tempfile import gettempdir
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from offers.models import ShopAd
from wallet.models import CoinLedger, CoinRule, CoinValue, Wallet
from .models import Product, Shop

User = get_user_model()


class ShopFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='StrongPass!482', email='owner@example.com')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9876543210')
        self.customer = User.objects.create_user('customer', password='StrongPass!482', email='customer@example.com')
        UserProfile.objects.create(user=self.customer, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=self.customer)
        self.shop_data = {
            'name': 'Mango Market', 'description': 'A neighbourhood shop', 'phone': '9876543210',
            'email': 'shop@example.com', 'address': '12 Main Road', 'city': 'Pune', 'state': 'Maharashtra', 'pincode': '411001',
        }

    def test_shop_creation_defaults_to_pending(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('shops:shop_create'), self.shop_data)
        self.assertRedirects(response, reverse('shops:dashboard'))
        shop = Shop.objects.get(name='Mango Market')
        self.assertEqual(shop.status, Shop.Status.PENDING)
        self.assertEqual(shop.owner, self.owner)
        self.assertEqual(shop.slug, 'mango-market')

    def test_shopkeeper_cannot_set_approval_status_in_post(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('shops:shop_create'), {**self.shop_data, 'status': Shop.Status.APPROVED, 'owner': self.customer.pk})
        shop = Shop.objects.get(name='Mango Market')
        self.assertEqual(shop.status, Shop.Status.PENDING)
        self.assertEqual(shop.owner, self.owner)

    def test_admin_can_approve_and_reject(self):
        shop = Shop.objects.create(owner=self.owner, **self.shop_data)
        admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'StrongPass!482')
        self.client.force_login(admin_user)
        response = self.client.post(reverse('admin:shops_shop_changelist'), {'action': 'approve_shops', '_selected_action': [shop.pk]})
        self.assertEqual(response.status_code, 302)
        shop.refresh_from_db()
        self.assertEqual(shop.status, Shop.Status.APPROVED)
        response = self.client.post(reverse('admin:shops_shop_changelist'), {'action': 'reject_shops', '_selected_action': [shop.pk]})
        self.assertEqual(response.status_code, 302)
        shop.refresh_from_db()
        self.assertEqual(shop.status, Shop.Status.REJECTED)

    def test_admin_can_delete_shop_and_shopkeeper_with_dependent_data(self):
        shop = Shop.objects.create(owner=self.owner, **self.shop_data)
        customer_profile = self.customer.customer_profile
        customer_profile.connected_shop = shop
        customer_profile.save(update_fields=('connected_shop',))
        Wallet.objects.create(customer=customer_profile)
        product = Product.objects.create(shop=shop, name='Delete with shop', price='20.00')
        CoinValue.objects.create(shop=shop, value_per_coin='1.00')
        admin_user = User.objects.create_superuser('admin-delete-shop', 'admin-delete@example.com', 'StrongPass!482')
        self.client.force_login(admin_user)
        response = self.client.post(reverse('admin:shops_shop_delete', args=[shop.pk]), {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Shop.objects.filter(pk=shop.pk).exists())
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
        customer_profile.refresh_from_db()
        self.assertIsNone(customer_profile.connected_shop)
        self.assertFalse(CoinValue.objects.filter(shop=shop).exists())

        response = self.client.post(reverse('admin:auth_user_delete', args=[self.owner.pk]), {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())

    def test_admin_can_delete_customer_with_wallet_and_ledger(self):
        admin_user = User.objects.create_superuser('admin-delete-customer', 'admin-customer@example.com', 'StrongPass!482')
        wallet = Wallet.objects.create(customer=self.customer.customer_profile, balance=12)
        CoinLedger.objects.create(wallet=wallet, entry_type=CoinLedger.EntryType.EARN, coin_delta=12, balance_before=0, balance_after=12)
        self.client.force_login(admin_user)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.has_perm('accounts.delete_customerprofile'))
        response = self.client.post(reverse('admin:accounts_customerprofile_delete', args=[self.customer.customer_profile.pk]), {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CustomerProfile.objects.filter(user=self.customer).exists())
        self.assertFalse(Wallet.objects.filter(pk=wallet.pk).exists())
        self.assertFalse(CoinLedger.objects.filter(wallet=wallet).exists())

    def test_non_admin_cannot_use_admin_approval_action(self):
        shop = Shop.objects.create(owner=self.owner, **self.shop_data)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('admin:shops_shop_changelist'), {'action': 'approve_shops', '_selected_action': [shop.pk]})
        self.assertIn(response.status_code, (302, 403))
        shop.refresh_from_db()
        self.assertEqual(shop.status, Shop.Status.PENDING)

    def test_only_owner_can_view_shop_detail(self):
        shop = Shop.objects.create(owner=self.owner, **self.shop_data)
        self.client.force_login(self.customer)
        self.assertRedirects(self.client.get(reverse('shops:shop_detail', args=[shop.slug])), reverse('customers:dashboard'))

    def test_other_shopkeeper_cannot_edit_shop(self):
        shop = Shop.objects.create(owner=self.owner, **self.shop_data)
        other = User.objects.create_user('other', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        self.client.force_login(other)
        response = self.client.get(reverse('shops:shop_detail', args=[shop.slug]))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse('shops:shop_create'))
        self.assertEqual(response.status_code, 200)


class AccessAndPageTests(TestCase):
    def make_user(self, name, role):
        user = User.objects.create_user(name, password='StrongPass!482')
        UserProfile.objects.create(user=user, role=role)
        if role == UserProfile.Role.CUSTOMER:
            CustomerProfile.objects.create(user=user)
        else:
            from accounts.models import ShopkeeperProfile
            ShopkeeperProfile.objects.create(user=user, phone='9876543210')
        return user

    def test_role_dashboard_access(self):
        customer = self.make_user('cust', UserProfile.Role.CUSTOMER)
        shopkeeper = self.make_user('keeper', UserProfile.Role.SHOPKEEPER)
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse('customers:dashboard')).status_code, 200)
        denied = self.client.get(reverse('shops:dashboard'))
        self.assertRedirects(denied, reverse('customers:dashboard'))
        self.client.force_login(shopkeeper)
        self.assertEqual(self.client.get(reverse('shops:dashboard')).status_code, 200)
        denied = self.client.get(reverse('customers:dashboard'))
        self.assertRedirects(denied, reverse('shops:dashboard'))

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse('customers:dashboard'))
        self.assertRedirects(response, f"{reverse('customers:login')}?next={reverse('customers:dashboard')}")

    def test_landing_login_and_dashboard_pages_load(self):
        self.assertEqual(self.client.get(reverse('core:home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:login')).status_code, 200)
        customer = self.make_user('cust2', UserProfile.Role.CUSTOMER)
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse('customers:dashboard')).status_code, 200)
        shopkeeper = self.make_user('keeper2', UserProfile.Role.SHOPKEEPER)
        self.client.force_login(shopkeeper)
        self.assertEqual(self.client.get(reverse('shops:dashboard')).status_code, 200)


class ShopCustomerManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('connecting-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9123456789')
        self.shop = Shop.objects.create(owner=self.owner, name='Approved Shop', phone='9123456789', address='10 Main', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        other = User.objects.create_user('other-owner', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=other, phone='9123456788')
        self.other_shop = Shop.objects.create(owner=other, name='Other Approved Shop', phone='9123456788', address='20 Main', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.client.force_login(self.owner)

    def customer_data(self, **extra):
        return {'name': 'Neha Sharma', 'phone': '9876501234', 'email': 'neha@example.com', 'password': 'StrongPass!482', 'confirm_password': 'StrongPass!482', 'address': '10 Main', **extra}

    def test_shopkeeper_creates_hashed_customer_connected_to_own_shop(self):
        response = self.client.post(reverse('shops:customer_create'), self.customer_data())
        self.assertRedirects(response, reverse('shops:customers'))
        profile = CustomerProfile.objects.get(phone='9876501234')
        self.assertEqual(profile.connected_shop, self.shop)
        self.assertTrue(profile.user.check_password('StrongPass!482'))
        self.assertNotEqual(profile.user.password, 'StrongPass!482')
        self.assertEqual(profile.user.profile.role, UserProfile.Role.CUSTOMER)
        self.assertEqual(profile.wallet.balance, 0)

    def test_customer_created_by_shopkeeper_can_login_from_customer_login_button_flow(self):
        self.client.post(reverse('shops:customer_create'), self.customer_data())
        self.client.logout()
        home = self.client.get(reverse('core:home'))
        self.assertContains(home, f'href="{reverse("customers:login")}"')
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '9876501234', 'password': 'StrongPass!482',
        })
        self.assertRedirects(response, reverse('customers:shop'))
        shop_page = self.client.get(reverse('customers:shop'))
        self.assertEqual(shop_page.status_code, 200)
        self.assertContains(shop_page, 'Approved Shop')

    def test_duplicate_customer_mobile_is_rejected_for_same_and_other_shop(self):
        self.client.post(reverse('shops:customer_create'), self.customer_data())
        response = self.client.post(reverse('shops:customer_create'), self.customer_data(name='Another Name', email='another@example.com'))
        self.assertContains(response, 'This customer is already registered with your shop.')
        self.client.force_login(self.other_shop.owner)
        response = self.client.post(reverse('shops:customer_create'), self.customer_data(name='Third Name', email='third@example.com'))
        self.assertContains(response, 'This mobile number is already registered with another shop.')
        self.assertEqual(CustomerProfile.objects.filter(phone='9876501234', is_deleted=False).count(), 1)

    def test_customer_list_shows_own_active_and_deleted_without_password(self):
        self.client.post(reverse('shops:customer_create'), self.customer_data())
        profile = CustomerProfile.objects.get(phone='9876501234')
        self.assertContains(self.client.get(reverse('shops:customers')), 'Neha Sharma')
        profile.is_deleted = True
        profile.save(update_fields=('is_deleted',))
        response = self.client.get(reverse('shops:customers'))
        self.assertContains(response, 'Deleted')
        self.assertNotContains(response, profile.user.password)

    def test_pending_shop_cannot_add_customers(self):
        self.shop.status = Shop.Status.PENDING
        self.shop.save(update_fields=('status', 'updated_at'))
        response = self.client.post(reverse('shops:customer_create'), self.customer_data())
        self.assertRedirects(response, reverse('shops:customers'))
        self.assertFalse(CustomerProfile.objects.exists())

    def test_shopkeeper_cannot_view_other_shop_customers(self):
        self.client.post(reverse('shops:customer_create'), self.customer_data())
        other_customer = User.objects.create_user('private-other-customer', password='StrongPass!482', first_name='Private')
        UserProfile.objects.create(user=other_customer, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=other_customer, connected_shop=self.other_shop, phone='9876501235')
        self.client.get(reverse('shops:customers'))
        self.client.force_login(self.other_shop.owner)
        response = self.client.get(reverse('shops:customers'))
        self.assertContains(response, 'Private')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shops:customers'))
        self.assertNotContains(response, 'Private')

    def test_shopkeeper_coin_rules_are_scoped_to_own_shop(self):
        CoinRule.objects.create(shop=self.shop, purchase_amount='300.00', coins_awarded=3)
        CoinRule.objects.create(shop=self.other_shop, purchase_amount='100.00', coins_awarded=50)
        response = self.client.get(reverse('shops:coin_rules'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '₹1,000–₹4,999')
        self.assertContains(response, '₹10.00 per coin')
        self.assertNotContains(response, 'Earn 50 coins')
        self.assertContains(self.client.get(reverse('shops:dashboard')), 'Coin Rules')

class ShopkeeperCatalogueManagementTests(TestCase):
    def setUp(self):
        self.owner = self.make_shopkeeper('catalog-owner', 'catalog@example.test', '1111111111', 'Catalog Shop')
        self.other_owner = self.make_shopkeeper('other-owner', 'other@example.test', '1111111112', 'Other Shop')
        self.shop = self.make_shop(self.owner, 'Catalog Shop', 'catalog-shop')
        self.other_shop = self.make_shop(self.other_owner, 'Other Shop', 'other-shop')
        self.client.force_login(self.owner)

    def make_shopkeeper(self, username, email, phone, business):
        user = User.objects.create_user(username, email=email, password='StrongPass!482')
        UserProfile.objects.create(user=user, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=user, phone=phone, business_name=business)
        return user

    def make_shop(self, owner, name, slug):
        return Shop.objects.create(owner=owner, name=name, slug=slug, phone='1111111111', address='10 Demo Street', city='Samplepur', state='Demostate', pincode='000000', status=Shop.Status.APPROVED)

    def product_data(self, **extra):
        return {'name': 'Cotton Shirt', 'price': '999.00', 'discount_price': '799.00', 'category': 'Shirts', 'sizes': 'M, L, XL', 'colors': 'Blue', 'description': 'Soft cotton shirt.', 'stock': '25', 'is_new': 'on', 'is_active': 'on', **extra}

    def test_shopkeeper_creates_product_for_own_shop_even_if_shop_field_is_spoofed(self):
        response = self.client.post(reverse('shops:product_create'), self.product_data(shop=self.other_shop.pk))
        self.assertRedirects(response, reverse('shops:products'))
        product = Product.objects.get(name='Cotton Shirt')
        self.assertEqual(product.shop, self.shop)
        self.assertEqual(product.stock, 25)
        self.assertTrue(product.is_active)
        self.assertTrue(product.is_new)

    def test_shopkeeper_edits_own_product(self):
        product = Product.objects.create(shop=self.shop, name='Old Shirt', price='700.00')
        response = self.client.post(reverse('shops:product_edit', args=[product.pk]), self.product_data(name='New Shirt', shop=self.other_shop.pk))
        self.assertRedirects(response, reverse('shops:products'))
        product.refresh_from_db()
        self.assertEqual(product.name, 'New Shirt')
        self.assertEqual(product.shop, self.shop)

    def test_shopkeeper_cannot_view_or_edit_another_shops_product(self):
        product = Product.objects.create(shop=self.other_shop, name='Private Shirt', price='500.00')
        self.assertEqual(self.client.get(reverse('shops:product_edit', args=[product.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('shops:product_edit', args=[product.pk]), self.product_data()).status_code, 404)
        self.assertEqual(self.client.get(reverse('shops:product_delete', args=[product.pk])).status_code, 404)

    def test_shopkeeper_deletes_own_product_after_confirmation(self):
        product = Product.objects.create(shop=self.shop, name='Delete Me', price='500.00')
        self.assertEqual(self.client.get(reverse('shops:product_delete', args=[product.pk])).status_code, 200)
        response = self.client.post(reverse('shops:product_delete', args=[product.pk]))
        self.assertRedirects(response, reverse('shops:products'))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def make_ad_image(self):
        from PIL import Image
        image_data = BytesIO()
        Image.new('RGB', (4, 3), color='green').save(image_data, format='PNG')
        return SimpleUploadedFile('shop-ad.png', image_data.getvalue(), content_type='image/png')

    def ad_data(self, **extra):
        return {'title': 'Winter Sale', 'description': 'New collection is here.', 'offer_text': 'Up to 30% OFF', 'start_date': date.today().isoformat(), 'end_date': (date.today() + timedelta(days=14)).isoformat(), 'is_active': 'on', **extra}

    @override_settings(MEDIA_ROOT=gettempdir())
    def test_shopkeeper_creates_and_edits_own_ad_with_image(self):
        response = self.client.post(reverse('shops:ad_create'), {**self.ad_data(shop=self.other_shop.pk), 'image': self.make_ad_image()})
        self.assertRedirects(response, reverse('shops:ads'))
        ad = ShopAd.objects.get(title='Winter Sale')
        self.assertEqual(ad.shop, self.shop)
        self.assertTrue(ad.image.name.startswith('shop_ads/'))
        response = self.client.post(reverse('shops:ad_edit', args=[ad.pk]), {**self.ad_data(title='Winter Edit'), 'image': self.make_ad_image()})
        self.assertRedirects(response, reverse('shops:ads'))
        ad.refresh_from_db()
        self.assertEqual(ad.title, 'Winter Edit')

    def test_shopkeeper_cannot_manage_another_shops_ad(self):
        ad = ShopAd.objects.create(shop=self.other_shop, image='shop_ads/demo-ad.png', title='Other Ad', description='Private', start_date=date.today(), end_date=date.today() + timedelta(days=1))
        self.assertEqual(self.client.get(reverse('shops:ad_edit', args=[ad.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('shops:ad_edit', args=[ad.pk]), self.ad_data()).status_code, 404)
        self.assertEqual(self.client.get(reverse('shops:ad_delete', args=[ad.pk])).status_code, 404)

    def test_shopkeeper_can_toggle_and_delete_own_ad(self):
        ad = ShopAd.objects.create(shop=self.shop, image='shop_ads/demo-ad.png', title='Toggle Ad', description='Toggle', start_date=date.today(), end_date=date.today() + timedelta(days=1))
        response = self.client.post(reverse('shops:ad_toggle', args=[ad.pk]))
        self.assertRedirects(response, reverse('shops:ads'))
        ad.refresh_from_db()
        self.assertFalse(ad.is_active)
        response = self.client.post(reverse('shops:ad_delete', args=[ad.pk]))
        self.assertRedirects(response, reverse('shops:ads'))
        self.assertFalse(ShopAd.objects.filter(pk=ad.pk).exists())

    @override_settings(MEDIA_ROOT=gettempdir())
    def test_shopkeeper_product_image_upload_uses_products_media_path(self):
        from PIL import Image
        image_data = BytesIO()
        Image.new('RGB', (4, 3), color='blue').save(image_data, format='PNG')
        image_file = SimpleUploadedFile('shirt.png', image_data.getvalue(), content_type='image/png')
        response = self.client.post(reverse('shops:product_create'), {**self.product_data(), 'image': image_file})
        self.assertRedirects(response, reverse('shops:products'))
        product = Product.objects.get(name='Cotton Shirt')
        self.assertTrue(product.image.name.startswith('products/'))

    def test_my_products_and_ads_are_scoped_to_shop_owner(self):
        Product.objects.create(shop=self.shop, name='Mine', price='100.00')
        Product.objects.create(shop=self.other_shop, name='Theirs', price='100.00')
        ShopAd.objects.create(shop=self.shop, image='shop_ads/demo-ad.png', title='Mine Ad', description='Own', start_date=date.today(), end_date=date.today())
        ShopAd.objects.create(shop=self.other_shop, image='shop_ads/demo-ad.png', title='Theirs Ad', description='Other', start_date=date.today(), end_date=date.today())
        self.assertContains(self.client.get(reverse('shops:products')), 'Mine')
        self.assertNotContains(self.client.get(reverse('shops:products')), 'Theirs')
        self.assertContains(self.client.get(reverse('shops:ads')), 'Mine Ad')
        self.assertNotContains(self.client.get(reverse('shops:ads')), 'Theirs Ad')

