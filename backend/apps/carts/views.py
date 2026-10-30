from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.catalog.models import Product

from .models import Cart, CartItem
from .serializers import AddProductSerializer, AddToCartSerializer, CartSerializer, QuantitySerializer, TransferSerializer
from .services import BusinessMemberCannotPurchaseError, CartLockedError, add_product, create_cart, create_default_cart, require_mutable, require_purchase_allowed, set_item_quantity, transfer_item


class CartPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CartViewMixin:
    def carts(self, request):
        return Cart.objects.filter(buyer=request.user).select_related("business", "locked_by").prefetch_related(
            "items__product__unit_of_measure",
            "items__product__media",
        )

    def cart(self, request, reference):
        return self.carts(request).filter(reference=reference).first()

    def not_found(self):
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    def locked(self):
        return Response({"code": "CART_LOCKED", "detail": "Ce panier est verrouillé."}, status=status.HTTP_409_CONFLICT)

    def member_cannot_purchase(self):
        return Response({
            "code": "BUSINESS_MEMBER_CANNOT_PURCHASE",
            "detail": "Vous ne pouvez pas acheter de produits dans une boutique dont vous êtes membre.",
        }, status=status.HTTP_403_FORBIDDEN)

    def product(self, product_reference):
        # Cart mutations must enforce the same commercial visibility contract as
        # the marketplace instead of trusting a product identifier from the client.
        return Product.objects.select_related("business", "unit_of_measure").filter(
            public_id=product_reference,
            status=Product.Status.ACTIVE,
            is_public=True,
            is_online_purchasable=True,
            business__status=Business.Status.ACTIVE,
        ).first()


class CartListCreateView(CartViewMixin, APIView):
    def get(self, request):
        carts = self.carts(request)
        business_reference = request.query_params.get("business")
        if business_reference:
            carts = carts.filter(business__public_id=business_reference)
        search = request.query_params.get("search")
        if search:
            carts = carts.filter(name__icontains=search.strip())
        status_value = request.query_params.get("status")
        if status_value in Cart.Status.values:
            carts = carts.filter(status=status_value)
        paginator = CartPagination()
        page = paginator.paginate_queryset(carts, request)
        return paginator.get_paginated_response(CartSerializer(page, many=True).data)

    def post(self, request):
        serializer = CartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        business_reference = request.data.get("business")
        business = Business.objects.filter(public_id=business_reference).first()
        if not business:
            raise ValidationError({"business": "Entreprise introuvable."})
        try:
            cart = create_cart(buyer=request.user, business=business, name=serializer.validated_data["name"])
            cart.save()
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        except IntegrityError:
            raise ValidationError({"name": "Vous avez déjà un panier de ce nom dans cette entreprise."}) from None
        return Response(CartSerializer(self.cart(request, cart.reference)).data, status=status.HTTP_201_CREATED)


class CartDetailView(CartViewMixin, APIView):
    def get(self, request, reference):
        cart = self.cart(request, reference)
        return Response(CartSerializer(cart).data) if cart else self.not_found()

    def patch(self, request, reference):
        cart = self.cart(request, reference)
        if not cart:
            return self.not_found()
        try:
            require_purchase_allowed(buyer=request.user, business=cart.business)
            require_mutable(cart)
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except CartLockedError:
            return self.locked()
        serializer = CartSerializer(cart, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        except IntegrityError:
            raise ValidationError({"name": "Vous avez déjà un panier de ce nom dans cette entreprise."}) from None
        return Response(CartSerializer(self.cart(request, reference)).data)

    def delete(self, request, reference):
        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(reference=reference, buyer=request.user).first()
            if not cart:
                return self.not_found()
            try:
                require_purchase_allowed(buyer=request.user, business=cart.business)
                require_mutable(cart)
            except BusinessMemberCannotPurchaseError:
                return self.member_cannot_purchase()
            except CartLockedError:
                return self.locked()
            cart.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemListCreateView(CartViewMixin, APIView):
    def post(self, request, reference):
        cart = self.cart(request, reference)
        if not cart:
            return self.not_found()
        serializer = AddProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = self.product(serializer.validated_data["product"])
        if not product:
            raise ValidationError({"product": "Produit introuvable ou indisponible."})
        try:
            item = add_product(cart=cart, product=product, quantity=serializer.validated_data["quantity"])
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except CartLockedError:
            return self.locked()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(CartSerializer(self.cart(request, reference)).data, status=status.HTTP_201_CREATED)


class CartItemDetailView(CartViewMixin, APIView):
    def patch(self, request, reference, product_reference):
        cart = self.cart(request, reference)
        product = self.product(product_reference)
        if not cart or not product:
            return self.not_found()
        serializer = QuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = set_item_quantity(cart=cart, product=product, quantity=serializer.validated_data["quantity"])
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except CartLockedError:
            return self.locked()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        if not item:
            return self.not_found()
        return Response(CartSerializer(self.cart(request, reference)).data)

    def delete(self, request, reference, product_reference):
        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(reference=reference, buyer=request.user).first()
            if not cart:
                return self.not_found()
            try:
                require_purchase_allowed(buyer=request.user, business=cart.business)
                require_mutable(cart)
            except BusinessMemberCannotPurchaseError:
                return self.member_cannot_purchase()
            except CartLockedError:
                return self.locked()
            item = CartItem.objects.select_for_update().filter(cart=cart, product__public_id=product_reference).first()
            if not item:
                return self.not_found()
            item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartClearView(CartViewMixin, APIView):
    def post(self, request, reference):
        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(reference=reference, buyer=request.user).first()
            if not cart:
                return self.not_found()
            try:
                require_purchase_allowed(buyer=request.user, business=cart.business)
                require_mutable(cart)
            except BusinessMemberCannotPurchaseError:
                return self.member_cannot_purchase()
            except CartLockedError:
                return self.locked()
            CartItem.objects.filter(cart=cart).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AddToCartView(CartViewMixin, APIView):
    def post(self, request):
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = self.product(serializer.validated_data["product"])
        if not product:
            raise ValidationError({"product": "Produit introuvable ou indisponible."})
        reference = serializer.validated_data.get("cart")
        if reference:
            cart = self.cart(request, reference)
            if not cart:
                return self.not_found()
        else:
            drafts = list(self.carts(request).filter(business=product.business, status=Cart.Status.DRAFT))
            if len(drafts) == 1:
                cart = drafts[0]
            elif len(drafts) > 1:
                raise ValidationError({"cart": "Sélectionnez le panier à utiliser."})
            else:
                try:
                    cart = create_default_cart(buyer=request.user, business=product.business)
                except BusinessMemberCannotPurchaseError:
                    return self.member_cannot_purchase()
        try:
            add_product(cart=cart, product=product, quantity=serializer.validated_data["quantity"])
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except CartLockedError:
            return self.locked()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(CartSerializer(self.cart(request, cart.reference)).data, status=status.HTTP_201_CREATED)


class CartTransferView(CartViewMixin, APIView):
    def post(self, request):
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = self.cart(request, serializer.validated_data["source_cart"])
        destination = self.cart(request, serializer.validated_data["destination_cart"])
        product = self.product(serializer.validated_data["product"])
        if not source or not destination or not product:
            return self.not_found()
        try:
            transfer_item(buyer=request.user, source=source, destination=destination, product=product, quantity=serializer.validated_data["quantity"])
        except BusinessMemberCannotPurchaseError:
            return self.member_cannot_purchase()
        except CartLockedError:
            return self.locked()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(CartSerializer(self.cart(request, destination.reference)).data)
