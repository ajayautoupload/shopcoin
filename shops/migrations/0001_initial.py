import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='Shop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=180)),
                ('slug', models.SlugField(blank=True, max_length=200, unique=True)),
                ('description', models.TextField(blank=True)),
                ('logo', models.ImageField(blank=True, upload_to='shops/logos/')),
                ('phone', models.CharField(max_length=16, validators=[django.core.validators.RegexValidator(r'^\+?[0-9]{10,15}$', 'Enter a valid phone number (10–15 digits, optional leading +).')])),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('address', models.CharField(max_length=255)),
                ('city', models.CharField(max_length=100)),
                ('state', models.CharField(max_length=100)),
                ('pincode', models.CharField(max_length=10, validators=[django.core.validators.RegexValidator(r'^[0-9A-Za-z -]{4,10}$', 'Enter a valid postal code.')])),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('SUSPENDED', 'Suspended')], db_index=True, default='PENDING', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shops', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('name',), 'indexes': [models.Index(fields=['owner', 'status'], name='shops_shop_owner_i_87d7ad_idx')]},
        ),
    ]
