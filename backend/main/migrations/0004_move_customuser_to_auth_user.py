from django.db import migrations

FIELDS = ('password', 'last_login', 'is_superuser', 'first_name', 'last_name', 'email',
          'is_staff', 'is_active', 'date_joined')


def move_accounts(apps, schema_editor):
    """CustomUser was never AUTH_USER_MODEL, so its rows could not sign in.
    Keep them as real accounts (password hashes included) before dropping the table."""
    CustomUser = apps.get_model('main', 'CustomUser')
    User = apps.get_model('auth', 'User')
    for legacy in CustomUser.objects.all():
        if not User.objects.filter(username=legacy.username).exists():
            User.objects.create(username=legacy.username, **{f: getattr(legacy, f) for f in FIELDS})


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0003_delete_room'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(move_accounts, migrations.RunPython.noop),
        migrations.DeleteModel(name='CustomUser'),
    ]
