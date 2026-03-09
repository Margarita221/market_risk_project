from django.db import models


class Instrument(models.Model):
    ticker = models.CharField(max_length=20, unique=True, verbose_name='Тикер')
    name = models.CharField(max_length=200, verbose_name='Наименование')
    instrument_type = models.CharField(max_length=50, verbose_name='Тип инструмента')
    currency = models.CharField(max_length=10, verbose_name='Валюта')
    current_price = models.DecimalField(max_digits=15, decimal_places=4, verbose_name='Текущая цена')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')

    class Meta:
        db_table = 'instrument'
        verbose_name = 'Финансовый инструмент'
        verbose_name_plural = 'Финансовые инструменты'
        ordering = ['ticker']

    def __str__(self):
        return f'{self.ticker} - {self.name}'