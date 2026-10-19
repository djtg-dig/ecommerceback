from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductMedia
from apps.common.media import validate_image


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
