# Public identifiers

`SH` denotes a public Business/Shop reference. The suffix has ten cryptographically generated characters from an unambiguous 32-character alphabet. UUIDs remain internal. Future entity prefixes may be added without changing this convention.

## Product catalog identifiers

Products use immutable `PR` plus ten random characters and variants use `PV` plus ten. Both use the same secure alphabet and bounded collision retry strategy as businesses; they are opaque references, never authorization credentials.

## Inventory identifiers

| Prefix | Resource |
|---|---|
| `SH` | Business |
| `PR` | Product |
| `PV` | ProductVariant |
| `IV` | InventoryItem |
| `SM` | StockMovement |

Chaque identifiant est son préfixe plus 10 caractères tirés cryptographiquement de `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`.

| `SP` | Supplier |
| `PU` | Purchase |
| `PL` | PurchaseLine |

| `CU` | Customer |
| `SA` | Sale |
| `SL` | SaleLine |
