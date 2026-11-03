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
        fields = ('image', 'title', 'description', 'offer_text', 'cta_text', 'cta_url', 'display_order', 'start_date', 'end_date', 'is_active')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'cta_url': forms.URLInput(attrs={'placeholder': 'https://example.com/shop'}),
            'display_order': forms.NumberInput(attrs={'min': '0', 'step': '1'}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        help_texts = {
            'image': 'Wide images around 16:6 or 3:1 work best.',
            'display_order': 'Lower numbers are shown first.',
            'cta_text': 'Optional button label. Add a destination link too.',
            'cta_url': 'Optional destination for the banner button.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['display_order'].required = False
        self.fields['display_order'].initial = 0

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('display_order') is None:
            cleaned['display_order'] = 0
        if cleaned.get('cta_text') and not cleaned.get('cta_url'):
            self.add_error('cta_url', 'Add a destination link when you provide button text.')
        if cleaned.get('cta_url') and not cleaned.get('cta_text'):
            self.add_error('cta_text', 'Add button text when you provide a destination link.')
        return cleaned
