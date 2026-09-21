import logging

from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import ApplicationDocument


logger = logging.getLogger(__name__)


def delete_stored_file(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.exception('Could not delete stored application document %s.', name)


@receiver(pre_save, sender=ApplicationDocument)
def delete_replaced_document_file(sender, instance, **kwargs):
    if not instance.pk:
        return

    previous = sender.objects.filter(pk=instance.pk).only('file').first()

    if previous and previous.file and previous.file.name != instance.file.name:
        storage = previous.file.storage
        name = previous.file.name
        transaction.on_commit(lambda: delete_stored_file(storage, name))


@receiver(post_delete, sender=ApplicationDocument)
def delete_document_file(sender, instance, **kwargs):
    if not instance.file:
        return

    storage = instance.file.storage
    name = instance.file.name
    transaction.on_commit(lambda: delete_stored_file(storage, name))
