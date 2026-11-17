from decimal import Decimal

from django import forms
from django.forms import formset_factory

from shops.models import Product
from wallet.models import CoinRedemption
from .models import Bill


class BillDetailsForm(forms.Form):
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)
    payment_received = forms.DecimalField(
        label='Payment received (₹)', required=False, initial=Decimal('0.00'), min_value=Decimal('0.00'),
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'value': '0.00', 'id': 'id_payment_received'}),
    )
    discount = forms.DecimalField(
        label='Bill discount', required=False, initial=Decimal('0.00'), min_value=Decimal('0.00'),
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'value': '0'}),
    )
    redemption_coins = forms.IntegerField(
        required=False, min_value=0, initial=0, label='Apply ShopCoin redemption',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1', 'value': '0', 'id': 'id_redemption_coins'}),
    )
    redemption_to_apply = forms.ModelChoiceField(queryset=CoinRedemption.objects.none(), required=False, label='Apply confirmed coins from an earlier bill')

    def __init__(self, *args, shop, customer, available_redemption_coins=0, allow_redemption_apply=False, **kwargs):
        super().__init__(*args, **kwargs)
        if available_redemption_coins:
            self.fields['redemption_coins'].max_value = available_redemption_coins
            self.fields['redemption_coins'].widget.attrs['max'] = available_redemption_coins
        else:
            self.fields.pop('redemption_coins')
        if allow_redemption_apply:
            self.fields['redemption_to_apply'].queryset = CoinRedemption.objects.filter(
                shop=shop, customer=customer, applied_bill__isnull=True,
                source_bill__isnull=False, source_bill__status=Bill.Status.COMPLETED,
                status=CoinRedemption.Status.COMPLETED,
            ).order_by('-redeemed_at')
        else:
            self.fields.pop('redemption_to_apply')


class BillEditForm(forms.Form):
    reason = forms.CharField(
        required=True, max_length=500, label='Edit reason',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': '500'}),
    )
    discount = forms.DecimalField(
        required=False, initial=Decimal('0.00'), min_value=Decimal('0.00'),
        max_digits=12, decimal_places=2, label='Bill discount (₹)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
    )


class BillItemForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(), required=False, label='Catalog product',
        widget=forms.Select(attrs={'class': 'form-select bill-product-select'}),
    )
    product_name = forms.CharField(
        max_length=180, required=False, label='Product name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product name'}),
    )
    quantity = forms.IntegerField(
        min_value=1, initial=1, label='Qty',
        widget=forms.NumberInput(attrs={'class': 'form-control bill-quantity', 'min': '1', 'step': '1', 'value': '1'}),
    )
    unit_price = forms.DecimalField(
        required=False, min_value=Decimal('0.00'), max_digits=10, decimal_places=2, label='Price',
        widget=forms.NumberInput(attrs={'class': 'form-control bill-price', 'min': '0', 'step': '0.01', 'placeholder': '0.00'}),
    )

    def __init__(self, *args, shop, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(shop=shop, is_active=True).order_by('name')

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        product_name = (cleaned.get('product_name') or '').strip()
        unit_price = cleaned.get('unit_price')
        if product:
            if not product_name:
                cleaned['product_name'] = product.name
            if unit_price is None:
                cleaned['unit_price'] = product.effective_price
        elif not product_name:
            raise forms.ValidationError('Select a catalog product or enter a product name.')
        if cleaned.get('unit_price') is None:
            self.add_error('unit_price', 'Enter a price for this product.')
        return cleaned


BillItemFormSet = formset_factory(BillItemForm, extra=1, min_num=1, validate_min=True, max_num=40, validate_max=True, can_delete=True)
