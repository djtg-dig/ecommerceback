# Purchases

`apps.purchases` regroupe Supplier, Purchase et PurchaseLine car ils forment le flux d’approvisionnement d’un commerce. Les identifiants publics sont `SP`, `PU` et `PL` plus dix caractères sécurisés.

Une Purchase commence en `DRAFT`: ses lignes, fournisseur et notes sont modifiables et aucun stock ne bouge. `confirm` exige au moins une ligne et passe à `CONFIRMED`. `receive` verrouille l’achat, crée si nécessaire un InventoryItem à zéro, ajoute un mouvement `IN` système par ligne (`reference_type=PURCHASE`), applique le dernier `unit_cost` comme `cost_price` courant, puis passe à `RECEIVED`. Cette transaction est atomique et une seconde réception est refusée. `cancel` est possible depuis DRAFT ou CONFIRMED, jamais depuis RECEIVED.

Les lignes visent exactement un Product simple ou ProductVariant, utilisent quantité `Decimal(14,3)`, coût unitaire décimal et total calculé serveur. Le total d’achat est la somme des lignes, sans TVA, remise, transport ni paiement fournisseur. Les mouvements de réception sont idempotents au niveau du statut verrouillé; les futurs achats intégrés devront renforcer cette garantie avec une clé métier.

OWNER et MANAGER écrivent; EMPLOYEE lit. Aucun Supplier, achat ou article d’un autre commerce ne peut être utilisé.

Les nouvelles purchases utilisent obligatoirement `Business.primary_currency`. Une devise contradictoire est refusée et aucune conversion n’est appliquée.
