from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notification_count(context):
    user = context.get('user')
    if not getattr(user, 'is_authenticated', False):
        return 0
    profile = getattr(user, 'profile', None)
    if profile is None or profile.role != 'CUSTOMER':
        return 0
    return user.shopcoin_notifications.filter(read_at__isnull=True).count()
