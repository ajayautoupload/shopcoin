"""Resolve media storage settings without coupling them to database settings."""


MEDIA_STORAGE_ENV_VARS = (
    'AWS_STORAGE_BUCKET_NAME',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_S3_ENDPOINT_URL',
    'AWS_S3_CUSTOM_DOMAIN',
)


def resolve_media_storage(environ, *, debug):
    values = {name: environ.get(name, '').strip() for name in MEDIA_STORAGE_ENV_VARS}
    enabled = all(values.values())
    partial = any(values.values()) and not enabled
    missing = tuple(name for name, value in values.items() if not value)
    temporary_fallback = not debug and not enabled
    return {
        'enabled': enabled,
        'partial': partial,
        'missing': missing,
        'temporary_fallback': temporary_fallback,
        'backend': (
            'storages.backends.s3.S3Storage'
            if enabled else 'django.core.files.storage.FileSystemStorage'
        ),
        'bucket': values['AWS_STORAGE_BUCKET_NAME'],
        'endpoint_url': values['AWS_S3_ENDPOINT_URL'] or None,
        'custom_domain': values['AWS_S3_CUSTOM_DOMAIN'] or None,
        'region_name': environ.get('AWS_S3_REGION_NAME', '').strip() or 'auto',
        'querystring_auth': environ.get('AWS_QUERYSTRING_AUTH', 'false').strip().lower() == 'true',
    }
