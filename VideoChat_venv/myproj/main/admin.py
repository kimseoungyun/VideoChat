from django.contrib import admin

# Register your models here.
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Room

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active')
    # UserAdmin.fieldsets + 
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login',)}),
    )
    # UserAdmin.add_fieldsets + 
    add_fieldsets = (
        (None, {'fields': ('username', 'email', 'password1', 'password2')}),
    )

admin.site.register(CustomUser,CustomUserAdmin)
admin.site.register(Room)