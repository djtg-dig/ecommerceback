from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from apps.businesses.models import Business
from apps.businesses.permissions import membership_for, can_manage_business
from .models import Supplier, Purchase, PurchaseLine
from .serializers import (
    SupplierSerializer,
    PurchaseSerializer,
    PurchaseWriteSerializer,
    PurchaseLineSerializer,
    PurchaseLineWriteSerializer,
    SupplierPaymentSerializer, SupplierPaymentCreateSerializer, SupplierPaymentReverseSerializer,
)
from .services import transition, receive_purchase, add_supplier_payment, reverse_supplier_payment, SupplierPaymentIdempotencyConflict


class Mixin:
    def business(self, r, sh):
        return Business.objects.filter(
            public_id=sh, members__identity=r.user, members__status="ACTIVE"
        ).first()

    def nf(self):
        return Response({"detail": "Not found."}, 404)

    def forbid(self):
        return Response({"detail": "Forbidden."}, 403)


class Suppliers(Mixin, APIView):
    def get(self, r, business_public_id):
        b = self.business(r, business_public_id)
        return (
            Response(
                SupplierSerializer(Supplier.objects.filter(business=b), many=True).data
            )
            if b
            else self.nf()
        )

    def post(self, r, business_public_id):
        b = self.business(r, business_public_id)
        if not b:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        s = SupplierSerializer(data=r.data)
        s.is_valid(raise_exception=True)
        o = s.save(business=b)
        return Response(SupplierSerializer(o).data, 201)


