from django import forms
from accounts.models import phone_validator
from offers.models import ShopAd
from .models import Product, Shop


class ShopForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = ('name', 'description', 'logo', 'phone', 'email', 'address', 'city', 'state', 'pincode')
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Enter your shop name.')
        return name


class CustomerLookupForm(forms.Form):
    phone = forms.CharField(max_length=16, validators=[phone_validator], label='Customer mobile number')


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('name', 'image', 'price', 'discount_price', 'category', 'sizes', 'colors', 'description', 'stock', 'is_new', 'is_active')
        widgets = {'description': forms.Textarea(attrs={'rows': 4}), 'price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}), 'discount_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'})}


class ShopAdForm(forms.ModelForm):
    class Meta:
        model = ShopAd
        fields = ('image', 'title', 'description', 'offer_text', 'start_date', 'end_date', 'is_active')
        widgets = {'description': forms.TextInput(), 'start_date': forms.DateInput(attrs={'type': 'date'}), 'end_date': forms.DateInput(attrs={'type': 'date'})}
