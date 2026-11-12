from decimal import Decimal

from django import forms

from accounts.models import CustomerProfile
from .models import Bill


class CustomerBillSelect(forms.Select):
    """Expose bill ownership to the form's small client-side filter."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        bill = getattr(value, 'instance', None)
        if bill is not None:
            option['attrs']['data-customer-id'] = str(bill.customer_id)
        return option


class CreditCreateForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=CustomerProfile.objects.none(), widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_customer'}))
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}))
    description = forms.CharField(required=False, max_length=500, widget=forms.TextInput(attrs={'class': 'form-control'}))
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    reference = forms.CharField(required=False, max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    bill = forms.ModelChoiceField(queryset=Bill.objects.none(), required=False, widget=CustomerBillSelect(attrs={'class': 'form-select', 'id': 'id_bill'}))

    def __init__(self, *args, shop, **kwargs):
        super().__init__(*args, **kwargs)
        customers = CustomerProfile.objects.filter(connected_shop=shop, is_deleted=False, user__is_active=True, user__profile__role='CUSTOMER', user__profile__is_deleted=False).select_related('user').order_by('user__first_name', 'user__last_name')
        self.fields['customer'].queryset = customers
        self.fields['customer'].label_from_instance = lambda customer: f"{' '.join(customer.user.get_full_name().split()) or 'Customer'} · {customer.phone}"
        bills = Bill.objects.filter(shop=shop, customer__in=customers).select_related('customer', 'customer__user').order_by('-issued_at')
        self.fields['bill'].label_from_instance = lambda bill: f'Bill {bill.bill_number} · {bill.issued_at:%d %b %Y} · ₹{Decimal(bill.total_amount):.2f}'
        # On POST, only accept a bill that belongs to the selected customer.
        # On GET, render the shop's bills and filter the options in the browser.
        if self.is_bound:
            selected_customer_id = self.data.get(self.add_prefix('customer'))
            bills = bills.filter(customer_id=selected_customer_id) if selected_customer_id else bills.none()
        self.fields['bill'].queryset = bills
        self.fields['bill'].label = 'Existing bill (optional)'


class CreditPaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}))
    payment_reference = forms.UUIDField(widget=forms.HiddenInput())