class SupplierDetail(Suppliers):
    def obj(self, b, p):
        return Supplier.objects.filter(business=b, public_id=p).first()

    def get(self, r, business_public_id, supplier_public_id):
        b = self.business(r, business_public_id)
        o = self.obj(b, supplier_public_id) if b else None
        return Response(SupplierSerializer(o).data) if o else self.nf()

    def patch(self, r, business_public_id, supplier_public_id):
        b = self.business(r, business_public_id)
        o = self.obj(b, supplier_public_id) if b else None
        if not o:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        s = SupplierSerializer(o, data=r.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class Purchases(Mixin, APIView):
    def get(self, r, business_public_id):
        b = self.business(r, business_public_id)
        return (
            Response(
                PurchaseSerializer(Purchase.objects.filter(business=b), many=True).data
            )
            if b
            else self.nf()
        )

    def post(self, r, business_public_id):
        b = self.business(r, business_public_id)
        if not b:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        s = PurchaseWriteSerializer(data=r.data, context={"business": b})
        s.is_valid(raise_exception=True)
        o = s.save(business=b, created_by=r.user, currency=b.primary_currency)
        return Response(PurchaseSerializer(o).data, 201)


class PurchaseDetail(Purchases):
    def obj(self, b, p):
        return Purchase.objects.filter(business=b, public_id=p).first()

    def get(self, r, business_public_id, purchase_public_id):
        b = self.business(r, business_public_id)
        o = self.obj(b, purchase_public_id) if b else None
        return Response(PurchaseSerializer(o).data) if o else self.nf()

    def patch(self, r, business_public_id, purchase_public_id):
        b = self.business(r, business_public_id)
        o = self.obj(b, purchase_public_id) if b else None
        if not o:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        if o.status != "DRAFT":
            return Response({"detail": "Only drafts are editable."}, 400)
        s = PurchaseWriteSerializer(
            o, data=r.data, partial=True, context={"business": b}
        )
        s.is_valid(raise_exception=True)
        s.save()
        return Response(PurchaseSerializer(o).data)


class Lines(PurchaseDetail):
    def get(self, r, business_public_id, purchase_public_id):
        b = self.business(r, business_public_id)
        p = self.obj(b, purchase_public_id) if b else None
        return (
            Response(PurchaseLineSerializer(p.lines.all(), many=True).data)
            if p
            else self.nf()
        )

    def post(self, r, business_public_id, purchase_public_id):
        b = self.business(r, business_public_id)
        p = self.obj(b, purchase_public_id) if b else None
        if not p:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        if p.status != "DRAFT":
            return Response({"detail": "Only drafts are editable."}, 400)
        s = PurchaseLineWriteSerializer(data=r.data, context={"purchase": p})
        s.is_valid(raise_exception=True)
        o = PurchaseLine.objects.create(purchase=p, **s.validated_data)
        return Response(PurchaseLineSerializer(o).data, 201)


class LineDetail(Lines):
    def getobj(self, p, x):
        return p.lines.filter(public_id=x).first()

    def get(self, r, business_public_id, purchase_public_id, line_public_id):
        b = self.business(r, business_public_id)
        p = self.obj(b, purchase_public_id) if b else None
        o = self.getobj(p, line_public_id) if p else None
        return Response(PurchaseLineSerializer(o).data) if o else self.nf()

    def patch(self, r, business_public_id, purchase_public_id, line_public_id):
        return self._edit(
            r, business_public_id, purchase_public_id, line_public_id, False
        )

    def delete(self, r, business_public_id, purchase_public_id, line_public_id):
        return self._edit(
            r, business_public_id, purchase_public_id, line_public_id, True
        )

    def _edit(self, r, sh, pu, pl, delete):
        b = self.business(r, sh)
        p = self.obj(b, pu) if b else None
        o = self.getobj(p, pl) if p else None
        if not o:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        if p.status != "DRAFT":
            return Response({"detail": "Only drafts are editable."}, 400)
        if delete:
            o.delete()
            return Response(status=204)
        s = PurchaseLineWriteSerializer(data=r.data, context={"purchase": p})
        s.is_valid(raise_exception=True)
        [setattr(o, k, v) for k, v in s.validated_data.items()]
        o.save()
        return Response(PurchaseLineSerializer(o).data)


class Action(PurchaseDetail):
    action = None

    def post(self, r, business_public_id, purchase_public_id):
        b = self.business(r, business_public_id)
        p = self.obj(b, purchase_public_id) if b else None
        if not p:
            return self.nf()
        if not can_manage_business(membership_for(r.user, b)):
            return self.forbid()
        try:
            o = (
                receive_purchase(p, r.user)
                if self.action == "receive"
                else transition(p, self.action, r.user)
            )
        except ValidationError as e:
            return Response({"detail": str(e)}, 400)
        return Response(PurchaseSerializer(o).data)


class Confirm(Action):
    action = "confirm"

    def post(self, *a, **kw):
        return super().post(*a, **kw)


class Receive(Action):
    action = "receive"

    def post(self, *a, **kw):
        return super().post(*a, **kw)


class Cancel(Action):
    action = "cancel"

    def post(self, *a, **kw):
        return super().post(*a, **kw)


from drf_spectacular.utils import extend_schema, OpenApiParameter

_bp = OpenApiParameter("business_public_id", str, OpenApiParameter.PATH)
_sp = OpenApiParameter("supplier_public_id", str, OpenApiParameter.PATH)
_pu = OpenApiParameter("purchase_public_id", str, OpenApiParameter.PATH)
_pl = OpenApiParameter("line_public_id", str, OpenApiParameter.PATH)
Suppliers.get = extend_schema(
    tags=["Suppliers"],
    operation_id="supplier_list",
    parameters=[_bp],
    responses={200: SupplierSerializer(many=True)},
)(Suppliers.get)
Suppliers.post = extend_schema(
    tags=["Suppliers"],
    operation_id="supplier_create",
    parameters=[_bp],
    request=SupplierSerializer,
    responses={201: SupplierSerializer},
)(Suppliers.post)
SupplierDetail.get = extend_schema(
    tags=["Suppliers"],
    operation_id="supplier_retrieve",
    parameters=[_bp, _sp],
    responses={200: SupplierSerializer},
)(SupplierDetail.get)
SupplierDetail.patch = extend_schema(
    tags=["Suppliers"],
    operation_id="supplier_update",
    parameters=[_bp, _sp],
    request=SupplierSerializer,
    responses={200: SupplierSerializer},
)(SupplierDetail.patch)
Purchases.get = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_list",
    parameters=[_bp],
    responses={200: PurchaseSerializer(many=True)},
)(Purchases.get)
Purchases.post = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_create",
    parameters=[_bp],
    request=PurchaseWriteSerializer,
    responses={201: PurchaseSerializer},
)(Purchases.post)
PurchaseDetail.get = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_retrieve",
    parameters=[_bp, _pu],
    responses={200: PurchaseSerializer},
)(PurchaseDetail.get)
PurchaseDetail.patch = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_update",
    parameters=[_bp, _pu],
    request=PurchaseWriteSerializer,
    responses={200: PurchaseSerializer},
)(PurchaseDetail.patch)
Lines.get = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_line_list",
    parameters=[_bp, _pu],
    responses={200: PurchaseLineSerializer(many=True)},
)(Lines.get)
Lines.post = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_line_create",
    parameters=[_bp, _pu],
    request=PurchaseLineWriteSerializer,
    responses={201: PurchaseLineSerializer},
)(Lines.post)
LineDetail.get = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_line_retrieve",
    parameters=[_bp, _pu, _pl],
    responses={200: PurchaseLineSerializer},
)(LineDetail.get)
LineDetail.patch = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_line_update",
    parameters=[_bp, _pu, _pl],
    request=PurchaseLineWriteSerializer,
    responses={200: PurchaseLineSerializer},
)(LineDetail.patch)
LineDetail.delete = extend_schema(
    tags=["Purchases"],
    operation_id="purchase_line_delete",
    parameters=[_bp, _pu, _pl],
    responses={204: None},
)(LineDetail.delete)
for C, n in ((Confirm, "confirm"), (Receive, "receive"), (Cancel, "cancel")):
    C.post = extend_schema(
        tags=["Purchases"],
        operation_id="purchase_" + n,
        parameters=[_bp, _pu],
        request=None,
        responses={200: PurchaseSerializer, 400: None},
    )(C.post)
