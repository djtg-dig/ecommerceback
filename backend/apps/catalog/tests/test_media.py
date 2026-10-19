from io import BytesIO
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductMedia
from apps.catalog.models import Product, ProductCategory
from apps.catalog.media import delete_product_media, update_product_media
from apps.catalog.views import media_error_response
from apps.businesses.models import Business
from apps.common.media import MediaStorageError, MediaStoragePermissionError, upload_to_cloudinary, validate_image, validate_video


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


@pytest.mark.django_db
def test_reordering_normalizes_the_whole_gallery_and_preserves_the_primary_image():
    business = Business.objects.create(name="Media shop")
    category = ProductCategory.objects.create(code="MEDIA_TEST", name="Media", slug="media-test")
    product = Product.objects.create(business=business, category=category, name="Product", selling_price=Decimal("1.00"), currency="CDF")
    first = ProductMedia.objects.create(product=product, public_id="ecommerce/products/test/first", secure_url="https://example.test/first.jpg", media_type="IMAGE", resource_type="image", is_primary=True, position=0, width=800, height=800, format="jpg", size_bytes=1)
    video = ProductMedia.objects.create(product=product, public_id="ecommerce/products/test/video", secure_url="https://example.test/video.mp4", media_type="VIDEO", resource_type="video", is_primary=False, position=1, width=144, height=144, duration_seconds="1.000", format="mp4", size_bytes=1)
    last = ProductMedia.objects.create(product=product, public_id="ecommerce/products/test/last", secure_url="https://example.test/last.jpg", media_type="IMAGE", resource_type="image", is_primary=False, position=2, width=800, height=800, format="jpg", size_bytes=1)

    update_product_media(product=product, media=video, position=0)
    ordered = list(product.media.order_by("position", "created_at", "id"))
    assert [item.pk for item in ordered] == [video.pk, first.pk, last.pk]
    assert [item.position for item in ordered] == [0, 1, 2]
    first.refresh_from_db()
    assert first.is_primary is True

    update_product_media(product=product, media=video, position=2)
    assert [item.pk for item in product.media.order_by("position", "created_at", "id")] == [first.pk, last.pk, video.pk]

    delete_product_media(product=product, media=last)
    assert [item.position for item in product.media.order_by("position", "created_at", "id")] == [0, 1]


@pytest.mark.parametrize("width,height", [(256, 144), (426, 240), (640, 360), (854, 480), (1280, 720), (1920, 1080), (3840, 2160)])
def test_valid_video_is_accepted_at_any_resolution(monkeypatch, width, height):
    upload = SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4")
    monkeypatch.setattr("apps.common.media.shutil.which", lambda _: "ffprobe")
    monkeypatch.setattr("apps.common.media.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": '{"format":{"format_name":"mp4","duration":"1"},"streams":[{"codec_type":"video","width":%d,"height":%d}]}' % (width, height)})())

    metadata = validate_video(upload)

    assert (metadata.width, metadata.height) == (width, height)
    assert metadata.resource_type == "video"


def _ffprobe(monkeypatch, payload, returncode=0):
    monkeypatch.setattr("apps.common.media.shutil.which", lambda _: "ffprobe")
    monkeypatch.setattr("apps.common.media.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": returncode, "stdout": payload})())


def test_video_larger_than_50_mb_is_rejected():
    upload = SimpleUploadedFile("large.mp4", b"x", content_type="video/mp4")
    upload.size = 50 * 1024 * 1024 + 1
    with pytest.raises(ValidationError, match="50 Mo"):
        validate_video(upload)


def test_video_longer_than_60_seconds_is_rejected(monkeypatch):
    _ffprobe(monkeypatch, '{"format":{"format_name":"mp4","duration":"60.001"},"streams":[{"codec_type":"video","width":3840,"height":2160}]}')
    with pytest.raises(ValidationError, match="60 secondes"):
        validate_video(SimpleUploadedFile("long.mp4", b"video", content_type="video/mp4"))


def test_file_without_video_stream_is_rejected(monkeypatch):
    _ffprobe(monkeypatch, '{"format":{"format_name":"mp4","duration":"1"},"streams":[{"codec_type":"audio"}]}')
    with pytest.raises(ValidationError, match="piste vidéo"):
        validate_video(SimpleUploadedFile("audio.mp4", b"audio", content_type="video/mp4"))


def test_corrupt_or_unsupported_video_is_rejected(monkeypatch):
    _ffprobe(monkeypatch, "", returncode=1)
    with pytest.raises(ValidationError, match="vidéo valide"):
        validate_video(SimpleUploadedFile("corrupt.mp4", b"bad", content_type="video/mp4"))
    _ffprobe(monkeypatch, '{"format":{"format_name":"avi","duration":"1"},"streams":[{"codec_type":"video","width":144,"height":144}]}')
    with pytest.raises(ValidationError, match="Formats vidéo"):
        validate_video(SimpleUploadedFile("unsupported.avi", b"video", content_type="video/avi"))


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
