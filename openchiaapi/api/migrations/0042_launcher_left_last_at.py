# Generated by Django 3.2.6 on 2022-03-17 10:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0041_launcher_joined_last_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='launcher',
            name='left_last_at',
            field=models.DateTimeField(default=None, null=True),
        ),
    ]