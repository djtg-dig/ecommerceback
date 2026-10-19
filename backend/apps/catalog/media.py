"""Product media services: quota checks, ordering and remote lifecycle."""

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from rest_framework import serializers

from apps.common.media import destroy_cloudinary, upload_to_cloudinary, validate_image, validate_video

from .models import ProductMedia


class ProductMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductMedia
        fields = ("id", "media_type", "resource_type", "secure_url", "is_primary", "position", "width", "height", "duration_seconds", "format", "size_bytes", "created_at", "updated_at")
        read_only_fields = fields


def _prefix(product, kind: str) -> str:
    return f"ecommerce/products/{product.business.public_id}/{product.public_id}/{kind}"


def create_product_media(*, product, upload, media_type: str):
    metadata = validate_image(upload, kind="product") if media_type == ProductMedia.MediaType.IMAGE else validate_video(upload)
    kind = "images" if media_type == ProductMedia.MediaType.IMAGE else "videos"
    prefix = _prefix(product, kind)
    # Validate and reserve quota while holding the product row. Upload happens
    # after the inexpensive DB checks; a second check protects concurrent sends.
    with transaction.atomic():
        locked = type(product).objects.select_for_update().select_related("business").get(pk=product.pk)
        media = ProductMedia.objects.select_for_update().filter(product=locked)
        total = media.count()
        typed = media.filter(media_type=media_type).count()
        typed_limit = settings.ECOMMERCE_PRODUCT_IMAGE_LIMIT if media_type == ProductMedia.MediaType.IMAGE else settings.ECOMMERCE_PRODUCT_VIDEO_LIMIT
        if total >= settings.ECOMMERCE_PRODUCT_MEDIA_LIMIT or typed >= typed_limit:
            raise serializers.ValidationError({"file": "La limite de médias de ce produit est atteinte."})
    remote = upload_to_cloudinary(upload, folder=prefix, resource_type=metadata.resource_type, metadata=metadata)
    public_id, secure_url = remote.get("public_id"), remote.get("secure_url")
    if not public_id or not secure_url:
        raise serializers.ValidationError({"file": "Le stockage média a retourné une réponse incomplète."})
    try:
        with transaction.atomic():
            locked = type(product).objects.select_for_update().select_related("business").get(pk=product.pk)
            media = ProductMedia.objects.select_for_update().filter(product=locked)
            total, typed = media.count(), media.filter(media_type=media_type).count()
            typed_limit = settings.ECOMMERCE_PRODUCT_IMAGE_LIMIT if media_type == ProductMedia.MediaType.IMAGE else settings.ECOMMERCE_PRODUCT_VIDEO_LIMIT
            if total >= settings.ECOMMERCE_PRODUCT_MEDIA_LIMIT or typed >= typed_limit:
                raise serializers.ValidationError({"file": "La limite de médias de ce produit est atteinte."})
            position = (media.aggregate(last=Max("position"))["last"] or -1) + 1
            is_primary = media_type == ProductMedia.MediaType.IMAGE and not media.filter(is_primary=True).exists()
            return ProductMedia.objects.create(product=locked, public_id=public_id, secure_url=secure_url, media_type=media_type, resource_type=metadata.resource_type, is_primary=is_primary, position=position, width=metadata.width, height=metadata.height, duration_seconds=metadata.duration_seconds, format=metadata.format, size_bytes=metadata.size_bytes)
    except Exception:
        destroy_cloudinary(public_id, resource_type=metadata.resource_type, required_prefix=prefix)
        raise


def update_product_media(*, product, media, is_primary=None, position=None):
    with transaction.atomic():
        item = ProductMedia.objects.select_for_update().get(pk=media.pk, product=product)
        if is_primary is True and item.media_type != ProductMedia.MediaType.IMAGE:
            raise serializers.ValidationError({"is_primary": "Une vidéo ne peut pas être l’image principale."})
        if is_primary is True:
            ProductMedia.objects.filter(product=product, is_primary=True).exclude(pk=item.pk).update(is_primary=False)
            item.is_primary = True
        elif is_primary is False:
            item.is_primary = False
        if position is not None:
            # Positions are gallery indexes, not independent values. Lock the
            # whole product gallery so concurrent moves cannot create ties.
            ordered = list(
                ProductMedia.objects.select_for_update()
                .filter(product=product)
                .order_by("position", "created_at", "id")
            )
            current_index = next(index for index, candidate in enumerate(ordered) if candidate.pk == item.pk)
            target_index = min(position, len(ordered) - 1)
            moved = ordered.pop(current_index)
            ordered.insert(target_index, moved)
            for index, candidate in enumerate(ordered):
                if candidate.position != index:
                    ProductMedia.objects.filter(pk=candidate.pk).update(position=index)
                candidate.position = index
            item.position = target_index
        item.full_clean()
        item.save(update_fields=("is_primary", "position", "updated_at"))
    return item


def delete_product_media(*, product, media) -> None:
    prefix = _prefix(product, "images" if media.media_type == ProductMedia.MediaType.IMAGE else "videos")
    with transaction.atomic():
        item = ProductMedia.objects.select_for_update().get(pk=media.pk, product=product)
        promote = item.is_primary
        public_id, resource_type = item.public_id, item.resource_type
        item.delete()
        if promote:
            next_image = ProductMedia.objects.select_for_update().filter(product=product, media_type=ProductMedia.MediaType.IMAGE).order_by("position", "created_at", "id").first()
            if next_image:
                next_image.is_primary = True
                next_image.save(update_fields=("is_primary", "updated_at"))
        # Keep future inserts and all gallery reads deterministic after a delete.
        for index, remaining in enumerate(
            ProductMedia.objects.select_for_update().filter(product=product).order_by("position", "created_at", "id")
        ):
            if remaining.position != index:
                ProductMedia.objects.filter(pk=remaining.pk).update(position=index)
        transaction.on_commit(lambda: destroy_cloudinary(public_id, resource_type=resource_type, required_prefix=prefix))
