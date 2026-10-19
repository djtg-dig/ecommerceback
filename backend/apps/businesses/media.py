"""Business branding media orchestration."""

from django.db import transaction
from rest_framework import serializers

from apps.common.media import destroy_cloudinary, upload_to_cloudinary, validate_image

from .models import BusinessMedia


class BusinessMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessMedia
        fields = ("media_type", "secure_url", "width", "height", "format", "size_bytes", "created_at", "updated_at")


def replace_business_media(*, business, media_type: str, upload):
    kind = "logo" if media_type == BusinessMedia.MediaType.LOGO else "banner"
    metadata = validate_image(upload, kind=kind)
    prefix = f"ecommerce/businesses/{business.public_id}/{kind}"
    remote = upload_to_cloudinary(upload, folder=prefix, resource_type="image", metadata=metadata)
    new_public_id = remote.get("public_id")
    secure_url = remote.get("secure_url")
    if not new_public_id or not secure_url:
        raise serializers.ValidationError({"file": "Le stockage média a retourné une réponse incomplète."})
    try:
        with transaction.atomic():
            previous = BusinessMedia.objects.select_for_update().filter(business=business, media_type=media_type).first()
            item, _ = BusinessMedia.objects.update_or_create(
                business=business, media_type=media_type,
                defaults={"public_id": new_public_id, "secure_url": secure_url, "width": metadata.width, "height": metadata.height, "format": metadata.format, "size_bytes": metadata.size_bytes},
            )
            if previous and previous.public_id != new_public_id:
                transaction.on_commit(lambda: destroy_cloudinary(previous.public_id, resource_type="image", required_prefix=prefix))
            return item
    except Exception:
        destroy_cloudinary(new_public_id, resource_type="image", required_prefix=prefix)
        raise


def delete_business_media(*, business, media_type: str) -> bool:
    kind = "logo" if media_type == BusinessMedia.MediaType.LOGO else "banner"
    prefix = f"ecommerce/businesses/{business.public_id}/{kind}"
    with transaction.atomic():
        item = BusinessMedia.objects.select_for_update().filter(business=business, media_type=media_type).first()
        if item is None:
            return False
        public_id = item.public_id
        item.delete()
        transaction.on_commit(lambda: destroy_cloudinary(public_id, resource_type="image", required_prefix=prefix))
    return True
