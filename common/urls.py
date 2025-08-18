from django.urls import path

from . import views

urlpatterns = [
    path("health-check/", views.health_check, name="health-check"),
    path("upload-urls/", views.get_upload_urls, name="get-upload-urls"),
    path("get-presigned-url/", views.get_presigned_url, name="get-presigned-url"),
    path("get-presigned-read-url/", views.get_presigned_read_url, name="get-presigned-read-url"),
    path("get-presigned-read-urls-batch/", views.get_presigned_read_urls_batch, name="get-presigned-read-urls-batch"),
    path("local-upload/", views.local_file_upload, name="local-upload"),
    path("search/global/", views.global_search, name="global-search"),
]
