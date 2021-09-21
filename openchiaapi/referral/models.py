from django.db import models


class Referral(models.Model):
    launcher = models.OneToOneField('api.Launcher', on_delete=models.CASCADE)
    referer = models.ForeignKey('api.Launcher', on_delete=models.CASCADE, related_name="referrals")
    total_income = models.BigIntegerField(verbose_name="Total Income")
    active = models.BooleanField(default=True)
    active_date = models.DateTimeField()
