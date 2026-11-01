from django import forms
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction
from .models import CustomerProfile, ShopkeeperProfile, UserProfile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    @transaction.atomic
    def save(self, role, commit=True):
        if role != UserProfile.Role.SHOPKEEPER:
            raise ValueError('Customer accounts must be created by an approved shopkeeper.')
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data.get('last_name', '')
        if commit:
            user.save()
            UserProfile.objects.create(user=user, role=role)
            ShopkeeperProfile.objects.create(user=user, phone=self.cleaned_data['phone'])
        return user


class ShopkeeperRegistrationForm(RegistrationForm):
    phone = forms.CharField(max_length=16, validators=[ShopkeeperProfile._meta.get_field('phone').validators[0]])
    business_name = forms.CharField(max_length=160, required=False)

    class Meta(RegistrationForm.Meta):
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'business_name', 'password1', 'password2')

    @transaction.atomic
    def save(self, role=UserProfile.Role.SHOPKEEPER, commit=True):
        user = super().save(role=role, commit=commit)
        if commit:
            ShopkeeperProfile.objects.filter(user=user).update(business_name=self.cleaned_data['business_name'])
        return user


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Mobile number',
        help_text='Customers use their registered mobile number. Shopkeepers use their username.',
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'inputmode': 'tel'}),
    )


class CustomerLoginForm(forms.Form):
    mobile_number = forms.CharField(
        label='Mobile Number',
        max_length=16,
        validators=[CustomerProfile._meta.get_field('phone').validators[0]],
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg', 'inputmode': 'tel',
            'autocomplete': 'tel', 'placeholder': 'Enter your mobile number',
        }),
    )
    password = forms.CharField(
        label='Password', strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg', 'autocomplete': 'current-password',
            'placeholder': 'Enter your password',
        }),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        mobile = cleaned.get('mobile_number')
        password = cleaned.get('password')
        if mobile and password:
            from .backends import MobileOrUsernameBackend
            self.user_cache = MobileOrUsernameBackend().authenticate_customer_mobile(mobile, password)
            if self.user_cache is None:
                raise forms.ValidationError('Mobile number or password is incorrect.')
        return cleaned

    def get_user(self):
        return self.user_cache


class ShopkeeperCustomerForm(forms.Form):
    name = forms.CharField(max_length=150, label='Customer name')
    phone = forms.CharField(max_length=16, validators=[CustomerProfile._meta.get_field('phone').validators[0]], label='Mobile number')
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), strip=False)
    confirm_password = forms.CharField(label='Confirm password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), strip=False)
    address = forms.CharField(max_length=255, required=False)
    image = forms.ImageField(required=False, label='Profile photo')

    def __init__(self, *args, shop, **kwargs):
        self.shop = shop
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if not name:
            raise forms.ValidationError('Enter the customer’s name.')
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        existing = CustomerProfile.objects.filter(phone=phone, is_deleted=False).select_related('connected_shop').first()
        if existing:
            if existing.connected_shop_id == self.shop.pk:
                raise forms.ValidationError('This customer is already registered with your shop.')
            raise forms.ValidationError('This mobile number is already registered with another shop.')
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm = cleaned.get('confirm_password')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')
        if password:
            first, _, last = cleaned.get('name', '').partition(' ')
            candidate = User(first_name=first, last_name=last, email=cleaned.get('email', ''))
            try:
                validate_password(password, user=candidate)
            except forms.ValidationError as error:
                self.add_error('password', error)
        return cleaned


class CustomerProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()

    class Meta:
        model = CustomerProfile
        fields = ('phone', 'image', 'address', 'city', 'state', 'pincode', 'notifications_enabled', 'privacy_show_name')

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name
        self.fields['email'].initial = user.email

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if phone and CustomerProfile.objects.filter(phone=phone, is_deleted=False).exclude(user=self.user).exists():
            raise forms.ValidationError('An account with this mobile number already exists.')
        return phone

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit:
            self.user.first_name = self.cleaned_data['first_name']
            self.user.last_name = self.cleaned_data['last_name']
            self.user.email = self.cleaned_data['email']
            self.user.save(update_fields=('first_name', 'last_name', 'email'))
        return profile


class ShopkeeperProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()

    class Meta:
        model = ShopkeeperProfile
        fields = ('phone', 'business_name', 'contact_email')

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name
        self.fields['email'].initial = user.email

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit:
            self.user.first_name = self.cleaned_data['first_name']
            self.user.last_name = self.cleaned_data['last_name']
            self.user.email = self.cleaned_data['email']
            self.user.save(update_fields=('first_name', 'last_name', 'email'))
        return profile


class NotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ('notifications_enabled',)


class PrivacySettingsForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ('privacy_show_name',)
