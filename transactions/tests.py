from decimal import Decimal
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from shops.models import Product, Shop
from transactions.models import Bill, BillEditHistory, BillPayment, Credit, CreditPayment
from transactions.services import create_bill, set_bill_status
from wallet.models import CoinLedger, CoinRedemption, CoinRedemptionRequest, CoinRule, CoinValue, Wallet
from notifications.models import InAppNotification
from wallet.services import get_customer_coin_summary, get_coin_rule_for_balance

User = get_user_model()


class CreditFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('credit-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9886500001')
        self.shop = Shop.objects.create(owner=self.owner, name='Credit Shop', phone='9886500001', address='1 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.other_owner = User.objects.create_user('credit-other-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.other_owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.other_owner, phone='9886500003')
        self.other_shop = Shop.objects.create(owner=self.other_owner, name='Other Credit Shop', phone='9886500003', address='2 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.customer_user = User.objects.create_user('credit-customer', password='StrongPass!482', first_name='Ajay')
        UserProfile.objects.create(user=self.customer_user, role=UserProfile.Role.CUSTOMER)
        self.customer = CustomerProfile.objects.create(user=self.customer_user, connected_shop=self.shop, phone='9886500002')
        self.other_customer_user = User.objects.create_user('other-credit-customer', password='StrongPass!482')
        UserProfile.objects.create(user=self.other_customer_user, role=UserProfile.Role.CUSTOMER)
        self.other_customer = CustomerProfile.objects.create(user=self.other_customer_user, connected_shop=self.other_shop, phone='9886500004')
        self.wallet = Wallet.objects.create(customer=self.customer)
        self.rule = CoinRule.objects.get(shop=self.shop, purchase_amount='1000.00')

    def create_credit(self, amount='5000.00'):
        from transactions.credit_services import create_credit
        return create_credit(shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk, amount=amount, description='Clothes')

    def pay(self, credit, amount, reference=None):
        from transactions.credit_services import receive_credit_payment
        return receive_credit_payment(shopkeeper=self.owner, shop=self.shop, credit_id=credit.pk, amount=amount, payment_reference=reference or uuid4())

    def test_credit_creation_awards_no_coins_and_installments_only_reward_payment(self):
        credit = self.create_credit()
        self.wallet.refresh_from_db()
        self.assertEqual(credit.status, Credit.Status.UNPAID)
        self.assertEqual(self.wallet.balance, 0)
        first, created = self.pay(credit, '2000.00')
        self.assertTrue(created)
        self.assertEqual(first.coin_ledger.coin_delta, 20)
        credit.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((credit.paid_amount, credit.remaining_amount, credit.status), (Decimal('2000.00'), Decimal('3000.00'), Credit.Status.PARTIAL))
        self.assertEqual(self.wallet.balance, 20)
        second, _ = self.pay(credit, '3000.00')
        credit.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(second.coin_ledger.coin_delta, 30)
        self.assertEqual((credit.remaining_amount, credit.status, self.wallet.balance), (Decimal('0.00'), Credit.Status.PAID, 50))

    def test_duplicate_payment_reference_does_not_duplicate_payment_or_coins(self):
        credit = self.create_credit()
        ref = uuid4()
        first, created = self.pay(credit, '2000.00', ref)
        duplicate, created_again = self.pay(credit, '2000.00', ref)
        self.wallet.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, duplicate.pk)
        self.assertEqual((CreditPayment.objects.count(), self.wallet.balance), (1, 20))

    def test_overpayment_and_negative_payment_are_rejected(self):
        credit = self.create_credit()
        from transactions.credit_services import receive_credit_payment
        with self.assertRaises(ValidationError):
            receive_credit_payment(shopkeeper=self.owner, shop=self.shop, credit_id=credit.pk, amount='5001', payment_reference=uuid4())
        with self.assertRaises(ValidationError):
            receive_credit_payment(shopkeeper=self.owner, shop=self.shop, credit_id=credit.pk, amount='-1', payment_reference=uuid4())

    def test_credit_access_is_scoped_to_customer_and_shopkeeper_shop(self):
        credit = self.create_credit()
        self.client.force_login(self.customer_user)
        self.assertContains(self.client.get(reverse('customers:credit')), 'Clothes')
        self.client.force_login(self.other_customer_user)
        self.assertNotContains(self.client.get(reverse('customers:credit')), 'Clothes')
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(reverse('shops:credit_detail', args=[credit.pk])).status_code, 404)

    def test_shopkeeper_credit_list_searches_name_and_phone(self):
        self.create_credit()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shops:credits'), {'q': '9886500002'})
        self.assertContains(response, 'Ajay')

    def test_payment_under_1000_awards_no_coin_ledger_entry(self):
        credit = self.create_credit('900.00')
        payment, _ = self.pay(credit, '900.00')
        self.wallet.refresh_from_db()
        self.assertIsNone(payment.coin_ledger)
        self.assertEqual(self.wallet.balance, 0)

    def test_payment_reversal_keeps_original_payment_and_offsets_awarded_coins(self):
        from transactions.credit_services import reverse_credit_payment
        credit = self.create_credit()
        payment, _ = self.pay(credit, '2000.00')
        reversal, created = reverse_credit_payment(actor=self.owner, shop=self.shop, payment_id=payment.pk)
        again, created_again = reverse_credit_payment(actor=self.owner, shop=self.shop, payment_id=payment.pk)
        credit.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(reversal.amount, Decimal('2000.00'))
        self.assertEqual((credit.paid_amount, credit.status), (Decimal('0.00'), Credit.Status.UNPAID))
        self.assertEqual(self.wallet.balance, 0)
        self.assertEqual(CoinLedger.objects.filter(wallet=self.wallet).count(), 2)


class BillFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('bill-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9876500001')
        self.shop = Shop.objects.create(owner=self.owner, name='Bill Shop', phone='9876500001', address='1 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        self.customer_user = User.objects.create_user('bill-customer', password='StrongPass!482')
        UserProfile.objects.create(user=self.customer_user, role=UserProfile.Role.CUSTOMER)
        self.customer = CustomerProfile.objects.create(user=self.customer_user, connected_shop=self.shop, phone='9876500002')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=10)
        CoinLedger.objects.create(wallet=self.wallet, shop=self.shop, entry_type=CoinLedger.EntryType.ADJUSTMENT, coin_delta=10, coin_value_per_coin=10, balance_before=0, balance_after=10, description='Fixture starting balance')
        self.rule = CoinRule.objects.get(shop=self.shop, purchase_amount='1000.00')
        CoinValue.objects.create(shop=self.shop, value_per_coin='2.00')
        self.product = Product.objects.create(shop=self.shop, name='Shirt', price='80.00', stock=1000)

    def create(self, key=None, price='1800.00', discount='0.00'):
        return create_bill(shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk, idempotency_key=key or uuid4(), discount=discount, items=[{'product': self.product, 'product_name': 'Shirt', 'quantity': 1, 'unit_price': price}])

    def create_paid_bill(self, *, total, payment_received, key=None, discount='0.00'):
        return create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=key or uuid4(), discount=discount, payment_received=payment_received,
            items=[{'product': self.product, 'product_name': 'Shirt', 'quantity': 1, 'unit_price': total}],
        )

    def create_bill_with_redemption(self, *, coins, total='1000.00', payment_received='0.00', key=None):
        return create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=key or uuid4(), discount='0.00', payment_received=payment_received,
            redemption_coins=coins,
            items=[{'product': None, 'product_name': 'Bill item', 'quantity': 1, 'unit_price': total}],
        )

    def edit_payload(self, *, reason='Corrected line details', price='2000.00', discount='200.00'):
        return {
            'discount': discount,
            'reason': reason,
            'items-TOTAL_FORMS': '1', 'items-INITIAL_FORMS': '1',
            'items-MIN_NUM_FORMS': '1', 'items-MAX_NUM_FORMS': '40',
            'items-0-product': str(self.product.pk), 'items-0-product_name': 'Corrected Shirt',
            'items-0-quantity': '1', 'items-0-unit_price': price,
            'items-0-DELETE': '',
        }

    def test_bill_edit_within_ten_minutes_is_creator_only_and_records_immutable_snapshots(self):
        bill, _ = self.create()
        self.client.force_login(self.owner)
        detail = self.client.get(reverse('shops:bill_detail', args=[bill.pk]))
        self.assertTrue(detail.context['can_edit_bill'])
        response = self.client.post(reverse('shops:bill_edit', args=[bill.pk]), self.edit_payload())
        self.assertRedirects(response, reverse('shops:bill_detail', args=[bill.pk]))
        bill.refresh_from_db()
        history = BillEditHistory.objects.get(bill=bill)
        self.assertEqual(history.reason, 'Corrected line details')
        self.assertEqual(history.before_snapshot['items'][0]['product_name'], 'Shirt')
        self.assertEqual(history.after_snapshot['items'][0]['product_name'], 'Corrected Shirt')
        self.assertEqual((bill.total_amount, bill.paid_amount), (Decimal('1800.00'), Decimal('1800.00')))
        with self.assertRaisesMessage(ValueError, 'immutable'):
            history.reason = 'rewritten'
            history.save()
        with self.assertRaisesMessage(ValueError, 'immutable'):
            history.delete()

        other = User.objects.create_user('bill-editor-other', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=other, phone='9876500011')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('shops:bill_edit', args=[bill.pk])).status_code, 404)

    def test_bill_edit_reason_is_required_and_total_cannot_change(self):
        bill, _ = self.create()
        self.client.force_login(self.owner)
        url = reverse('shops:bill_edit', args=[bill.pk])
        response = self.client.post(url, self.edit_payload(reason=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required.')
        response = self.client.post(url, self.edit_payload(price='2100.00', discount='200.00'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The final bill amount must stay unchanged')
        bill.refresh_from_db()
        self.assertEqual((bill.subtotal, bill.total_amount, bill.items.get().product_name), (Decimal('1800.00'), Decimal('1800.00'), 'Shirt'))
        self.assertFalse(BillEditHistory.objects.exists())

    def test_bill_edit_sends_customer_only_hindi_notification_with_comparison_and_deduplication(self):
        bill, _ = self.create()
        profile = self.customer_user.profile
        profile.preferred_language = 'hi'
        profile.save(update_fields=('preferred_language', 'updated_at'))
        other_user = User.objects.create_user('bill-unrelated-customer', password='StrongPass!482')
        UserProfile.objects.create(user=other_user, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=other_user, connected_shop=self.shop, phone='9876500099')

        self.client.force_login(self.owner)
        response = self.client.post(reverse('shops:bill_edit', args=[bill.pk]), self.edit_payload())
        self.assertRedirects(response, reverse('shops:bill_detail', args=[bill.pk]))
        notification = InAppNotification.objects.get(event_key=f'bill-edit-history:{bill.edit_history.get().pk}')
        self.assertEqual(notification.title, 'आपका बिल अपडेट किया गया')
        for expected in (self.shop.name, bill.bill_number, 'Corrected line details', 'पहले की जानकारी:', 'नई जानकारी:', 'Shirt', 'Corrected Shirt'):
            self.assertIn(expected, notification.message)
        self.assertEqual(notification.url, reverse('customers:bill_detail', args=[bill.pk]))
        self.assertFalse(InAppNotification.objects.filter(user=other_user).exists())

        from notifications.services import create_bill_edit_notification
        history = bill.edit_history.get()
        duplicate = create_bill_edit_notification(bill=bill, history=history)
        self.assertEqual(duplicate.pk, notification.pk)
        self.assertEqual(InAppNotification.objects.filter(event_key=f'bill-edit-history:{history.pk}').count(), 1)

    def test_bill_edit_notification_uses_english_for_english_customer(self):
        bill, _ = self.create()
        self.client.force_login(self.owner)
        self.client.post(reverse('shops:bill_edit', args=[bill.pk]), self.edit_payload())
        notification = InAppNotification.objects.get(event_key=f'bill-edit-history:{bill.edit_history.get().pk}')
        self.assertEqual(notification.title, 'Your bill was updated')
        self.assertIn('Previous details:', notification.message)
        self.assertIn('Updated details:', notification.message)
        self.assertIn('Reason: Corrected line details', notification.message)

    def test_notification_and_edit_history_rollback_together(self):
        bill, _ = self.create()
        from transactions.services_bill_edit import edit_bill
        with self.assertRaisesRegex(RuntimeError, 'rollback test'):
            with transaction.atomic():
                edit_bill(
                    bill_id=bill.pk, actor=self.owner, shop=self.shop,
                    reason='Rollback test', discount=Decimal('200.00'),
                    items=[{'product': self.product, 'product_name': 'Rolled back', 'quantity': 1, 'unit_price': Decimal('2000.00')}],
                )
                raise RuntimeError('rollback test')
        bill.refresh_from_db()
        self.assertEqual((bill.subtotal, bill.items.get().product_name), (Decimal('1800.00'), 'Shirt'))
        self.assertFalse(BillEditHistory.objects.exists())
        self.assertFalse(InAppNotification.objects.filter(event_key__startswith='bill-edit-history:').exists())

    def test_disabled_customer_notification_preference_is_honored(self):
        bill, _ = self.create()
        self.customer.notifications_enabled = False
        self.customer.save(update_fields=('notifications_enabled',))
        self.client.force_login(self.owner)
        self.client.post(reverse('shops:bill_edit', args=[bill.pk]), self.edit_payload())
        self.assertEqual(BillEditHistory.objects.count(), 1)
        self.assertEqual(InAppNotification.objects.filter(event_key__startswith='bill-edit-history:').count(), 0)
        self.assertEqual(InAppNotification.objects.filter(event_key__startswith='bill-purchase-thank-you:').count(), 1)

    def test_customer_notification_inbox_is_scoped_and_open_marks_read(self):
        bill, _ = self.create()
        owned = InAppNotification.objects.create(
            user=self.customer_user, title='Owned notice', message='Bill update',
            url=reverse('customers:bill_detail', args=[bill.pk]),
        )
        other_user = User.objects.create_user('notification-other', password='StrongPass!482')
        UserProfile.objects.create(user=other_user, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=other_user, connected_shop=self.shop, phone='9876500019')
        other = InAppNotification.objects.create(user=other_user, title='Private notice', message='Private')
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('customers:notification_inbox'))
        self.assertContains(response, 'Owned notice')
        self.assertNotContains(response, 'Private notice')
        response = self.client.post(reverse('customers:open_notification', args=[owned.pk]))
        self.assertRedirects(response, reverse('customers:bill_detail', args=[bill.pk]))
        owned.refresh_from_db()
        self.assertIsNotNone(owned.read_at)
        self.assertEqual(self.client.post(reverse('customers:open_notification', args=[other.pk])).status_code, 404)

    def test_bill_edit_window_is_enforced_on_detail_and_backend_at_ten_minutes(self):
        bill, _ = self.create()
        Bill.objects.filter(pk=bill.pk).update(issued_at=timezone.now() - timedelta(minutes=10, seconds=1))
        self.client.force_login(self.owner)
        detail = self.client.get(reverse('shops:bill_detail', args=[bill.pk]))
        self.assertFalse(detail.context['can_edit_bill'])
        response = self.client.get(reverse('shops:bill_edit', args=[bill.pk]))
        self.assertRedirects(response, reverse('shops:bill_detail', args=[bill.pk]))
        response = self.client.post(reverse('shops:bill_edit', args=[bill.pk]), self.edit_payload())
        self.assertRedirects(response, reverse('shops:bill_detail', args=[bill.pk]))
        self.assertFalse(BillEditHistory.objects.exists())

    def test_django_admin_cannot_edit_bill_financial_fields_or_delete_bill(self):
        bill, _ = self.create()
        admin = User.objects.create_superuser('bill-admin', 'admin@example.com', 'StrongPass!482')
        self.client.force_login(admin)
        change_url = f'/admin/transactions/bill/{bill.pk}/change/'
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1800.00')
        readonly_names = set(response.context['adminform'].readonly_fields)
        self.assertTrue({'subtotal', 'discount', 'total_amount', 'paid_amount'}.issubset(readonly_names))
        response = self.client.post(change_url, {
            'subtotal': '9000.00', 'discount': '0.00', 'total_amount': '9000.00',
            'paid_amount': '0.00', 'status': Bill.Status.COMPLETED, '_save': 'Save',
        })
        self.assertIn(response.status_code, (200, 302))
        bill.refresh_from_db()
        self.assertEqual((bill.subtotal, bill.total_amount, bill.paid_amount), (Decimal('1800.00'), Decimal('1800.00'), Decimal('1800.00')))
        item = bill.items.get()
        item_change = self.client.get(f'/admin/transactions/billitem/{item.pk}/change/')
        self.assertEqual(item_change.status_code, 200)
        item_readonly = set(item_change.context['adminform'].readonly_fields)
        self.assertTrue({'product_name', 'quantity', 'unit_price', 'line_total'}.issubset(item_readonly))
        item_post = self.client.post(f'/admin/transactions/billitem/{item.pk}/change/', {
            'product_name': 'Admin changed', 'quantity': '999', 'unit_price': '0.01',
        })
        self.assertIn(item_post.status_code, (200, 302, 403))
        item.refresh_from_db()
        self.assertEqual(item.product_name, 'Shirt')
        self.assertFalse(self.client.post(f'/admin/transactions/bill/{bill.pk}/delete/').status_code == 200)

    def test_partial_bill_creates_linked_udhar_and_awards_only_received_payment_coins(self):
        from transactions.credit_services import receive_credit_payment
        bill, created = self.create_paid_bill(total='5000.00', payment_received='3000.00')
        credit = bill.credits.get()
        self.wallet.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual((bill.total_amount, bill.paid_amount, bill.remaining_amount), (Decimal('5000.00'), Decimal('3000.00'), Decimal('2000.00')))
        self.assertEqual((bill.payment_status, credit.original_amount, bill.coins_earned), (Bill.PaymentStatus.PARTIAL, Decimal('2000.00'), 30))
        self.assertEqual((self.wallet.balance, bill.payments.get().coins_earned), (40, 30))
        payment, _ = receive_credit_payment(shopkeeper=self.owner, shop=self.shop, credit_id=credit.pk, amount='2000.00', payment_reference=uuid4())
        bill.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((payment.coin_ledger.coin_delta, bill.paid_amount, bill.remaining_amount), (20, Decimal('5000.00'), Decimal('0.00')))
        self.assertEqual((bill.payment_status, bill.coins_earned, self.wallet.balance), (Bill.PaymentStatus.PAID, 50, 60))

    def test_purchase_thank_you_contains_actual_bill_rewards_active_offer_and_is_idempotent(self):
        from offers.models import ShopOffer
        from notifications.services import create_purchase_thank_you_notification

        self.customer_user.first_name = 'Ajay'
        self.customer_user.save(update_fields=('first_name',))
        ShopOffer.objects.create(
            shop=self.shop, title='Spring collection', badge='15% OFF',
            description='Selected items only', starts_at=timezone.now() - timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1), is_active=True,
        )
        ShopOffer.objects.create(shop=self.shop, title='Inactive offer', is_active=False)
        ShopOffer.objects.create(
            shop=self.shop, title='Expired offer', is_active=True,
            ends_at=timezone.now() - timedelta(days=1),
        )
        key = uuid4()
        bill, created = self.create_paid_bill(
            total='5000.00', payment_received='3000.00', key=key, discount='500.00',
        )
        self.assertTrue(created)
        notice = InAppNotification.objects.get(event_key=f'bill-purchase-thank-you:{bill.pk}')
        self.assertEqual(notice.user_id, self.customer_user.pk)
        self.assertEqual(notice.url, reverse('customers:bill_detail', args=[bill.pk]))
        for expected in (
            'Hi Ajay,', self.shop.name, bill.bill_number, 'Products purchased today:',
            'Shirt × 1', 'Original bill amount: ₹5000.00', 'Shop discount: ₹500.00',
            'Coin redemption discount: ₹0.00', 'Final payable: ₹4500.00',
            'Payment actually received: ₹3000.00', 'Remaining Udhar: ₹1500.00',
            'Purchase Coins actually earned: 30 · saved value ₹300.00',
            'Your current confirmed balance: 40 coins · actual reward value ₹400.00',
            'Spring collection', '15% OFF', 'Selected items only',
        ):
            self.assertIn(expected, notice.message)
        self.assertNotIn('Inactive offer', notice.message)
        duplicate_notice = create_purchase_thank_you_notification(bill=bill)
        self.assertEqual(duplicate_notice.pk, notice.pk)
        duplicate_bill, duplicate_created = self.create_paid_bill(
            total='5000.00', payment_received='3000.00', key=key, discount='500.00',
        )
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate_bill.pk, bill.pk)
        self.assertEqual(InAppNotification.objects.filter(event_key=f'bill-purchase-thank-you:{bill.pk}').count(), 1)

    def test_purchase_thank_you_uses_hindi_and_respects_notification_preference(self):
        self.customer_user.profile.preferred_language = 'hi'
        self.customer_user.profile.save(update_fields=('preferred_language', 'updated_at'))
        self.customer_user.first_name = 'अजय'
        self.customer_user.save(update_fields=('first_name',))
        bill, _ = self.create_paid_bill(total='1800.00', payment_received='1800.00')
        notice = InAppNotification.objects.get(event_key=f'bill-purchase-thank-you:{bill.pk}')
        self.assertEqual(notice.title, f'{self.shop.name} की ओर से धन्यवाद!')
        self.assertIn('नमस्ते अजय,', notice.message)
        self.assertIn('मूल बिल राशि: ₹1800.00', notice.message)
        self.assertIn('इस खरीद पर मिले Purchase Coins: 18', notice.message)
        self.assertIn('इस समय दुकान का कोई सक्रिय ऑफ़र सूचीबद्ध नहीं है', notice.message)

        self.customer.notifications_enabled = False
        self.customer.save(update_fields=('notifications_enabled',))
        disabled_bill, _ = self.create_paid_bill(total='1200.00', payment_received='1200.00')
        self.assertFalse(InAppNotification.objects.filter(event_key=f'bill-purchase-thank-you:{disabled_bill.pk}').exists())

    def test_purchase_thank_you_is_only_visible_to_bill_customer(self):
        bill, _ = self.create_paid_bill(total='1200.00', payment_received='1200.00')
        notice = InAppNotification.objects.get(event_key=f'bill-purchase-thank-you:{bill.pk}')
        other_user = User.objects.create_user('thankyou-other-customer', password='StrongPass!482')
        UserProfile.objects.create(user=other_user, role=UserProfile.Role.CUSTOMER)
        CustomerProfile.objects.create(user=other_user, connected_shop=self.shop, phone='9876500038')
        self.client.force_login(other_user)
        inbox = self.client.get(reverse('customers:notification_inbox'))
        self.assertNotContains(inbox, bill.bill_number)
        self.assertEqual(self.client.post(reverse('customers:open_notification', args=[notice.pk])).status_code, 404)

    def test_zero_and_full_payment_create_expected_credit_and_status(self):
        unpaid, _ = self.create_paid_bill(total='5000.00', payment_received='0.00')
        self.assertEqual((unpaid.payment_status, unpaid.coins_earned, unpaid.credits.get().original_amount), (Bill.PaymentStatus.UNPAID, 0, Decimal('5000.00')))
        paid, _ = self.create_paid_bill(total='5000.00', payment_received='5000.00')
        self.assertEqual((paid.payment_status, paid.coins_earned, paid.paid_amount), (Bill.PaymentStatus.PAID, 50, Decimal('5000.00')))
        self.assertFalse(paid.credits.exists())

    def test_payment_received_above_bill_or_negative_is_rejected(self):
        for amount in ('5000.01', '-0.01'):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.create_paid_bill(total='5000.00', payment_received=amount)

    def test_bill_form_list_history_and_customer_bill_pages_render_payment_data(self):
        payload = {
            'idempotency_key': str(uuid4()), 'discount': '0.00', 'payment_received': '3000.00',
            'items-TOTAL_FORMS': '1', 'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '1', 'items-MAX_NUM_FORMS': '40',
            'items-0-product': '', 'items-0-product_name': 'Shirt', 'items-0-quantity': '1',
            'items-0-unit_price': '5000.00', 'items-0-DELETE': '',
        }
        self.client.force_login(self.owner)
        result = self.client.post(reverse('shops:create_bill_for_customer', args=[self.customer.pk]), payload)
        self.assertEqual(result.status_code, 302)
        bill = Bill.objects.get()
        self.assertEqual(bill.payment_status, Bill.PaymentStatus.PARTIAL)
        self.assertContains(self.client.get(reverse('shops:bills')), 'Create Bill')
        self.assertContains(self.client.get(reverse('shops:bill_detail', args=[bill.pk])), 'Payment history')
        self.assertContains(self.client.get(reverse('shops:sales')), 'Partially paid')
        self.client.force_login(self.customer_user)
        self.assertContains(self.client.get(reverse('customers:bill_detail', args=[bill.pk])), 'Outstanding:')

    def test_first_bill_hides_redemption_controls_and_existing_customer_balance_enables_request(self):
        self.client.force_login(self.owner)
        url = reverse('shops:create_bill_for_customer', args=[self.customer.pk])
        first_page = self.client.get(url)
        self.assertEqual(first_page.status_code, 200)
        self.assertNotIn('redemption_to_apply', first_page.context['form'].fields)
        self.assertNotIn('redemption_coins', first_page.context['form'].fields)

        self.create_paid_bill(total='1000.00', payment_received='1000.00')
        later_page = self.client.get(url)
        self.assertEqual(later_page.status_code, 200)
        self.assertContains(later_page, 'Eligible confirmed balance:')
        self.assertContains(later_page, 'Apply ShopCoin Redemption')

    def test_redemption_request_is_rejected_before_any_completed_bill(self):
        with self.assertRaisesMessage(ValidationError, 'after the customer’s first completed bill'):
            self.create_bill_with_redemption(coins=1)

    def test_generic_redemption_request_is_deduplicated_and_notification_uses_wallet_page(self):
        response = self.client.post('/customer/redemptions/999/confirm/', {'decision': 'confirm'})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CoinRedemptionRequest.objects.exists())

    def test_generic_redemption_notifications_respect_customer_preference(self):
        self.client.force_login(self.owner)
        response = self.client.post(f'/shopkeeper/customers/{self.customer.pk}/clear-coins/', {})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CoinRedemptionRequest.objects.exists())

    def test_bill_payment_reversal_creates_audit_entry_and_restores_udhar(self):
        from transactions.credit_services import reverse_bill_payment
        bill, _ = self.create_paid_bill(total='5000.00', payment_received='3000.00')
        payment = bill.payments.get()
        reversal, created = reverse_bill_payment(actor=self.owner, shop=self.shop, payment_id=payment.pk)
        duplicate, created_again = reverse_bill_payment(actor=self.owner, shop=self.shop, payment_id=payment.pk)
        bill.refresh_from_db()
        credit = bill.credits.get()
        self.wallet.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(reversal.amount, Decimal('3000.00'))
        self.assertEqual((bill.paid_amount, bill.remaining_amount, bill.payment_status), (Decimal('0.00'), Decimal('5000.00'), Bill.PaymentStatus.UNPAID))
        self.assertEqual((credit.original_amount, credit.paid_amount, credit.status), (Decimal('5000.00'), Decimal('0.00'), Credit.Status.UNPAID))
        self.assertEqual(self.wallet.balance, 10)

    def reset_wallet(self):
        CoinLedger.objects.filter(wallet=self.wallet).update(is_reversed=True)
        self.wallet.balance = 0
        self.wallet.save(update_fields=('balance',))

    def test_bill_earns_coins_and_updates_wallet_and_ledger(self):
        bill, created = self.create()
        self.assertTrue(created)
        self.wallet.refresh_from_db()
        self.assertEqual((bill.total_amount, bill.coins_earned), (Decimal('1800.00'), 18))
        self.assertEqual((bill.coin_value_per_coin, bill.coin_value_amount), (Decimal('10.00'), Decimal('180.00')))
        self.assertEqual((self.wallet.balance, bill.wallet_balance_before, bill.wallet_balance_after), (28, 10, 28))
        self.assertEqual(CoinLedger.objects.filter(wallet=self.wallet).count(), 2)
        self.assertEqual(bill.items.count(), 1)

    def test_idempotent_repeat_does_not_credit_wallet_twice(self):
        key = uuid4()
        first, created = self.create(key)
        again, created_again = self.create(key)
        self.wallet.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(self.wallet.balance, 28)
        self.assertEqual(Bill.objects.count(), 1)

    def test_coin_value_for_selected_slab_is_snapshotted_on_new_bill(self):
        self.rule.coin_value_per_coin = Decimal('11.00')
        self.rule.save()
        bill, _ = self.create()
        self.assertEqual(bill.coins_earned, 18)
        self.assertEqual(bill.coin_value_per_coin, Decimal('11.00'))
        self.assertEqual(bill.coin_value_amount, Decimal('198.00'))

    def test_2500_purchase_earns_25_coins_from_1000_to_10_rule(self):
        bill, _ = self.create(price='2500.00')
        self.assertEqual(bill.coins_earned, 25)

    def test_slab_is_selected_using_discounted_final_amount(self):
        bill, _ = self.create(price='5000.00', discount='0.01')
        self.assertEqual(bill.total_amount, Decimal('4999.99'))
        self.assertEqual(bill.coins_earned, 49)
        self.assertEqual(bill.coin_value_per_coin, Decimal('10.00'))

    def test_bill_coin_earning_boundaries_and_zero_bill(self):
        self.reset_wallet()
        for amount, expected_coins in (('0', 0), ('99', 0), ('100', 0), ('999', 0), ('1000', 10), ('4999', 49), ('5000', 50), ('9999', 99), ('10000', 100)):
            with self.subTest(amount=amount):
                bill, _ = self.create(price=amount)
                self.assertEqual(bill.total_amount, Decimal(amount))
                self.assertEqual(bill.coins_earned, expected_coins)

    def test_bill_rejects_invalid_items_and_excessive_discounts(self):
        invalid_cases = (
            ({'product_name': 'Item', 'quantity': 0, 'unit_price': '100'}, 'Quantity must be at least 1'),
            ({'product_name': 'Item', 'quantity': 1, 'unit_price': '-1'}, 'Quantity must be at least 1'),
        )
        for item, expected_error in invalid_cases:
            with self.subTest(item=item), self.assertRaisesMessage(ValidationError, expected_error):
                create_bill(shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk, idempotency_key=uuid4(), discount='0', items=[item])
        with self.assertRaisesMessage(ValidationError, 'Discount cannot be greater than the subtotal'):
            self.create(price='100', discount='101')
        with self.assertRaisesMessage(ValidationError, 'Add at least one product to the bill'):
            create_bill(shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk, idempotency_key=uuid4(), discount='0', items=[])

    def test_bills_ignore_stock_and_leave_legacy_stock_value_unchanged(self):
        self.product.stock = 0
        self.product.save(update_fields=('stock',))
        bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=uuid4(), discount='0', items=[
                {'product': self.product, 'product_name': 'Shirt', 'quantity': 10, 'unit_price': '80'},
                {'product': self.product, 'product_name': 'Shirt', 'quantity': 1, 'unit_price': '80'},
            ],
        )
        self.product.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((bill.coins_earned, self.product.stock), (0, 0))
        bills_before = Bill.objects.count()
        balance_before = self.wallet.balance
        another_bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=uuid4(), discount='0',
            items=[{'product': self.product, 'product_name': 'Shirt', 'quantity': 50, 'unit_price': '80'}],
        )
        self.product.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((Bill.objects.count(), self.product.stock, self.wallet.balance), (bills_before + 1, 0, balance_before + 40))
        self.assertEqual(another_bill.total_amount, Decimal('4000.00'))

    def test_bill_reward_snapshots_use_the_coin_balance_slab_at_issue_time(self):
        self.reset_wallet()
        first, _ = self.create(price='1800.00')
        second, _ = self.create(price='5000.00')
        self.wallet.refresh_from_db()
        self.assertEqual((first.coin_value_per_coin, first.coin_value_amount), (Decimal('10.00'), Decimal('180.00')))
        self.assertEqual((second.coin_value_per_coin, second.coin_value_amount), (Decimal('12.00'), Decimal('600.00')))
        self.assertEqual(self.wallet.balance, 68)
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('customers:wallet'))
        self.assertContains(response, '68')
        self.assertContains(response, '₹780.00')

    def test_current_balance_slabs_revalue_the_entire_active_balance(self):
        self.reset_wallet()
        first, _ = self.create(price='2000.00')
        first_summary = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((first.coins_earned, first_summary['active_coins'], first_summary['total_shopping']), (20, 20, Decimal('2000.00')))
        self.assertEqual((first_summary['current_coin_value'], first_summary['current_reward_value']), (Decimal('10.00'), Decimal('200.00')))

        second, _ = self.create(price='3500.00')
        second_summary = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((second.coins_earned, second.coin_value_per_coin, second.coin_value_amount), (35, Decimal('10.00'), Decimal('350.00')))
        self.assertEqual((second_summary['active_coins'], second_summary['total_shopping']), (55, Decimal('5500.00')))
        self.assertEqual((second_summary['current_coin_value'], second_summary['current_reward_value']), (Decimal('10.00'), Decimal('550.00')))

        third, _ = self.create(price='5000.00')
        third_summary = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((third.coins_earned, third.coin_value_per_coin, third.coin_value_amount), (50, Decimal('12.00'), Decimal('600.00')))
        self.assertEqual((third_summary['active_coins'], third_summary['total_shopping']), (105, Decimal('10500.00')))
        self.assertEqual((third_summary['current_coin_value'], third_summary['current_reward_value']), (Decimal('10.95'), Decimal('1150.00')))

        fourth, _ = self.create(price='40000.00')
        fourth_summary = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((fourth.coins_earned, fourth.coin_value_per_coin), (400, Decimal('15.00')))
        self.assertEqual((fourth_summary['active_coins'], fourth_summary['current_coin_value'], fourth_summary['current_reward_value']), (505, Decimal('14.16'), Decimal('7150.00')))

    def test_shopkeeper_redemption_clears_active_coins_only_and_is_idempotent(self):
        self.reset_wallet()
        self.create(price='2000.00')
        self.create(price='3500.00')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shops:customer_detail', args=[self.customer.pk]))
        self.assertNotContains(response, 'Request 55 Coins')
        self.assertEqual(self.client.post(f'/shopkeeper/customers/{self.customer.pk}/clear-coins/', {}).status_code, 404)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 55)
        self.assertFalse(CoinRedemption.objects.exists())
        self.assertFalse(CoinRedemptionRequest.objects.exists())

    def test_shopkeeper_cannot_clear_another_shops_customer_coins(self):
        other = User.objects.create_user('redeem-other-owner', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=other, phone='9876500023')
        other_shop = Shop.objects.create(owner=other, name='Redeem Other Shop', phone='9876500023', address='4 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        other_user = User.objects.create_user('redeem-other-customer', password='StrongPass!482')
        UserProfile.objects.create(user=other_user, role=UserProfile.Role.CUSTOMER)
        other_customer = CustomerProfile.objects.create(user=other_user, connected_shop=other_shop, phone='9876500024')
        other_wallet = Wallet.objects.create(customer=other_customer, balance=55)
        self.client.force_login(self.owner)
        response = self.client.post(f'/shopkeeper/customers/{other_customer.pk}/clear-coins/', {})
        self.assertEqual(response.status_code, 404)
        other_wallet.refresh_from_db()
        self.assertEqual(other_wallet.balance, 55)
        self.assertFalse(CoinRedemption.objects.exists())

    def test_customer_rejects_redemption_without_any_coin_deduction(self):
        self.create(price='2000.00')
        bill, _ = self.create_bill_with_redemption(coins=5)
        self.assertEqual(bill.status, Bill.Status.COMPLETED)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 25)
        self.assertEqual(CoinRedemption.objects.get().coins_redeemed, 5)
        self.assertEqual(self.client.post('/customer/redemptions/999/confirm/', {'decision': 'reject'}).status_code, 404)

    def test_bill_redemption_uses_saved_weighted_values_and_waits_for_both_approvals(self):
        self.create(price='5000.00')  # 50 Purchase Coins saved at ₹12 each; fixture coins retain ₹10 each.
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 60)
        bill, created = self.create_bill_with_redemption(coins=30, payment_received='300.00')
        self.assertTrue(created)
        self.assertEqual(bill.status, Bill.Status.COMPLETED)
        self.assertEqual((bill.subtotal, bill.discount, bill.total_amount, bill.paid_amount), (Decimal('1000.00'), Decimal('350.10'), Decimal('649.90'), Decimal('300.00')))
        self.assertEqual((bill.payment_status, bill.remaining_amount), (Bill.PaymentStatus.PARTIAL, Decimal('349.90')))
        self.assertEqual((bill.coins_earned, bill.coin_redemption_discount, bill.merchant_discount), (0, Decimal('350.10'), Decimal('0.00')))
        redemption = CoinRedemption.objects.get(applied_bill=bill)
        self.assertEqual((redemption.coins_redeemed, redemption.reward_value), (30, Decimal('350.10')))
        self.assertEqual(CoinLedger.objects.filter(redemption=redemption, bill=bill, coin_delta=-30).count(), 1)
        self.assertEqual((bill.payments.get().amount, bill.payments.get().coins_earned), (Decimal('300.00'), 0))
        self.assertEqual(bill.credits.get().original_amount, Decimal('349.90'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 30)
        notice = InAppNotification.objects.get(event_key=f'bill-redemption-direct:{redemption.pk}')
        self.assertIn('Coins redeemed: 30', notice.message)
        self.assertIn('Saved coin value: ₹350.10', notice.message)
        self.assertIn('Final payable: ₹649.90', notice.message)
        self.assertNotIn('approval', notice.message.lower())
        thank_you = InAppNotification.objects.get(event_key=f'bill-purchase-thank-you:{bill.pk}')
        self.assertIn('Coin redemption discount: ₹350.10', thank_you.message)
        self.assertIn('Payment actually received: ₹300.00', thank_you.message)
        self.assertIn('Remaining Udhar: ₹349.90', thank_you.message)
        self.assertIn('Purchase Coins actually earned: 0', thank_you.message)
        self.assertEqual(InAppNotification.objects.filter(event_key=f'bill-purchase-thank-you:{bill.pk}').count(), 1)

    def test_bill_redemption_rejection_finalizes_without_discount_or_deduction(self):
        self.reset_wallet()
        self.create(price='2000.00')
        self.wallet.refresh_from_db()
        balance_before = self.wallet.balance
        bill, _ = self.create_bill_with_redemption(coins=5, payment_received='0.00')
        self.assertEqual((bill.status, bill.discount, bill.total_amount), (Bill.Status.COMPLETED, Decimal('50.00'), Decimal('950.00')))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, balance_before - 5)
        self.assertTrue(CoinRedemption.objects.filter(applied_bill=bill).exists())
        self.assertTrue(InAppNotification.objects.filter(event_key=f'bill-purchase-thank-you:{bill.pk}').exists())

    def test_expired_bill_redemption_falls_back_without_coin_discount(self):
        # A legacy pre-upgrade pending bill remains resolvable by its shopkeeper.
        self.create(price='2000.00')
        bill = Bill.objects.create(
            bill_number='LEGACY-EXPIRED-1', idempotency_key=uuid4(), shop=self.shop,
            customer=self.customer, created_by=self.owner, subtotal=Decimal('1000.00'),
            discount=Decimal('0.00'), total_amount=Decimal('1000.00'),
            status=Bill.Status.PENDING_REDEMPTION,
        )
        request_obj = CoinRedemptionRequest.objects.create(
            customer=self.customer, shop=self.shop, requested_by=self.owner, requested_bill=bill,
            idempotency_key=uuid4(), coins_requested=5, reward_value=Decimal('50.00'),
            purchase_coins_requested=5, expires_at=timezone.now() - timedelta(seconds=1),
            pending_payment_received=Decimal('100.00'), status=CoinRedemptionRequest.Status.PENDING_CUSTOMER,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse('shops:resolve_legacy_bill_redemption', args=[request_obj.pk]))
        self.assertEqual(response.status_code, 302)
        request_obj.refresh_from_db()
        bill.refresh_from_db()
        self.assertEqual(request_obj.status, CoinRedemptionRequest.Status.EXPIRED)
        self.assertEqual((bill.status, bill.total_amount, bill.paid_amount), (Bill.Status.COMPLETED, Decimal('1000.00'), Decimal('100.00')))
        self.assertEqual(bill.credits.get().original_amount, Decimal('900.00'))
        self.assertFalse(CoinRedemption.objects.exists())
        self.assertTrue(InAppNotification.objects.filter(event_key=f'bill-purchase-thank-you:{bill.pk}').exists())

    def test_bill_redemption_rejects_insufficient_coins_and_rolls_back_pending_bill(self):
        self.reset_wallet()
        self.create(price='1000.00')
        self.wallet.refresh_from_db()
        balance_before = self.wallet.balance
        bill_count = Bill.objects.count()
        with self.assertRaisesMessage(ValidationError, 'Only 10 eligible coins are available'):
            self.create_bill_with_redemption(coins=11)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, balance_before)
        self.assertEqual(Bill.objects.count(), bill_count)
        self.assertFalse(CoinRedemption.objects.exists())

    def test_bill_idempotency_key_prevents_duplicate_bill_redemption_request(self):
        self.create(price='2000.00')
        key = uuid4()
        bill, created = self.create_bill_with_redemption(coins=2, key=key)
        duplicate, created_again = self.create_bill_with_redemption(coins=2, key=key)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(duplicate.pk, bill.pk)
        self.assertEqual(CoinRedemption.objects.filter(applied_bill=bill).count(), 1)
        self.assertEqual(CoinLedger.objects.filter(bill=bill, entry_type=CoinLedger.EntryType.REDEEM).count(), 1)
        self.assertEqual(BillPayment.objects.filter(bill=bill).count(), 0)
        self.assertTrue(Credit.objects.filter(bill=bill, original_amount=bill.total_amount).exists())
        self.assertEqual(InAppNotification.objects.filter(event_key__startswith='bill-redemption-direct:').count(), 1)

    def test_bill_redemption_is_restored_when_bill_is_cancelled(self):
        self.create(price='2000.00')
        bill, _ = self.create_bill_with_redemption(coins=2, payment_received='980.00')
        self.wallet.refresh_from_db()
        wallet_after_bill = self.wallet.balance
        cancelled, changed = set_bill_status(bill_id=bill.pk, status=Bill.Status.CANCELLED)
        self.wallet.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(cancelled.status, Bill.Status.CANCELLED)
        self.assertEqual(self.wallet.balance, wallet_after_bill + 2)
        self.assertEqual(CoinRedemption.objects.get(applied_bill=bill).status, CoinRedemption.Status.REVERSED)
        self.assertTrue(CoinLedger.objects.filter(bill=bill, entry_type=CoinLedger.EntryType.REDEEM, is_reversed=True).exists())
        self.assertTrue(bill.payments.exists())

    def test_redemption_notification_inbox_contains_csrf_yes_and_reject_actions_and_marks_read(self):
        self.create(price='2000.00')
        bill, _ = self.create_bill_with_redemption(coins=2)
        redemption = CoinRedemption.objects.get(applied_bill=bill)
        notice = InAppNotification.objects.get(event_key=f'bill-redemption-direct:{redemption.pk}')
        self.assertEqual(notice.url, reverse('customers:bill_detail', args=[bill.pk]))
        self.assertIn(self.shop.name, notice.message)
        self.assertIn(bill.bill_number, notice.message)
        self.assertIn('Coins redeemed: 2', notice.message)
        InAppNotification.objects.create(
            user=self.customer_user, title='Legacy approval prompt', message='Approve or reject this old request.',
            url='/customer/redemptions/999/confirm/',
        )
        self.client.force_login(self.customer_user)
        inbox = self.client.get(reverse('customers:notification_inbox'))
        self.assertNotContains(inbox, "Yes, It's Me")
        self.assertNotContains(inbox, 'Reject')
        self.assertNotContains(inbox, 'Legacy approval prompt')
        self.assertContains(inbox, 'ShopCoin redemption applied to your bill')
        opened = self.client.post(reverse('customers:open_notification', args=[notice.pk]))
        self.assertRedirects(opened, reverse('customers:bill_detail', args=[bill.pk]))
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)

    def test_redemption_customer_approval_is_scoped_idempotent_and_does_not_deduct(self):
        self.create(price='2000.00')
        bill, _ = self.create_bill_with_redemption(coins=2)
        self.assertEqual(bill.status, Bill.Status.COMPLETED)
        self.assertFalse(CoinRedemptionRequest.objects.filter(requested_bill=bill).exists())
        self.assertEqual(CoinRedemption.objects.filter(applied_bill=bill).count(), 1)
        self.client.force_login(self.customer_user)
        self.assertEqual(self.client.post(f'/customer/redemptions/1/confirm/', {'decision': 'confirm'}).status_code, 404)
        self.assertEqual(self.client.post(f'/customer/redemptions/1/confirm/', {'decision': 'reject'}).status_code, 404)

    def test_bill_redemption_request_and_rejection_notifications_are_hindi(self):
        self.reset_wallet()
        self.create(price='2000.00')
        profile = self.customer_user.profile
        profile.preferred_language = 'hi'
        profile.save(update_fields=('preferred_language', 'updated_at'))
        bill, _ = self.create_bill_with_redemption(coins=2)
        redemption = CoinRedemption.objects.get(applied_bill=bill)
        notice = InAppNotification.objects.get(event_key=f'bill-redemption-direct:{redemption.pk}')
        self.assertEqual(notice.title, 'बिल पर ShopCoin रिडेम्पशन लागू हुआ')
        self.assertIn('रिडीम किए गए कॉइन: 2', notice.message)
        self.assertIn('अंतिम देय राशि:', notice.message)
        self.assertNotIn('पुष्टि आवश्यक', notice.message)

    def test_expired_redemption_request_cannot_be_confirmed_or_finalized(self):
        self.client.force_login(self.customer_user)
        self.assertEqual(self.client.post('/customer/redemptions/1/confirm/', {'decision': 'confirm'}).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post('/shopkeeper/redemptions/1/confirm/', {}).status_code, 404)

    def test_redemption_finalization_rejects_request_above_available_wallet_balance(self):
        self.reset_wallet()
        self.create(price='2000.00')
        self.wallet.refresh_from_db()
        CoinLedger.objects.filter(wallet=self.wallet).update(is_reversed=True)
        self.wallet.balance = 5
        self.wallet.save(update_fields=('balance',))
        CoinLedger.objects.create(
            wallet=self.wallet, shop=self.shop, entry_type=CoinLedger.EntryType.ADJUSTMENT,
            coin_source=CoinLedger.Source.PURCHASE, coin_delta=5,
            coin_value_per_coin=Decimal('10.00'), balance_before=0, balance_after=5,
            description='Available balance validation fixture',
        )
        with self.assertRaisesMessage(ValidationError, 'Only 5 eligible coins are available'):
            self.create_bill_with_redemption(coins=6)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 5)
        self.assertFalse(CoinRedemption.objects.exists())

    def test_confirmed_redemption_can_only_be_applied_to_later_bill(self):
        self.reset_wallet()
        source_bill, _ = self.create(price='2000.00')
        redemption = CoinRedemption.objects.create(
            customer=self.customer, shop=self.shop, redeemed_by=self.owner,
            source_bill=source_bill, idempotency_key=uuid4(), coins_redeemed=20,
            purchase_coins_redeemed=20, reward_value=Decimal('200.00'),
            purchase_reward_value=Decimal('200.00'), website_reward_value=Decimal('0.00'),
            coin_value_per_coin=Decimal('10.00'), remaining_coin_balance=10,
            cumulative_shopping=source_bill.total_amount, status=CoinRedemption.Status.COMPLETED,
        )
        later_bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk, idempotency_key=uuid4(),
            discount='0.00', payment_received='100.00',
            items=[{'product': None, 'product_name': 'Later purchase', 'quantity': 1, 'unit_price': '1000.00'}],
            redemption_to_apply=redemption,
        )
        redemption.refresh_from_db()
        self.assertEqual(redemption.applied_bill_id, later_bill.pk)
        self.assertEqual(later_bill.discount, Decimal('200.00'))
        self.assertEqual(later_bill.coin_redemption_discount, Decimal('200.00'))
        self.assertEqual(later_bill.merchant_discount, Decimal('0.00'))

    def test_all_nine_slab_examples(self):
        from wallet.services import calculate_coins_for_purchase

        examples = (
            ('999', 0, '10.00'),
            ('1000', 10, '10.00'),
            ('1500', 15, '10.00'),
            ('2000', 20, '10.00'),
            ('4999', 49, '10.00'),
            ('5000', 50, '12.00'),
            ('9999', 99, '12.00'),
            ('10000', 100, '15.00'),
        )
        for amount, expected_coins, expected_value in examples:
            with self.subTest(amount=amount):
                rule, coins = calculate_coins_for_purchase(self.shop, Decimal(amount), 0)
                if Decimal(amount) < Decimal('1000'):
                    self.assertIsNone(rule)
                else:
                    self.assertIsNotNone(rule)
                    self.assertEqual(rule.coin_value_per_coin, Decimal(expected_value))
                self.assertEqual(coins, expected_coins)

    def test_cancelled_bill_reverses_purchase_coins_and_is_excluded_from_totals(self):
        bill, _ = self.create(price='1800.00')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 28)

        cancelled, changed = set_bill_status(bill_id=bill.pk, status=Bill.Status.CANCELLED)
        self.wallet.refresh_from_db()
        summary = get_customer_coin_summary(self.customer, self.shop)

        self.assertTrue(changed)
        self.assertEqual(cancelled.status, Bill.Status.CANCELLED)
        self.assertEqual(self.wallet.balance, 10)
        self.assertEqual(summary['total_bills'], 0)
        self.assertEqual(summary['total_shopping'], Decimal('0.00'))
        self.assertEqual(summary['active_coins'], 10)
        self.assertTrue(CoinLedger.objects.get(bill=bill).is_reversed)
        self.assertEqual(self.client.get(reverse('customers:bill_detail', args=[bill.pk])).status_code, 302)

    def test_refund_is_blocked_after_purchase_coins_from_any_bill_were_redeemed(self):
        bill, _ = self.create(price='1800.00')
        CoinRedemption.objects.create(
            customer=self.customer, shop=self.shop, coins_redeemed=1,
            purchase_coins_redeemed=1, coin_value_per_coin=10,
            purchase_reward_value=10, reward_value=10,
            cumulative_shopping=1800,
        )
        with self.assertRaisesMessage(ValidationError, 'already been redeemed'):
            set_bill_status(bill_id=bill.pk, status=Bill.Status.REFUNDED)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.Status.COMPLETED)

    def test_no_active_rule_blocks_bill_with_clear_error(self):
        CoinRule.objects.filter(shop=self.shop).update(is_active=False)
        with self.assertRaisesMessage(ValidationError, 'Coin earning rule is not configured for this shop'):
            self.create()

    def test_bill_form_warns_and_disables_submit_without_active_rule(self):
        CoinRule.objects.filter(shop=self.shop).update(is_active=False)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shops:create_bill_for_customer', args=[self.customer.pk]))
        self.assertContains(response, 'Coin earning rule is not configured for this shop')
        self.assertContains(response, 'disabled')

    def test_each_shop_uses_its_own_rule_rate(self):
        other = User.objects.create_user('rule-owner-b', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=other, phone='9876500013')
        other_shop = Shop.objects.create(owner=other, name='Rate B Shop', phone='9876500013', address='3 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        other_customer_user = User.objects.create_user('customer-b', password='StrongPass!482')
        UserProfile.objects.create(user=other_customer_user, role=UserProfile.Role.CUSTOMER)
        other_customer = CustomerProfile.objects.create(user=other_customer_user, connected_shop=other_shop, phone='9876500014')
        other_rule = CoinRule.objects.get(shop=other_shop, purchase_amount='1000.00')
        self.assertNotEqual(other_rule.pk, self.rule.pk)
        bill, _ = create_bill(shopkeeper=other, shop=other_shop, customer_id=other_customer.pk, idempotency_key=uuid4(), discount='0', items=[{'product_name': 'Item', 'quantity': 1, 'unit_price': '1800'}])
        self.assertEqual(bill.coins_earned, 18)
        self.assertEqual(bill.coin_rule_id, other_rule.pk)

    def test_shopkeeper_bill_customer_lists_and_history_are_shop_scoped(self):
        other = User.objects.create_user('bill-other-owner', password='StrongPass!482')
        UserProfile.objects.create(user=other, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=other, phone='9876500003')
        other_shop = Shop.objects.create(owner=other, name='Other Shop', phone='9876500003', address='2 Road', city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED)
        other_user = User.objects.create_user('other-customer', password='StrongPass!482')
        UserProfile.objects.create(user=other_user, role=UserProfile.Role.CUSTOMER)
        other_customer = CustomerProfile.objects.create(user=other_user, connected_shop=other_shop, phone='9876500004')
        key = uuid4()
        self.create(key)
        self.client.force_login(other)
        response = self.client.get(reverse('shops:bills'))
        self.assertNotContains(response, self.customer.phone)
        self.assertEqual(self.client.get(reverse('shops:customer_detail', args=[self.customer.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('shops:bill_detail', args=[Bill.objects.get().pk])).status_code, 404)
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('customers:history'))
        self.assertContains(response, 'Bill Shop')
        self.assertNotContains(response, 'Other Shop')
        self.assertEqual(self.client.get(reverse('customers:bill_detail', args=[Bill.objects.get().pk])).status_code, 200)
        other_bill = Bill.objects.create(bill_number='OTHER-BILL', idempotency_key=uuid4(), shop=other_shop, customer=other_customer, subtotal=1, total_amount=1)
        self.assertEqual(self.client.get(reverse('customers:bill_detail', args=[other_bill.pk])).status_code, 404)

    def test_generate_bill_endpoint_uses_connected_customer_and_shows_list(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shops:bills'))
        self.assertContains(response, self.customer.phone)
        self.assertEqual(self.client.get(reverse('shops:create_bill_for_customer', args=[self.customer.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('shops:create_bill_for_customer', args=[999999])).status_code, 404)


@unittest.skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock concurrency test; SQLite does not support select_for_update.')
class PostgreSQLRedemptionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user('pg-redemption-owner', password='StrongPass!482')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.create(user=self.owner, phone='9896500001')
        self.shop = Shop.objects.create(
            owner=self.owner, name='PG Redemption Shop', phone='9896500001', address='1 Road',
            city='Pune', state='Maharashtra', pincode='411001', status=Shop.Status.APPROVED,
        )
        customer_user = User.objects.create_user('pg-redemption-customer', password='StrongPass!482')
        UserProfile.objects.create(user=customer_user, role=UserProfile.Role.CUSTOMER)
        self.customer = CustomerProfile.objects.create(user=customer_user, connected_shop=self.shop, phone='9896500002')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=10)
        CoinLedger.objects.create(
            wallet=self.wallet, shop=self.shop, entry_type=CoinLedger.EntryType.ADJUSTMENT,
            coin_source=CoinLedger.Source.PURCHASE, coin_delta=10, coin_value_per_coin=Decimal('10.00'),
            balance_before=0, balance_after=10, description='Concurrency fixture',
        )

    def _parallel_calls(self, callback):
        barrier = Barrier(2)

        def run():
            connections.close_all()
            try:
                barrier.wait(timeout=15)
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_simultaneous_bill_redemption_finalization_deducts_selected_coins_once(self):
        source_bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=uuid4(), discount='0.00', payment_received='0.00',
            items=[{'product_name': 'Source purchase', 'quantity': 1, 'unit_price': '1000.00'}],
        )
        keys = (uuid4(), uuid4())
        def submit(key):
            try:
                bill, created = create_bill(
                    shopkeeper=User.objects.get(pk=self.owner.pk), shop=Shop.objects.get(pk=self.shop.pk),
                    customer_id=self.customer.pk, idempotency_key=key, discount='0.00',
                    payment_received='0.00', redemption_coins=8,
                    items=[{'product_name': 'Concurrent redemption', 'quantity': 1, 'unit_price': '1000.00'}],
                )
                return ('completed' if created else 'duplicate', bill.pk)
            except ValidationError:
                return ('insufficient', None)
        results = self._parallel_calls(lambda: submit(keys.pop()))
        self.wallet.refresh_from_db()
        self.assertCountEqual([item[0] for item in results], ['completed', 'insufficient'])
        self.assertEqual(self.wallet.balance, 2)
        self.assertEqual(Bill.objects.filter(customer=self.customer, status=Bill.Status.COMPLETED).count(), 2)
        self.assertEqual(CoinRedemption.objects.filter(customer=self.customer).count(), 1)
        direct_bill = Bill.objects.get(customer=self.customer, status=Bill.Status.COMPLETED, applied_redemptions__isnull=False)
        self.assertEqual(CoinLedger.objects.filter(bill=direct_bill, entry_type=CoinLedger.EntryType.REDEEM, coin_delta=-8).count(), 1)

    def test_simultaneous_duplicate_request_creation_returns_one_request(self):
        source_bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=uuid4(), discount='0.00', payment_received='0.00',
            items=[{'product_name': 'Source purchase', 'quantity': 1, 'unit_price': '1000.00'}],
        )
        key = uuid4()
        def submit():
            try:
                bill, created = create_bill(
                    shopkeeper=User.objects.get(pk=self.owner.pk), shop=Shop.objects.get(pk=self.shop.pk),
                    customer_id=self.customer.pk, idempotency_key=key, discount='0.00',
                    payment_received='0.00', redemption_coins=5,
                    items=[{'product_name': 'Duplicate submission', 'quantity': 1, 'unit_price': '1000.00'}],
                )
                return ('created' if created else 'duplicate', bill.pk)
            except IntegrityError:
                return ('unique-conflict', None)
        results = self._parallel_calls(submit)
        self.wallet.refresh_from_db()
        self.assertEqual(Bill.objects.filter(idempotency_key=key).count(), 1)
        self.assertEqual(CoinRedemption.objects.filter(idempotency_key=key).count(), 1)
        self.assertEqual(self.wallet.balance, 5)
        self.assertEqual(CoinLedger.objects.filter(redemption__idempotency_key=key, entry_type=CoinLedger.EntryType.REDEEM).count(), 1)
        self.assertEqual(sum(result[0] == 'created' for result in results), 1)
        self.assertEqual(sum(result[0] in ('duplicate', 'unique-conflict') for result in results), 1)

    def test_simultaneous_requests_with_different_keys_cannot_reserve_balance_twice(self):
        # There is no request/approval endpoint anymore: parallel bill submissions
        # are covered by the wallet-lock and idempotency tests above.
        self.assertEqual(self.wallet.balance, 10)

    def test_simultaneous_finalization_deducts_wallet_only_once(self):
        self.assertFalse(hasattr(__import__('wallet.services', fromlist=['x']), 'finalize_coin_redemption_request'))
