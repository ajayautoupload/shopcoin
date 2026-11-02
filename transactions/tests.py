from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from shops.models import Product, Shop
from transactions.models import Bill
from transactions.services import create_bill, set_bill_status
from wallet.models import CoinLedger, CoinRedemption, CoinRule, CoinValue, Wallet
from wallet.services import get_customer_coin_summary, get_coin_rule_for_balance

User = get_user_model()


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

    def test_catalog_stock_is_decremented_atomically_and_insufficient_stock_is_rejected(self):
        self.product.stock = 3
        self.product.save(update_fields=('stock',))
        bill, _ = create_bill(
            shopkeeper=self.owner, shop=self.shop, customer_id=self.customer.pk,
            idempotency_key=uuid4(), discount='0', items=[
                {'product': self.product, 'product_name': 'Shirt', 'quantity': 2, 'unit_price': '80'},
                {'product': self.product, 'product_name': 'Shirt', 'quantity': 1, 'unit_price': '80'},
            ],
        )
        self.product.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((bill.coins_earned, self.product.stock), (0, 0))
        bills_before = Bill.objects.count()
        balance_before = self.wallet.balance
        with self.assertRaisesMessage(ValidationError, 'Insufficient stock for Shirt. Only 0 available.'):
            self.create(price='80.00')
        self.product.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual((Bill.objects.count(), self.product.stock, self.wallet.balance), (bills_before, 0, balance_before))

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
        self.assertContains(response, 'Redeem 55 Coins')
        key = response.context['redemption_key']
        url = reverse('shops:clear_customer_coins', args=[self.customer.pk])
        data = {'idempotency_key': key, 'confirm_redemption': 'yes', 'reward_description': 'One eligible shirt'}

        self.assertEqual(self.client.post(url, {'idempotency_key': key, 'confirm_redemption': 'yes'}).status_code, 302)
        self.assertFalse(CoinRedemption.objects.exists())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.wallet.refresh_from_db()
        redemption = CoinRedemption.objects.get()
        self.assertEqual(self.wallet.balance, 0)
        self.assertEqual((redemption.coins_redeemed, redemption.coin_value_per_coin, redemption.reward_value, redemption.reward_description, redemption.remaining_coin_balance), (55, Decimal('10.00'), Decimal('550.00'), 'One eligible shirt', 0))
        self.assertEqual(CoinLedger.objects.get(redemption=redemption).coin_delta, -55)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(CoinRedemption.objects.count(), 1)
        self.client.force_login(self.customer_user)
        wallet_response = self.client.get(reverse('customers:wallet'))
        history_response = self.client.get(reverse('customers:history'))
        self.assertContains(wallet_response, '55 coins')
        self.assertContains(history_response, 'Coin redemptions')
        self.assertContains(history_response, '₹550.00')

        after_clear = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((after_clear['total_shopping'], after_clear['total_bills']), (Decimal('5500.00'), 2))
        self.assertEqual((after_clear['active_coins'], after_clear['current_coin_value'], after_clear['current_reward_value']), (0, Decimal('0.00'), Decimal('0.00')))

        next_bill, _ = self.create(price='2000.00')
        after_next = get_customer_coin_summary(self.customer, self.shop)
        self.assertEqual((next_bill.coins_earned, next_bill.cumulative_shopping_after), (20, Decimal('7500.00')))
        self.assertEqual((after_next['active_coins'], after_next['current_coin_value'], after_next['current_reward_value']), (20, Decimal('10.00'), Decimal('200.00')))
        self.assertEqual(after_next['total_bills'], 3)

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
        response = self.client.post(reverse('shops:clear_customer_coins', args=[other_customer.pk]), {'idempotency_key': uuid4(), 'confirm_redemption': 'yes', 'reward_description': 'Unauthorized item'})
        self.assertEqual(response.status_code, 302)
        other_wallet.refresh_from_db()
        self.assertEqual(other_wallet.balance, 55)
        self.assertFalse(CoinRedemption.objects.exists())

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
