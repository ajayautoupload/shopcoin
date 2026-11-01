from pathlib import Path
import re
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from offers.models import ShopAd, ShopOffer
from shops.models import Product, Shop
from wallet.models import Wallet

User = get_user_model()


class DemoSeedCommandTests(TestCase):
    def test_seed_command_is_idempotent_and_creates_exact_demo_catalog(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as media_root, override_settings(MEDIA_ROOT=media_root, DEBUG=True):
            call_command('seed_demo_data', password='DemoOnly!ChangeMe2026', verbosity=0)
            call_command('seed_demo_data', password='DemoOnly!ChangeMe2026', verbosity=0)

        shop = Shop.objects.get(slug='abc-fashion-store', is_demo=True)
        self.assertEqual(shop.status, Shop.Status.APPROVED)
        self.assertEqual(Product.objects.filter(shop=shop, is_demo=True).count(), 10)
        self.assertEqual(ShopAd.objects.filter(shop=shop, is_demo=True).count(), 1)
        self.assertEqual(ShopOffer.objects.filter(shop=shop, is_demo=True).count(), 1)
        customers = CustomerProfile.objects.filter(connected_shop=shop, user__profile__is_demo=True)
        self.assertEqual(customers.count(), 10)
        self.assertEqual(UserProfile.objects.filter(is_demo=True, role=UserProfile.Role.SHOPKEEPER).count(), 1)
        self.assertEqual(UserProfile.objects.filter(is_demo=True, role=UserProfile.Role.CUSTOMER).count(), 10)
        self.assertTrue(shop.logo.name.startswith('shops/logos/'))
        self.assertTrue(shop.banner.name.startswith('shops/banners/'))
        self.assertTrue(Product.objects.filter(shop=shop, image__startswith='products/').exists())
        self.assertTrue(ShopAd.objects.filter(shop=shop, image__startswith='shop_ads/').exists())


class AuthorizationPageMatrixTests(TestCase):
    def setUp(self):
        self.shopkeeper = User.objects.create_user('matrix-shopkeeper', password='StrongPass!482')
        UserProfile.objects.create(user=self.shopkeeper, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.shopkeeper, phone='9111222333')
        self.shop = Shop.objects.create(
            owner=self.shopkeeper, name='Matrix Shop', slug='matrix-shop', phone='9111222333',
            address='1 Main', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED,
        )
        self.customer = User.objects.create_user('matrix-customer', password='StrongPass!482')
        UserProfile.objects.create(user=self.customer, role=UserProfile.Role.CUSTOMER)
        self.customer_profile = CustomerProfile.objects.create(user=self.customer, connected_shop=self.shop, phone='9111222334')
        Wallet.objects.create(customer=self.customer_profile)
        self.product = Product.objects.create(shop=self.shop, name='Matrix Product', slug='matrix-product', price='10.00')
        today = timezone.localdate()
        self.ad = ShopAd.objects.create(shop=self.shop, image='shop_ads/matrix.png', title='Matrix Ad', description='Test ad', start_date=today, end_date=today + timedelta(days=3))

    def test_public_pages_render_without_authentication(self):
        for path in ('/', '/login/', '/register/shopkeeper/', '/about/', '/terms/', '/privacy-policy/', '/help/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_homepage_stays_generic_for_guests_customers_and_shopkeepers(self):
        for user in (None, self.customer, self.shopkeeper):
            if user is None:
                self.client.logout()
            else:
                self.client.force_login(user)
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Shop Coin connects customers with local shops')
            self.assertContains(response, 'Earn Coins')
            self.assertContains(response, 'Save More')
            self.assertContains(response, 'Local Shopping')
            self.assertContains(response, 'Redeem')
            self.assertContains(response, 'href="/login/"')
            self.assertContains(response, 'href="/customer/login/"')
            self.assertNotContains(response, 'Matrix Shop')
            self.assertNotContains(response, 'Matrix Product')
            self.assertNotContains(response, 'matrix-customer')
            self.assertNotContains(response, 'matrix-shopkeeper')
            self.assertNotContains(response, 'bottom-nav')

    def test_both_login_pages_have_common_branding_even_with_an_active_session(self):
        self.shop.logo = 'shops/logos/matrix-shop-logo.png'
        self.shop.save(update_fields=('logo',))
        self.customer_profile.image = 'profiles/customers/matrix-customer.png'
        self.customer_profile.save(update_fields=('image',))
        for user, path in ((self.customer, '/customer/login/'), (self.shopkeeper, '/login/')):
            self.client.force_login(user)
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Shop Coin')
            self.assertContains(response, 'brand-mark')
            self.assertNotContains(response, 'Matrix Shop')
            self.assertNotContains(response, 'matrix-shop-logo.png')
            self.assertNotContains(response, 'matrix-customer.png')
            self.assertNotContains(response, 'matrix-customer')
            self.assertNotContains(response, 'matrix-shopkeeper')
            self.assertNotContains(response, 'bottom-nav')

    def test_post_login_headers_use_only_the_authenticated_users_shop(self):
        self.shop.logo = 'shops/logos/matrix-shop-logo.png'
        self.shop.save(update_fields=('logo',))
        self.client.force_login(self.customer)
        customer_page = self.client.get('/customer/shop/')
        self.assertContains(customer_page, 'Matrix Shop')
        self.assertContains(customer_page, '/media/shops/logos/matrix-shop-logo.png')
        self.assertContains(customer_page, 'width="40" height="40"')

        self.client.force_login(self.shopkeeper)
        shopkeeper_page = self.client.get('/shopkeeper/')
        self.assertContains(shopkeeper_page, 'Matrix Shop')
        self.assertContains(shopkeeper_page, '/media/shops/logos/matrix-shop-logo.png')
        self.assertContains(shopkeeper_page, 'width="40" height="40"')
        for item in ('Products', 'Customers', 'Orders', 'Coin Rules', 'Profile', 'Log out'):
            self.assertContains(shopkeeper_page, item)

        self.client.force_login(self.customer)
        customer_page = self.client.get('/customer/')
        for item in ('Home', 'Shop', 'Wallet', 'Coin Rules', 'Profile', 'Log out'):
            self.assertContains(customer_page, item)

    def test_nested_pages_use_root_relative_shared_assets(self):
        self.client.force_login(self.shopkeeper)
        response = self.client.get('/shopkeeper/products/add/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/static/css/style.css"')
        self.assertContains(response, 'href="/static/css/customer.css"')

    def test_customer_can_access_all_customer_pages_and_public_information(self):
        self.client.force_login(self.customer)
        paths = (
            '/customer/', '/customer/wallet/', '/customer/shop/',
            '/customer/coin-rules/',
            f'/customer/shop/{self.product.slug}/', '/customer/profile/',
            '/customer/profile/edit/', '/customer/notifications/', '/customer/privacy/',
            '/customer/scan/', '/account/password/', '/account/password/done/',
            '/about/', '/terms/', '/privacy-policy/', '/help/',
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in ('/customer/rewards/', '/customer/shops/'):
            with self.subTest(path=path):
                response = self.client.get(path, follow=True)
                self.assertEqual(response.status_code, 200)

    def test_approved_shopkeeper_can_access_all_shopkeeper_pages(self):
        self.client.force_login(self.shopkeeper)
        paths = (
            '/shopkeeper/', '/shopkeeper/shop/create/', '/shopkeeper/shop/matrix-shop/',
            '/shopkeeper/sales/', '/shopkeeper/customers/', '/shopkeeper/customers/add/',
            '/shopkeeper/coins/', '/shopkeeper/profile/', '/shopkeeper/notifications/',
            '/shopkeeper/coin-rules/',
            '/shopkeeper/bills/', '/shopkeeper/products/', '/shopkeeper/products/add/',
            f'/shopkeeper/products/{self.product.pk}/edit/', f'/shopkeeper/products/{self.product.pk}/delete/',
            '/shopkeeper/ads/', '/shopkeeper/ads/add/', f'/shopkeeper/ads/{self.ad.pk}/edit/',
            f'/shopkeeper/ads/{self.ad.pk}/delete/',
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_pending_shopkeeper_keeps_dashboard_and_general_pages_but_cannot_add_customers(self):
        self.shop.status = Shop.Status.PENDING
        self.shop.save(update_fields=('status', 'updated_at'))
        self.client.force_login(self.shopkeeper)
        for path in ('/shopkeeper/', '/shopkeeper/customers/', '/shopkeeper/sales/', '/shopkeeper/coins/', '/shopkeeper/bills/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.get('/shopkeeper/customers/add/')
        self.assertRedirects(response, '/shopkeeper/customers/')

    def test_wrong_roles_and_anonymous_users_remain_blocked(self):
        customer_only = ('/shopkeeper/', '/shopkeeper/customers/', '/shopkeeper/customers/add/', '/shopkeeper/sales/')
        self.client.force_login(self.customer)
        for path in customer_only:
            with self.subTest(role='customer', path=path):
                self.assertRedirects(self.client.get(path), '/customer/')
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)

        self.client.force_login(self.shopkeeper)
        for path in ('/customer/', '/customer/wallet/', '/customer/profile/', '/account/password/'):
            with self.subTest(role='shopkeeper', path=path):
                self.assertRedirects(self.client.get(path), '/shopkeeper/')
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)

        self.client.logout()
        for path in ('/customer/', '/customer/wallet/'):
            with self.subTest(role='anonymous-customer', path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/customer/login/', response.url)
        for path in ('/shopkeeper/', '/shopkeeper/customers/add/'):
            with self.subTest(role='anonymous-shopkeeper', path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response.url)

    def test_csrf_protection_remains_enabled_for_customer_creation(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.shopkeeper)
        response = csrf_client.post('/shopkeeper/customers/add/', {
            'name': 'New Customer', 'phone': '9111222335',
            'password': 'StrongPass!482', 'confirm_password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 403)


class CsrfRecoveryTests(TestCase):
    def test_fresh_shopkeeper_login_token_authenticates_and_routes_normally(self):
        keeper = User.objects.create_user('csrf-keeper', password='StrongPass!482')
        UserProfile.objects.create(user=keeper, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=keeper, phone='9111222339')
        client = self.client_class(enforce_csrf_checks=True)
        response = client.get('/login/?next=/shopkeeper/')
        token = re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', response.content).group(1).decode()

        response = client.post('/login/?next=/shopkeeper/', {
            'csrfmiddlewaretoken': token, 'username': keeper.username,
            'password': 'StrongPass!482', 'next': '/shopkeeper/',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], '/shopkeeper/')
        self.assertEqual(str(client.session['_auth_user_id']), str(keeper.pk))

    def test_stale_shopkeeper_login_token_returns_to_login_and_preserves_next(self):
        client = self.client_class(enforce_csrf_checks=True)
        response = client.get('/login/?next=/shopkeeper/')
        self.assertEqual(response.status_code, 200)
        token = re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', response.content).group(1).decode()
        client.cookies['csrftoken'] = 'stale-session-token'

        response = client.post('/login/?next=/shopkeeper/', {
            'csrfmiddlewaretoken': token, 'username': 'keeper', 'password': 'wrong',
            'next': '/shopkeeper/',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[0][0], '/login/?next=%2Fshopkeeper%2F')
        self.assertContains(response, 'Your login form expired. Please try again.')
        self.assertNotIn('_auth_user_id', client.session)

    def test_non_login_csrf_failure_shows_friendly_page_but_keeps_forbidden_status(self):
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post('/shopkeeper/customers/add/', {'name': 'Blocked request'})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Please refresh and try again', status_code=403)
        self.assertNotContains(response, 'CSRF token from POST incorrect', status_code=403)
