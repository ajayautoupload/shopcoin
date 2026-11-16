from django.conf import settings
from django.db import models


class InAppNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shopcoin_notifications')
    title = models.CharField(max_length=180)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
