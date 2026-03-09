from django.contrib import admin
from .models import Instrument


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'name', 'instrument_type', 'currency', 'current_price', 'created_at')
    search_fields = ('ticker', 'name')
    list_filter = ('instrument_type', 'currency')
