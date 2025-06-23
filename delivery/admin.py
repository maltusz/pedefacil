from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Estabelecimento, UserProfile, DeliveryRange

@admin.register(DeliveryRange)
class DeliveryRangeAdmin(admin.ModelAdmin):
    list_display = ['estabelecimento', 'min_distance', 'max_distance', 'delivery_fee']
    list_filter = ['estabelecimento']
    search_fields = ['estabelecimento__estabelecimento_nome']

# Inline para UserProfile
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Usuário'
    fields = ['estabelecimento']
    extra = 1  # Exige 1 UserProfile por usuário

# Custom UserAdmin com inline
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]

# Re-registrar o modelo User
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Registrar outros modelos
@admin.register(Estabelecimento)
class EstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ['estabelecimento_nome', 'estabelecimento_cnpj', 'estabelecimento_proprietario', 'estabelecimento_cidade']
    search_fields = ['estabelecimento_nome', 'estabelecimento_cnpj']
    list_filter = ['estabelecimento_cidade']

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'estabelecimento']
    search_fields = ['user__username', 'estabelecimento__nome']
    list_filter = ['estabelecimento']
