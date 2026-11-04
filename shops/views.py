from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from accounts.decorators import shopkeeper_required
from accounts.forms import ShopkeeperCustomerForm, ShopkeeperProfileForm
from accounts.models import CustomerProfile
from offers.models import ShopAd
from .forms import ProductForm, ShopAdForm, ShopForm
from .models import Product, Shop
from accounts.services import create_customer_for_shopkeeper
from .access import get_current_shopkeeper_shop, is_approved_shop
from django.utils import timezone
from decimal import Decimal
from transactions.models import Bill
from uuid import uuid4
from django.core.exceptions import ValidationError
from wallet.models import CoinRedemption, CoinRule
from wallet.services import get_customer_coin_summary, redeem_customer_coins
from transactions.models import Credit, CreditPayment
from transactions.credit_forms import CreditCreateForm, CreditPaymentForm
from transactions.credit_services import create_credit, receive_credit_payment, reverse_bill_payment, reverse_credit_payment


@shopkeeper_required
def dashboard(request):
    shop = get_current_shopkeeper_shop(request.user)
    products = Product.objects.filter(shop__owner=request.user).order_by('-created_at')[:4]
    ads = ShopAd.objects.filter(shop__owner=request.user).order_by('display_order', 'start_date', '-created_at')[:3]
    today = timezone.localdate()
    today_bills = shop.bills.filter(issued_at__date=today, status=Bill.Status.COMPLETED) if shop else None
    today_sales = today_bills.aggregate(amount=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField(max_digits=12, decimal_places=2)))['amount'] if shop else Decimal('0.00')
    coins_issued = today_bills.aggregate(coins=Coalesce(Sum('coins_earned'), Value(0)))['coins'] if shop else 0
    return render(request, 'shopkeeper/dashboard.html', {'shop': shop, 'products': products, 'ads': ads, 'today_sales': today_sales, 'coins_issued': coins_issued})


@shopkeeper_required
def credit_list(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        return render(request, 'shopkeeper/credits.html', {'shop': None, 'credits': Credit.objects.none()})
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    credits = Credit.objects.filter(shop=shop).select_related('customer__user', 'bill').prefetch_related('payments')
    if query:
        credits = credits.filter(Q(customer__user__first_name__icontains=query) | Q(customer__user__last_name__icontains=query) | Q(customer__phone__icontains=query) | Q(customer__user__username__icontains=query))
    if status in Credit.Status.values:
        credits = credits.filter(status=status)
    return render(request, 'shopkeeper/credits.html', {'shop': shop, 'credits': credits, 'search_query': query, 'selected_status': status, 'statuses': Credit.Status.choices})


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def credit_create(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None or not is_approved_shop(shop):
        messages.error(request, 'An approved shop is required to create credit.')
        return redirect('shops:dashboard')
    form = CreditCreateForm(request.POST or None, shop=shop)
    if request.method == 'POST' and form.is_valid():
        try:
            credit = create_credit(shopkeeper=request.user, shop=shop, customer_id=form.cleaned_data['customer'].pk, amount=form.cleaned_data['amount'], description=form.cleaned_data['description'], due_date=form.cleaned_data['due_date'], reference=form.cleaned_data['reference'], bill_id=form.cleaned_data['bill'].pk if form.cleaned_data['bill'] else None)
        except ValidationError as error:
            form.add_error(None, '; '.join(error.messages))
        else:
            messages.success(request, 'Credit recorded. No coins were awarded at creation.')
            return redirect('shops:credit_detail', credit_id=credit.pk)
    return render(request, 'shopkeeper/credit_form.html', {'form': form, 'shop': shop, 'page_title': 'Create Udhar / Credit'})


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def credit_detail(request, credit_id):
    shop = get_current_shopkeeper_shop(request.user)
    credit = get_object_or_404(Credit.objects.select_related('customer__user', 'bill').prefetch_related('payments__coin_ledger'), pk=credit_id, shop=shop)
    form = CreditPaymentForm(request.POST or None, initial={'payment_reference': uuid4()})
    if request.method == 'POST' and form.is_valid():
        try:
            payment, created = receive_credit_payment(shopkeeper=request.user, shop=shop, credit_id=credit.pk, amount=form.cleaned_data['amount'], payment_reference=form.cleaned_data['payment_reference'])
        except ValidationError as error:
            form.add_error(None, '; '.join(error.messages))
        else:
            messages.success(request, f'Payment ₹{payment.amount:.2f} recorded.' if created else 'This payment was already recorded; no duplicate coins were issued.')
            return redirect('shops:credit_detail', credit_id=credit.pk)
    credit.refresh_from_db()
    return render(request, 'shopkeeper/credit_detail.html', {'credit': credit, 'form': form})


@shopkeeper_required
@require_POST
def credit_payment_reverse(request, credit_id, payment_id):
    shop = get_current_shopkeeper_shop(request.user)
    try:
        reverse_credit_payment(actor=request.user, shop=shop, payment_id=payment_id)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, 'Payment reversed with a retained ledger record.')
    return redirect('shops:credit_detail', credit_id=credit_id)


@shopkeeper_required
@require_POST
def bill_payment_reverse(request, bill_id, payment_id):
    shop = get_current_shopkeeper_shop(request.user)
    try:
        reverse_bill_payment(actor=request.user, shop=shop, payment_id=payment_id)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, 'Bill payment reversed with an auditable credit and wallet ledger adjustment.')
    return redirect('shops:bill_detail', bill_id=bill_id)


