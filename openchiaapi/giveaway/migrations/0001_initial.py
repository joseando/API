# Generated by Django 3.2.6 on 2021-11-09 12:26

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('api', '0027_coinreward'),
    ]

    operations = [
        migrations.CreateModel(
            name='Giveaway',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('draw_datetime', models.DateTimeField(unique=True)),
                ('selected_number', models.IntegerField(null=True)),
                ('total_tickets', models.IntegerField()),
                ('prize_amount', models.BigIntegerField()),
                ('winner', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='api.launcher')),
            ],
        ),
        migrations.CreateModel(
            name='TicketsRound',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('estimated_size', models.BigIntegerField()),
                ('number_tickets', models.IntegerField()),
                ('tickets', models.JSONField()),
                ('giveaway', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='giveaway.giveaway')),
                ('launcher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api.launcher')),
            ],
        ),
    ]