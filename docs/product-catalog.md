# Product catalog

`apps.catalog` owns both the global taxonomy and the tenant-owned product catalog. It deliberately contains no stock quantity, supplier, purchase, sale, cart, order, payment, images or marketplace publication. Product is descriptive catalog data; the future Inventory domain will own availability for either a simple product or one of its variants.

## Taxonomy and attributes

`ProductCategory` is global and is limited to three protected levels. Products can use only an active leaf category. `product_type_key` remains derived from that category and is never duplicated into `Product`.

`AttributeDefinition` is the schema; JSONB only stores values. Active inherited definitions are resolved from the root to the selected leaf. Unknown keys are rejected. `text`, `integer`, `decimal`, `boolean`, `date`, and `choice` values are validated, and choice values must match active `AttributeOption` records.

A non-variant-axis attribute belongs only in `Product.attributes`; a variant-axis attribute belongs only in `ProductVariant.attributes`. Required non-axis fields are required on Product. Required variant axes are required on each variant, but are not required on a product before it has variants.

## Product and variant identifiers

Both tables retain UUID primary keys internally and expose opaque immutable identifiers:

- Product: `PR` + 10 characters, for example `PR7K9M2X4P8Q`.
- ProductVariant: `PV` + 10 characters, for example `PV7K9M2X4P8Q`.

The shared generator uses `secrets` and alphabet `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`; PostgreSQL unique constraints are authoritative and creation retries up to five times on an identifier collision. UUIDs are not returned by the API.

`internal_reference` is the business SKU and is distinct from `public_id` and optional `barcode`. A SKU is unique per business across products and variants through validation plus per-table database constraints; concurrent cross-table writes remain a documented limitation until a future central SKU registry exists. Barcode has no global uniqueness constraint because merchant data may be imperfect and multiple barcode standards are expected.

## Prices and lifecycle

Prices are `DecimalField`, never float. `selling_price` is required and non-negative; `cost_price` is optional and non-negative. Currency is `CDF` or `USD`; omitted product currency defaults to `Business.primary_currency`, and no conversion occurs. A variant may override either price; otherwise `effective_selling_price` and `effective_cost_price` inherit the product value.

Products and variants use `ACTIVE`, `INACTIVE`, or `ARCHIVED`. APIs never physically delete products. `POST .../archive/` performs the controlled archival transition.

## Variant combinations

A variant contains only variant-axis values. Its `variant_signature` is SHA-256 over canonical JSON with sorted keys; order in the submitted JSON cannot create a second combination. `(product, variant_signature)` is unique. A simple product needs no variant; later stock rules can target the product itself or a variant.

## API and future scope

All writes require an active OWNER or MANAGER membership. Active EMPLOYEE memberships can read product and variant data only. Every lookup is constrained by membership, business and then product/variant; knowing an `SH`, `PR`, or `PV` code is never authorization.

A future `ProductImage` relation will add file handling. Marketplace publication will later have its own publication state, distinct from internal `Product.status`.


## Inventory boundary

Product and ProductVariant remain catalog records. Quantities, reservations and movements are implemented only in `apps.inventory`; see [Inventory](inventory.md). A simple product receives inventory directly, whereas a product with active variants is stocked through its variants.