@shopkeeper_required
def my_products(request):
    products = Product.objects.filter(shop__owner=request.user).select_related('shop').order_by('-created_at')
    return render(request, 'shopkeeper/products.html', {'products': products})


@shopkeeper_required
def product_create(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        messages.info(request, 'Create your shop profile before adding products.')
        return redirect('shops:shop_create')
    data = request.POST if request.method == 'POST' else None
    files = request.FILES if request.method == 'POST' else None
    form = ProductForm(data, files)
    if request.method == 'POST' and form.is_valid():
        product = form.save(commit=False)
        product.shop = shop
        product.save()
        messages.success(request, f'{product.name} was added to your products.')
        return redirect('shops:products')
    return render(request, 'shopkeeper/product_form.html', {'form': form, 'page_title': 'Add product'})


@shopkeeper_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, shop__owner=request.user)
    data = request.POST if request.method == 'POST' else None
    files = request.FILES if request.method == 'POST' else None
    form = ProductForm(data, files, instance=product)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'{product.name} was updated.')
        return redirect('shops:products')
    return render(request, 'shopkeeper/product_form.html', {'form': form, 'product': product, 'page_title': 'Edit product'})


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, shop__owner=request.user)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f'{name} was deleted.')
        return redirect('shops:products')
    return render(request, 'shopkeeper/product_confirm_delete.html', {'product': product})


@shopkeeper_required
def my_ads(request):
    ads = ShopAd.objects.filter(shop__owner=request.user).select_related('shop').order_by('display_order', 'start_date', '-created_at')
    return render(request, 'shopkeeper/ads.html', {'ads': ads})


@shopkeeper_required
def ad_create(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        messages.info(request, 'Create your shop profile before creating an ad.')
        return redirect('shops:shop_create')
    data = request.POST if request.method == 'POST' else None
    files = request.FILES if request.method == 'POST' else None
    form = ShopAdForm(data, files)
    if request.method == 'POST' and form.is_valid():
        ad = form.save(commit=False)
        ad.shop = shop
        ad.save()
        messages.success(request, f'{ad.title} was created.')
        return redirect('shops:ads')
    return render(request, 'shopkeeper/ad_form.html', {'form': form, 'page_title': 'Create shop ad'})


@shopkeeper_required
def ad_edit(request, pk):
    ad = get_object_or_404(ShopAd, pk=pk, shop__owner=request.user)
    data = request.POST if request.method == 'POST' else None
    files = request.FILES if request.method == 'POST' else None
    form = ShopAdForm(data, files, instance=ad)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'{ad.title} was updated.')
        return redirect('shops:ads')
    return render(request, 'shopkeeper/ad_form.html', {'form': form, 'ad': ad, 'page_title': 'Edit shop ad'})


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def ad_delete(request, pk):
    ad = get_object_or_404(ShopAd, pk=pk, shop__owner=request.user)
    if request.method == 'POST':
        title = ad.title
        ad.delete()
        messages.success(request, f'{title} was deleted.')
        return redirect('shops:ads')
    return render(request, 'shopkeeper/ad_confirm_delete.html', {'ad': ad})


