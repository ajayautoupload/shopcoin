from django.conf import settings
from django.db import models


class InAppNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shopcoin_notifications')
    event_key = models.CharField(max_length=140, unique=True, null=True, blank=True, editable=False)
    redemption_request = models.ForeignKey(
        'wallet.CoinRedemptionRequest', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='notifications',
    )
    title = models.CharField(max_length=180)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
