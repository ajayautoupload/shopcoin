"""Copy local media into the configured object store without changing DB paths."""
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.core.files.storage import default_storage


class Command(BaseCommand):
    help = 'Copy existing local media to configured S3-compatible storage, keeping its current relative path.'

    def handle(self, *args, **options):
        if not getattr(settings, 'MEDIA_STORAGE_ENABLED', False):
            raise CommandError('Configure the permanent object storage environment variables before syncing media.')

        source_root = Path(settings.MEDIA_ROOT).resolve()
        if not source_root.is_dir():
            self.stdout.write('No local media directory exists; nothing to sync.')
            return

        copied = skipped = missing = 0
        for source in source_root.rglob('*'):
            if not source.is_file():
                continue
            resolved = source.resolve()
            if not resolved.is_relative_to(source_root):
                self.stderr.write(f'Skipped path outside media root: {source.name}')
                skipped += 1
                continue
            name = resolved.relative_to(source_root).as_posix()
            if default_storage.exists(name):
                skipped += 1
                continue
            try:
                with resolved.open('rb') as source_handle:
                    # _save preserves the exact key referenced by existing DB rows.
                    default_storage._save(name, File(source_handle, name=Path(name).name))
            except OSError:
                missing += 1
                self.stderr.write(f'Could not read local media file: {name}')
                continue
            copied += 1

        self.stdout.write(self.style.SUCCESS(
            f'Media sync complete. Copied: {copied}; already present/skipped: {skipped}; unreadable: {missing}. '
            'Local files were retained.'
        ))
