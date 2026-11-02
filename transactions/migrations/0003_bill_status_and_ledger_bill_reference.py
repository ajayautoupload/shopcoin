from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0002_bill_cumulative_shopping_after'),
        ('wallet', '0006_source_aware_website_engagement'),
    ]

    operations = [
        migrations.AddField(
            model_name='bill',
            name='status',
            field=models.CharField(choices=[('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled'), ('REFUNDED', 'Refunded')], db_index=True, default='COMPLETED', max_length=12),
        ),
    ]
