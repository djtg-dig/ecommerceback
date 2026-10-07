# POS product search

`GET /api/v1/businesses/{business_public_id}/products/pos/search/?q=...`
returns a compact, paginated list for the Android POS. An active Business member,
including an EMPLOYEE, may use it; an inaccessible Business returns `404`.

The server trims `q` and searches in order: exact public ID, trimmed barcode,
trimmed uppercase SKU, then product name text. Exact and text results are never
mixed. A duplicate sellable barcode or SKU returns `409` with `pos_barcode_conflict`
or `pos_sku_conflict`; the API never selects one arbitrarily.

An eligible Product is ACTIVE and has no ACTIVE variant. An eligible Variant and
its parent Product are both ACTIVE. Inactive and archived records are invisible.
The response returns only the sellable identifier, short name/variant label,
identifiers, effective price, currency, and `quantity - reserved_quantity`.
Missing inventory is represented by `0.000`, so active zero-stock articles remain
visible. Variant prices inherit the Product price when no override is set.

Text results are server-paginated (`page_size=20`, maximum `50`). The endpoint
projects stock on the server and joins variant parents, avoiding one inventory
request per mobile result and minimizing data on slow connections.
