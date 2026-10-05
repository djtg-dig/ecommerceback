# Product catalog taxonomy

`apps.catalog` owns the platform-wide taxonomy used later to classify products. It does not contain products, variants, stock, orders, sales or purchases.

## Categories

`ProductCategory` has an internal UUID, an immutable-by-convention `code`, a display name and slug, an optional `product_type_key`, an active flag and a sortable self-reference. The hierarchy is validated in the model and is limited to three levels: root, child and grandchild. A category cannot point at itself or form a direct or indirect cycle. PostgreSQL keeps `code`, `slug` and every non-null `product_type_key` unique.

The initial migration seeds a small idempotent hierarchy: Electronics > Phones > Smartphones, Fashion > Shoes, and Food > Drinks. It is starter data, not a business-owned taxonomy.

## Attributes and inheritance

`AttributeDefinition` belongs to exactly one category and has a code, name, data type (`text`, `integer`, `decimal`, `boolean`, `choice`, `date`), optional unit, flags for requirement/filtering/variant axis, active flag and sort order. `(category, code)` is unique. A child cannot define a code already present in an ancestor, so inherited resolution is unambiguous.

`AttributeOption` supplies active or inactive choices for a `choice` definition. `(attribute_definition, value)` is unique. `effective_attributes(category)` resolves active definitions from the root to the requested category and returns the source category as `inherited_from`; inactive definitions and options are omitted.

## Public API

Both endpoints are public metadata endpoints and require no ecommerce JWT:

- `GET /api/v1/product-categories/` returns active categories in a flat list. Records expose `parent_code` and `level`, allowing every client to rebuild the tree.
- `GET /api/v1/product-categories/{code}/attributes/` returns active effective attributes, their source (`inherited_from`) and active options. An inactive or unknown category returns `404`.
