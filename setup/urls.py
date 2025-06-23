from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from delivery.views import landing_page, chatbot, user_data, search_client, business, products, types, orders, addons, menu_delivery, print_order, ToggleActiveView, DeliveryFeeView, promo

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path('', landing_page, name='landing_page'),

    path('admin/', admin.site.urls),

    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/me/', user_data, name='user_profile'),

    path('update_business', business, name='business'),
    
    path('product_list', products, name='product_list'),
    path('product_register', products, name='product_register'),
    path('product_edit/<int:id>/', products, name='product_edit'),

    path('promotion_list', promo, name='promotion_list'),
    path('promotion_register', promo, name='promotion_register'),
    path('promotion_edit/<int:id>/', promo, name='promotion_edit'),

    path('types_list', types, name='types_list'),
    path('types_register', types, name='types_register'),
    path('types_edit/<int:id>/', types, name='types_edit'),

    path('addons_list', addons, name='addons_list'),
    path('addons_register', addons, name='addons_register'),
    path('addons_edit/<int:id>/', addons, name='addons_edit'),

    path('orders_list', orders, name='orders_list'),
    path('orders_detail/<int:id>/', orders, name='orders_detail'),
    path('orders_edit/<int:id>/', orders, name='orders_edit'),
    path('orders_print/<int:id>/', print_order, name='print_order'),

    path('<str:model_name>/<int:id>/toggle-active/', ToggleActiveView.as_view(), name='toggle-active'),


    path('chatbot/<str:estab_url>', chatbot, name='chatbot'),

    path('<str:estab_url>', menu_delivery, name='menu_delivery'),
    
    path('search_client/<str:estab_url>/<str:phone>', search_client, name='search_client'),
    path('search_client/<str:estab_url>', search_client, name='search_client'),
    
    path('api/endereco/', DeliveryFeeView.as_view(), name='delivery_fee'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
