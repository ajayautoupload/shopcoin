from django.urls import path
from . import views

app_name = 'core'
urlpatterns = [path('', views.home, name='home'), path('preferences/language/', views.set_language_preference, name='set_language_preference'), path('preferences/translations/', views.translation_catalogue, name='translation_catalogue')]