@shopkeeper_required
@require_POST
def ad_toggle(request, pk):
    ad = get_object_or_404(ShopAd, pk=pk, shop__owner=request.user)
    ad.is_active = not ad.is_active
    ad.save(update_fields=('is_active', 'updated_at'))
    messages.success(request, f'{ad.title} is now {"active" if ad.is_active else "inactive"}.')
    return redirect('shops:ads')


@shopkeeper_required
def shop_form(request):
    shop = get_current_shopkeeper_shop(request.user)
    form = ShopForm(request.POST or None, request.FILES or None, instance=shop)
    if request.method == 'POST' and form.is_valid():
        shop = form.save(commit=False)
        if shop.pk is None:
            shop.owner = request.user
            shop.status = Shop.Status.PENDING
        shop.save()
        messages.success(request, 'Your shop details have been submitted for review.')
        return redirect('shops:dashboard')
    return render(request, 'shops/shop_form.html', {'form': form, 'shop': shop})


@shopkeeper_required
def shop_detail(request, slug):
    shop = get_object_or_404(Shop, slug=slug, owner=request.user)
    return render(request, 'shops/shop_form.html', {'form': ShopForm(instance=shop), 'shop': shop, 'read_only': True})


@shopkeeper_required
def customers(request):
    shop = get_current_shopkeeper_shop(request.user)
    connected_customers = CustomerProfile.objects.none()
    if shop:
        connected_customers = CustomerProfile.objects.filter(connected_shop=shop).select_related('user', 'user__profile').annotate(
            coin_balance=Coalesce('wallet__balance', Value(0)),
            total_spent=Coalesce(Sum('bills__total_amount', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED)), Decimal('0.00'), output_field=DecimalField(max_digits=12, decimal_places=2)),
            total_bills=Count('bills', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED), distinct=True),
            total_coins=Coalesce(Sum('bills__coins_earned', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED)), Value(0)),
        )
        query = request.GET.get('q', '').strip()
        if query:
            connected_customers = connected_customers.filter(
                Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) |
                Q(phone__icontains=query) | Q(user__username__icontains=query)
            )
        connected_customers = connected_customers.order_by('is_deleted', 'user__first_name', 'user__last_name')
    return render(request, 'shopkeeper/customers.html', {
        'shop': shop, 'connected_customers': connected_customers,
        'customer_count': shop.connected_customers.count() if shop else 0,
        'search_query': request.GET.get('q', '').strip(),
    })


@shopkeeper_required
def sales(request):
    shop = get_current_shopkeeper_shop(request.user)
    bills = Bill.objects.filter(shop=shop).select_related('customer__user').prefetch_related('items') if shop else Bill.objects.none()
    payment_status = request.GET.get('status', '')
    if payment_status in Bill.PaymentStatus.values:
        bills = bills.filter(payment_status=payment_status)
    return render(request, 'shopkeeper/sales.html', {'shop': shop, 'bills': bills, 'selected_status': payment_status, 'payment_statuses': Bill.PaymentStatus.choices})