# Restrict inherited APIView methods so detail/action routes expose only real operations.
SupplierDetail.http_method_names = ["get", "patch", "head", "options"]
PurchaseDetail.http_method_names = ["get", "patch", "head", "options"]
Lines.http_method_names = ["get", "post", "head", "options"]
LineDetail.http_method_names = ["get", "patch", "delete", "head", "options"]
Confirm.http_method_names = ["post", "options"]
Receive.http_method_names = ["post", "options"]
Cancel.http_method_names = ["post", "options"]

class PurchasePayments(PurchaseDetail):
 def get(self,r,business_public_id,purchase_public_id):
  b=self.business(r,business_public_id);p=self.obj(b,purchase_public_id) if b else None
  return Response(SupplierPaymentSerializer(p.payments.all(),many=True).data) if p else self.nf()
 def post(self,r,business_public_id,purchase_public_id):
  b=self.business(r,business_public_id);p=self.obj(b,purchase_public_id) if b else None
  if not p:return self.nf()
  if not can_manage_business(membership_for(r.user,b)):return self.forbid()
  s=SupplierPaymentCreateSerializer(data=r.data);s.is_valid(raise_exception=True)
  try:o=add_supplier_payment(p,r.user,idempotency_key=r.headers.get('Idempotency-Key',''),**s.validated_data)
  except SupplierPaymentIdempotencyConflict as e:return Response({'detail':str(e)},409)
  except ValidationError as e:return Response({'detail':str(e)},400)
  return Response(SupplierPaymentSerializer(o).data,201)
class SupplierPaymentReverse(PurchasePayments):
 def post(self,r,business_public_id,purchase_public_id,payment_public_id):
  b=self.business(r,business_public_id);p=self.obj(b,purchase_public_id) if b else None;o=p.payments.filter(public_id=payment_public_id).first() if p else None
  if not o:return self.nf()
  if not can_manage_business(membership_for(r.user,b)):return self.forbid()
  s=SupplierPaymentReverseSerializer(data=r.data);s.is_valid(raise_exception=True)
  try:return Response(SupplierPaymentSerializer(reverse_supplier_payment(o,r.user,s.validated_data['reason'])).data)
  except ValidationError as e:return Response({'detail':str(e)},400)
PurchasePayments.http_method_names=['get','post','head','options'];SupplierPaymentReverse.http_method_names=['post','options']

PurchasePayments.serializer_class = SupplierPaymentSerializer
SupplierPaymentReverse.serializer_class = SupplierPaymentReverseSerializer
