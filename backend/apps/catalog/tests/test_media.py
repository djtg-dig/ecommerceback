from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductMedia
from apps.catalog.views import media_error_response
from apps.common.media import MediaStorageError, MediaStoragePermissionError, upload_to_cloudinary, validate_image


def image_file(width, height, image_format="PNG"):
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format=image_format)
    return SimpleUploadedFile(f"image.{image_format.lower()}", stream.getvalue(), content_type="application/octet-stream")


def test_product_image_is_verified_by_content_not_declared_mime_type():
    metadata = validate_image(image_file(800, 800), kind="product")
    assert metadata.media_type == "IMAGE"
    assert metadata.width == 800
    assert metadata.resource_type == "image"


def test_documents_and_too_small_images_are_rejected():
    document = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
    with pytest.raises(ValidationError):
        validate_image(document, kind="product")
    with pytest.raises(ValidationError):
        validate_image(image_file(799, 800), kind="product")


def test_video_cannot_be_primary_even_before_database_constraints():
    media = ProductMedia(media_type=ProductMedia.MediaType.VIDEO, resource_type="video", is_primary=True)
    with pytest.raises(ValidationError):
        media.clean()


def test_cloudinary_not_allowed_is_safe_storage_permission_error(monkeypatch, settings):
    from cloudinary.exceptions import NotAllowed
    import cloudinary.uploader

    settings.CLOUDINARY_ENABLED = True
    monkeypatch.setattr(cloudinary.uploader, "upload", lambda *args, **kwargs: (_ for _ in ()).throw(NotAllowed("create denied")))
    with pytest.raises(MediaStoragePermissionError):
        upload_to_cloudinary(image_file(800, 800), folder="ecommerce/products/a/b/images", resource_type="image", metadata=validate_image(image_file(800, 800), kind="product"))


def test_cloudinary_outage_is_safe_and_api_response_is_json(monkeypatch, settings):
    import cloudinary.uploader

    settings.CLOUDINARY_ENABLED = True
    monkeypatch.setattr(cloudinary.uploader, "upload", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("network down")))
    with pytest.raises(MediaStorageError) as raised:
        upload_to_cloudinary(image_file(800, 800), folder="ecommerce/products/a/b/images", resource_type="image", metadata=validate_image(image_file(800, 800), kind="product"))
    response = media_error_response(raised.value)
    assert response.status_code == 503
    assert response.data == {"code": "media_storage_unavailable", "detail": "Le service de stockage des médias est temporairement indisponible.", "message": "Le service de stockage des médias est temporairement indisponible."}


def test_cloudinary_permission_error_has_a_safe_502_json_response():
    response = media_error_response(MediaStoragePermissionError())
    assert response.status_code == 502
    assert response.data == {"code": "media_storage_permission_denied", "detail": "Le service de stockage n’autorise pas la création de ce média.", "message": "Le service de stockage n’autorise pas la création de ce média."}
