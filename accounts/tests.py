from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CustomerProfile, ShopkeeperProfile, UserProfile

User = get_user_model()


class AccountFlowTests(TestCase):
    def test_customer_self_registration_route_is_removed(self):
        response = self.client.get('/register/customer/')
        self.assertEqual(response.status_code, 404)

    def test_shopkeeper_registration_creates_role_and_profile(self):
        response = self.client.post(reverse('accounts:register_shopkeeper'), {
            'username': 'shopowner', 'first_name': 'Ravi', 'email': 'ravi@example.com',
            'phone': '9876543210', 'business_name': 'Ravi Stores',
            'password1': 'StrongPass!482', 'password2': 'StrongPass!482',
        })
        self.assertRedirects(response, reverse('shops:dashboard'))
        user = User.objects.get(username='shopowner')
        self.assertEqual(user.profile.role, UserProfile.Role.SHOPKEEPER)
        self.assertEqual(user.shopkeeper_profile.phone, '9876543210')

    def test_customer_can_login_by_mobile_and_shopkeeper_by_username(self):
        customer = User.objects.create_user('internal-customer', password='StrongPass!482')
        UserProfile.objects.create(user=customer, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=customer, phone='9876543210')
        response = self.client.post(reverse('accounts:login'), {'username': '9876543210', 'password': 'StrongPass!482'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(self.client.get(response.url), reverse('customers:dashboard'))
        self.client.logout()

        owner = User.objects.create_user('shopowner2', password='StrongPass!482')
        UserProfile.objects.create(user=owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=owner, phone='9123456789')
        response = self.client.post(reverse('accounts:login'), {'username': 'shopowner2', 'password': 'StrongPass!482'})
        self.assertEqual(response.status_code, 302)
        routed = self.client.get(response.url)
        self.assertRedirects(routed, reverse('shops:dashboard'))

    def test_invalid_login_does_not_authenticate(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'nobody', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_home_and_login_do_not_offer_customer_registration(self):
        self.assertNotContains(self.client.get(reverse('core:home')), 'register/customer')
        self.assertNotContains(self.client.get(reverse('accounts:login')), 'Create an account')

    def test_shopkeeper_login_form_remains_available_for_another_signed_in_role(self):
        customer = User.objects.create_user('signed-in-customer', password='StrongPass!482')
        UserProfile.objects.create(user=customer, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=customer, phone='9876500001')
        self.client.force_login(customer)
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Shopkeepers use their username')

    def test_sessions_using_the_original_django_backend_remain_valid(self):
        user = User.objects.create_user('legacy-session-shopkeeper', password='StrongPass!482')
        UserProfile.objects.create(user=user, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=user, phone='9222333444')
        self.client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(self.client.get(reverse('shops:dashboard')).status_code, 200)


class DedicatedCustomerLoginTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user('ajay', password='StrongPass!482', first_name='Ajay')
        UserProfile.objects.create(user=self.customer, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=self.customer, phone='1234567890')

    def test_customer_login_page_has_mobile_password_and_login_button(self):
        response = self.client.get(reverse('customers:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mobile Number')
        self.assertContains(response, 'name="mobile_number"')
        self.assertContains(response, 'Password')
        self.assertContains(response, '>Login</button>')

    def test_ajay_logs_in_with_mobile_and_lands_on_customer_dashboard(self):
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567890', 'password': 'StrongPass!482',
        })
        self.assertRedirects(response, reverse('customers:shop'))
        self.assertEqual(str(self.client.session['_auth_user_id']), str(self.customer.pk))
        dashboard = self.client.get(reverse('customers:dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.wsgi_request.user.profile.role, UserProfile.Role.CUSTOMER)
        self.assertRedirects(self.client.get(reverse('shops:dashboard')), reverse('customers:dashboard'))
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)

    def test_wrong_customer_password_shows_error_and_does_not_authenticate(self):
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567890', 'password': 'WrongPass!482',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mobile number or password is incorrect.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_mobile_shows_error_and_does_not_authenticate(self):
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567899', 'password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mobile number or password is incorrect.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_deleted_or_inactive_customer_cannot_login(self):
        self.customer.customer_profile.is_deleted = True
        self.customer.customer_profile.save(update_fields=('is_deleted',))
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567890', 'password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mobile number or password is incorrect.')
        self.assertNotIn('_auth_user_id', self.client.session)

        self.customer.customer_profile.is_deleted = False
        self.customer.customer_profile.save(update_fields=('is_deleted',))
        self.customer.is_active = False
        self.customer.save(update_fields=('is_active',))
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567890', 'password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_anonymous_customer_dashboard_redirects_to_dedicated_login(self):
        response = self.client.get(reverse('customers:dashboard'))
        self.assertRedirects(response, f"{reverse('customers:login')}?next={reverse('customers:dashboard')}")

    def test_shopkeeper_login_route_and_django_admin_login_are_unchanged(self):
        shopkeeper = User.objects.create_user('separate-shopkeeper', password='StrongPass!482')
        UserProfile.objects.create(user=shopkeeper, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=shopkeeper, phone='9123456789')
        response = self.client.post(reverse('accounts:login'), {
            'username': 'separate-shopkeeper', 'password': 'StrongPass!482',
        })
        self.assertEqual(response.status_code, 302)
        routed = self.client.get(response.url)
        self.assertRedirects(routed, reverse('shops:dashboard'))
        self.client.logout()

        admin = User.objects.create_superuser('admin-login-test', 'admin@example.test', 'StrongPass!482')
        self.assertEqual(self.client.get('/admin/login/').status_code, 200)
        response = self.client.post('/admin/login/', {
            'username': admin.username, 'password': 'StrongPass!482', 'next': '/admin/',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

        customer_login_page = self.client.get(reverse('customers:login'))
        self.assertEqual(customer_login_page.status_code, 200)
        self.assertContains(customer_login_page, 'Mobile Number')
        response = self.client.post(reverse('customers:login'), {
            'mobile_number': '1234567890', 'password': 'StrongPass!482',
        })
        self.assertRedirects(response, reverse('customers:shop'))
        shop_page = self.client.get(reverse('customers:shop'))
        self.assertEqual(shop_page.status_code, 200)
        self.assertEqual(shop_page.wsgi_request.user.profile.role, UserProfile.Role.CUSTOMER)
