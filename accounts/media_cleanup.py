"""Delete replaced or removed uploads only after their final DB reference ends."""

from django.apps import apps
from django.db import transaction
from django.db.models import FileField
from django.db.models.signals import post_delete, post_save, pre_save


def _file_fields(model):
    return [field for field in model._meta.concrete_fields if isinstance(field, FileField)]


def _is_referenced(name, storage, using):
    if not name:
        return False
    for model in apps.get_models():
        for field in _file_fields(model):
            if field.storage == storage and model._base_manager.using(using).filter(**{field.name: name}).exists():
                return True
    return False


def _delete_if_unreferenced(name, storage, using):
    if name and not _is_referenced(name, storage, using):
        storage.delete(name)


def _capture_previous_files(sender, instance, using, **kwargs):
    if not instance.pk or not _file_fields(sender):
        instance._previous_media_names = {}
        return
    old = sender._base_manager.using(using).filter(pk=instance.pk).first()
    instance._previous_media_names = {
        field.name: getattr(old, field.name).name
        for field in _file_fields(sender)
        if old and getattr(old, field.name)
    }


def _cleanup_replaced_files(sender, instance, using, **kwargs):
    previous = getattr(instance, '_previous_media_names', {})
    for field in _file_fields(sender):
        old_name = previous.get(field.name)
        new_name = getattr(instance, field.name).name if getattr(instance, field.name) else ''
        if old_name and old_name != new_name:
            storage = field.storage
            transaction.on_commit(lambda name=old_name, store=storage: _delete_if_unreferenced(name, store, using), using=using)


def _cleanup_deleted_files(sender, instance, using, **kwargs):
    for field in _file_fields(sender):
        file_value = getattr(instance, field.name)
        if file_value and file_value.name:
            name, storage = file_value.name, field.storage
            transaction.on_commit(lambda name=name, store=storage: _delete_if_unreferenced(name, store, using), using=using)


pre_save.connect(_capture_previous_files, dispatch_uid='shopcoin.capture_previous_media')
post_save.connect(_cleanup_replaced_files, dispatch_uid='shopcoin.cleanup_replaced_media')
post_delete.connect(_cleanup_deleted_files, dispatch_uid='shopcoin.cleanup_deleted_media')
