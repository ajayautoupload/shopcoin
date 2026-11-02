import django.db.models.deletion
from django.db import migrations, models


def connect_existing_ledger_bills(apps, schema_editor):
    Bill = apps.get_model('transactions', 'Bill')
    CoinLedger = apps.get_model('wallet', 'CoinLedger')
    database = schema_editor.connection.alias
    bills = {bill.bill_number: bill.pk for bill in Bill.objects.using(database).all()}
    for entry in CoinLedger.objects.using(database).exclude(transaction_reference='').iterator():
        bill_id = bills.get(entry.transaction_reference)
        if bill_id:
            CoinLedger.objects.using(database).filter(pk=entry.pk).update(bill_id=bill_id)


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0003_bill_status_and_ledger_bill_reference'),
        ('wallet', '0006_source_aware_website_engagement'),
    ]

    operations = [
        migrations.AddField(
            model_name='coinledger',
            name='bill',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coin_ledger_entries', to='transactions.bill'),
        ),
        migrations.RunPython(connect_existing_ledger_bills, migrations.RunPython.noop),
    ]
