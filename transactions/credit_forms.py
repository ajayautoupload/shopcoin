from decimal import Decimal

from django import forms

from accounts.models import CustomerProfile
from .models import Bill


class CreditCreateForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=CustomerProfile.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}))
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}))
    description = forms.CharField(required=False, max_length=500, widget=forms.TextInput(attrs={'class': 'form-control'}))
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    reference = forms.CharField(required=False, max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    bill = forms.ModelChoiceField(queryset=Bill.objects.none(), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, shop, **kwargs):
        super().__init__(*args, **kwargs)
        customers = CustomerProfile.objects.filter(connected_shop=shop, is_deleted=False, user__is_active=True, user__profile__role='CUSTOMER', user__profile__is_deleted=False).select_related('user').order_by('user__first_name', 'user__last_name')
        self.fields['customer'].queryset = customers
        self.fields['bill'].queryset = Bill.objects.filter(shop=shop, customer__in=customers).order_by('-issued_at')
        self.fields['bill'].label = 'Existing bill (optional)'


class CreditPaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}))
    payment_reference = forms.UUIDField(widget=forms.HiddenInput())
