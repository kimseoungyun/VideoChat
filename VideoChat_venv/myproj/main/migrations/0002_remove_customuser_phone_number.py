# Generated by Django 5.1.7 on 2025-03-28 19:54

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customuser',
            name='phone_number',
        ),
    ]
