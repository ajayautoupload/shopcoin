from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from offers.models import ShopAd
from shops.forms import ShopAdForm
from shops.models import Shop


User = get_user_model()


class ShopPromotionBannerTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('banner-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9111111111')
        self.shop = Shop.objects.create(
            owner=self.owner, name='Full Connected Shop Name', slug='full-connected-shop',
            phone='9876543210', address='10 Main Road', city='Pune', state='Maharashtra',
            pincode='411001', status=Shop.Status.APPROVED,
        )

        self.other_owner = User.objects.create_user('other-banner-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.other_owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.other_owner, phone='9222222222')
        self.other_shop = Shop.objects.create(
            owner=self.other_owner, name='Other Store', slug='other-store', phone='9888888888',
            address='20 Other Road', city='Pune', state='Maharashtra', pincode='411002',
            status=Shop.Status.APPROVED,
        )

        self.customer_user = User.objects.create_user('banner-customer', password='StrongPass!482')
        UserProfile.objects.create(user=self.customer_user, role=UserProfile.Role.CUSTOMER)
        self.customer = CustomerProfile.objects.create(
            user=self.customer_user, phone='9777777777', connected_shop=self.shop,
        )
        self.client.force_login(self.customer_user)

    def make_ad(self, title, *, shop=None, order=0, is_active=True, start_date=None, end_date=None):
        today = timezone.localdate()
        return ShopAd.objects.create(
            shop=shop or self.shop, image='shop_ads/test-banner.png', title=title,
            description=f'{title} description', start_date=start_date or today,
            end_date=end_date or today + timedelta(days=5), display_order=order,
            is_active=is_active,
        )

    def test_active_connected_shop_banners_are_ordered_on_home_and_shop_pages(self):
        self.make_ad('Second banner', order=2)
        self.make_ad('First banner', order=1)
        self.make_ad('Inactive banner', order=0, is_active=False)
        self.make_ad('Other shop banner', shop=self.other_shop, order=0)
        today = timezone.localdate()
        self.make_ad('Expired banner', order=0, end_date=today - timedelta(days=1))

        for route in ('customers:dashboard', 'customers:shop'):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertLess(html.index('First banner'), html.index('Second banner'))
            self.assertContains(response, 'data-promo-next')
            self.assertContains(response, 'data-promo-dot="0"')
            self.assertNotContains(response, 'Inactive banner')
            self.assertNotContains(response, 'Other shop banner')
            self.assertNotContains(response, 'Expired banner')

    def test_single_banner_hides_carousel_controls(self):
        self.make_ad('One banner')
        response = self.client.get(reverse('customers:dashboard'))
        self.assertContains(response, 'One banner')
        self.assertNotContains(response, 'data-promo-next')
        self.assertNotContains(response, 'data-promo-dot=')

    def test_no_banner_shows_default_promotion_card(self):
        response = self.client.get(reverse('customers:dashboard'))
        self.assertContains(response, 'Something special is on its way')
        self.assertNotContains(response, 'data-promo-next')

    def test_customer_cannot_open_shopkeeper_banner_management(self):
        response = self.client.get(reverse('shops:ad_create'))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ShopAd.objects.exists())

    def test_banner_form_accepts_optional_copy_and_optional_cta_pair(self):
        image_data = BytesIO()
        Image.new('RGB', (16, 6), color='green').save(image_data, format='PNG')
        image_bytes = image_data.getvalue()
        form = ShopAdForm({
            'title': '', 'description': '', 'offer_text': '',
            'cta_text': 'Explore', 'cta_url': 'https://example.com/collection',
            'display_order': 3,
            'start_date': timezone.localdate().isoformat(),
            'end_date': (timezone.localdate() + timedelta(days=7)).isoformat(),
            'is_active': 'on',
        }, {'image': SimpleUploadedFile('banner.png', image_bytes, content_type='image/png')})
        self.assertTrue(form.is_valid(), form.errors)

        form = ShopAdForm({
            'title': '', 'description': '', 'offer_text': '',
            'cta_text': 'Explore', 'cta_url': '', 'display_order': 0,
            'start_date': timezone.localdate().isoformat(),
            'end_date': (timezone.localdate() + timedelta(days=7)).isoformat(),
            'is_active': 'on',
        }, {'image': SimpleUploadedFile('banner.png', image_bytes, content_type='image/png')})
        self.assertFalse(form.is_valid())
        self.assertIn('cta_url', form.errors)