@shopkeeper_required
def bills(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        messages.info(request, 'Create your shop profile before generating bills.')
        return redirect('shops:shop_create')
    query = request.GET.get('q', '').strip()
    customers = CustomerProfile.objects.filter(
        connected_shop=shop, is_deleted=False, user__is_active=True,
        user__profile__role='CUSTOMER', user__profile__is_deleted=False,
    ).select_related('user').annotate(
        coin_balance=Coalesce('wallet__balance', Value(0)),
        total_spent=Coalesce(Sum('bills__total_amount', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED)), Decimal('0.00'), output_field=DecimalField(max_digits=12, decimal_places=2)),
        total_bills=Count('bills', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED), distinct=True),
        total_coins=Coalesce(Sum('bills__coins_earned', filter=Q(bills__shop=shop, bills__status=Bill.Status.COMPLETED)), Value(0)),
    ).order_by('user__first_name', 'user__last_name')
    if query:
        customers = customers.filter(
            Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) |
            Q(phone__icontains=query) | Q(user__username__icontains=query)
        )
    return render(request, 'shopkeeper/bills.html', {'shop': shop, 'customers': customers, 'search_query': query})


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def create_bill_for_customer(request, customer_id):
    from uuid import uuid4
    from django.core.exceptions import ValidationError
    from transactions.forms import BillDetailsForm, BillItemFormSet
    from transactions.models import Bill
    from transactions.services import create_bill

    shop = get_current_shopkeeper_shop(request.user)
    if shop is None or not is_approved_shop(shop):
        messages.info(request, 'An approved shop is required to generate a bill.')
        return redirect('shops:dashboard')
    customer = get_object_or_404(
        CustomerProfile.objects.select_related('user'),
        pk=customer_id, connected_shop=shop, is_deleted=False,
        user__is_active=True, user__profile__role='CUSTOMER', user__profile__is_deleted=False,
    )
    active_tiers = set(CoinRule.objects.filter(shop=shop, is_active=True, purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00'))).values_list('purchase_amount', flat=True))
    has_active_coin_rule = active_tiers == {Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00')}

    if request.method == 'POST':
        form = BillDetailsForm(request.POST)
        item_formset = BillItemFormSet(request.POST, prefix='items', form_kwargs={'shop': shop})
        if form.is_valid() and item_formset.is_valid():
            active_forms = [line for line in item_formset.forms if line.cleaned_data and not line.cleaned_data.get('DELETE')]
            subtotal = sum((line.cleaned_data['unit_price'] * line.cleaned_data['quantity'] for line in active_forms), Decimal('0.00'))
            discount = form.cleaned_data.get('discount') or Decimal('0.00')
            if discount > subtotal:
                form.add_error('discount', 'Discount cannot be greater than the subtotal.')
            else:
                bill = None
                try:
                    bill, created = create_bill(
                        shopkeeper=request.user, shop=shop, customer_id=customer.pk,
                        idempotency_key=form.cleaned_data['idempotency_key'],
                        discount=discount, items=[line.cleaned_data for line in active_forms],
                        payment_received=form.cleaned_data.get('payment_received'),
                    )
                except IntegrityError:
                    bill = Bill.objects.filter(
                        idempotency_key=form.cleaned_data['idempotency_key'], shop=shop, customer=customer,
                    ).first()
                    if bill is None:
                        raise
                    created = False
                except ValidationError as error:
                    for message in error.messages:
                        form.add_error(None, message)
                else:
                    messages.success(request, f'Bill {bill.bill_number} was generated successfully.')
                    return redirect('shops:bill_detail', bill_id=bill.pk)
                if bill is not None:
                    messages.info(request, 'This bill was already submitted. No additional coins were added.')
                    return redirect('shops:bill_detail', bill_id=bill.pk)
    else:
        form = BillDetailsForm(initial={'idempotency_key': uuid4(), 'discount': Decimal('0.00')})
        item_formset = BillItemFormSet(prefix='items', form_kwargs={'shop': shop})
    return render(request, 'shopkeeper/bill_form.html', {
        'shop': shop, 'customer': customer, 'form': form, 'item_formset': item_formset,
        'has_active_coin_rule': has_active_coin_rule,
    })


@shopkeeper_required
def bill_detail(request, bill_id):
    shop = get_current_shopkeeper_shop(request.user)
    bill = get_object_or_404(Bill.objects.select_related('shop', 'customer__user', 'coin_rule').prefetch_related('items', 'payments__coin_ledger', 'payments__reversal', 'credits__payments__coin_ledger', 'credits__payments__reversal'), pk=bill_id, shop=shop)
    payment_history = [{'payment': payment, 'is_credit_payment': False} for payment in bill.payments.all()]
    for credit in bill.credits.all():
        payment_history.extend({'payment': payment, 'is_credit_payment': True} for payment in credit.payments.all())
    payment_history.sort(key=lambda item: item['payment'].created_at)
    return render(request, 'shopkeeper/bill_detail.html', {'bill': bill, 'audience': 'shopkeeper', 'payment_history': payment_history})


@shopkeeper_required
def customer_detail(request, customer_id):
    shop = get_current_shopkeeper_shop(request.user)
    customer = get_object_or_404(
        CustomerProfile.objects.select_related('user'), pk=customer_id,
        connected_shop=shop, is_deleted=False, user__is_active=True,
        user__profile__role='CUSTOMER', user__profile__is_deleted=False,
    )
    bills = Bill.objects.filter(shop=shop, customer=customer).prefetch_related('items')
    coin_summary = get_customer_coin_summary(customer, shop)
    wallet = coin_summary['wallet']
    summary = {
        **coin_summary,
        'total_spent': coin_summary['total_shopping'],
        'total_bills': coin_summary['total_bills'],
        'total_coins': coin_summary['active_coins'],
        'current_coin_value': coin_summary['current_coin_value'],
        'current_reward_value': coin_summary['current_reward_value'],
    }
    redemptions = CoinRedemption.objects.filter(customer=customer, shop=shop).select_related('redeemed_by').order_by('-redeemed_at')
    return render(request, 'shopkeeper/customer_detail.html', {
        'shop': shop, 'customer': customer, 'bills': bills, 'summary': summary, 'wallet': wallet,
        'redemptions': redemptions, 'redemption_key': uuid4(),
    })


@shopkeeper_required
@require_POST
def clear_customer_coins(request, customer_id):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        messages.error(request, 'Create your shop profile before redeeming customer coins.')
        return redirect('shops:dashboard')
    try:
        redemption, created = redeem_customer_coins(
            shopkeeper=request.user,
            shop=shop,
            customer_id=customer_id,
            idempotency_key=request.POST.get('idempotency_key'),
            confirmed=request.POST.get('confirm_redemption') == 'yes',
            reward_description=request.POST.get('reward_description', ''),
        )
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        if created:
            messages.success(request, f'{redemption.coins_redeemed} coins redeemed for ₹{redemption.reward_value}.')
        else:
            messages.info(request, 'This redemption was already recorded; no additional coins were cleared.')
    return redirect('shops:customer_detail', customer_id=customer_id)


@shopkeeper_required
def coin_rules(request):
    shop = get_current_shopkeeper_shop(request.user)
    rules = CoinRule.objects.filter(shop=shop, is_active=True, purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00'))) if shop else CoinRule.objects.none()
    ranges = {Decimal('1000.00'): '₹1,000–₹4,999', Decimal('5000.00'): '₹5,000–₹9,999', Decimal('10000.00'): '₹10,000+'}
    rule_slabs = [{'rule': rule, 'range': ranges[rule.purchase_amount]} for rule in rules if rule.purchase_amount in ranges]
    return render(request, 'shared/coin_rules.html', {
        'shop': shop, 'rules': rules,
        'rule_slabs': rule_slabs,
        'audience': 'shopkeeper',
    })


@shopkeeper_required
@require_http_methods(['GET', 'POST'])
def customer_create(request):
    shop = get_current_shopkeeper_shop(request.user)
    if shop is None:
        messages.info(request, 'Create your shop profile before adding customers.')
        return redirect('shops:shop_create')
    if not is_approved_shop(shop):
        messages.info(request, 'Your shop must be approved before you can add customers.')
        return redirect('shops:customers')
    form = ShopkeeperCustomerForm(request.POST or None, request.FILES or None, shop=shop)
    if request.method == 'POST' and form.is_valid():
        try:
            customer = create_customer_for_shopkeeper(request.user, shop, form.cleaned_data)
        except IntegrityError:
            existing = CustomerProfile.objects.filter(phone=form.cleaned_data['phone'], is_deleted=False).select_related('connected_shop').first()
            if existing and existing.connected_shop_id == shop.pk:
                form.add_error('phone', 'This customer is already registered with your shop.')
            else:
                form.add_error('phone', 'This mobile number is already registered with another shop.')
        else:
            messages.success(request, f'{customer.user.get_full_name()} was added to {shop.name}.')
            return redirect('shops:customers')
    return render(request, 'shopkeeper/customer_form.html', {'form': form, 'shop': shop})


@shopkeeper_required
def placeholder(request, title):
    return render(request, 'shared/placeholder.html', {'title': title})


@shopkeeper_required
def profile(request):
    instance = request.user.shopkeeper_profile
    form = ShopkeeperProfileForm(request.POST or None, instance=instance, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been updated.')
        return redirect('shops:profile')
    return render(request, 'accounts/profile.html', {'form': form, 'profile_title': 'Your profile'})
