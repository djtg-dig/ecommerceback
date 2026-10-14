# Audit des permissions atomiques

Date de l'audit : 2026-10-14. Cette matrice décrit les opérations réellement exposées avant la migration. Les catégories produit publiques et la création d'une entreprise depuis l'espace personnel ne relèvent pas des permissions d'une appartenance.

## Matrice des opérations

| Module | Opération | Endpoint | Permission avant | Permission atomique | Interface | Risque / test |
|---|---|---|---|---|---|---|
| Entreprise | Consulter | `GET /businesses/{id}/` | appartenance active | appartenance active | shell, paramètres | isolation locataire |
| Entreprise | Modifier | `PATCH /businesses/{id}/` | `UPDATE_BUSINESS` | `BUSINESS_UPDATE` | paramètres | membre sans droit refusé |
| Paiements | Lister/consulter | `GET .../payment-methods[/id]/` | `VIEW_PAYMENT_METHODS` ou `USE_POS` (actifs seuls) | `PAYMENT_METHOD_VIEW` ou action appelante limitée | ventes, paramètres | aucune méthode inactive via sélection |
| Paiements | Créer | `POST .../payment-methods/` | `MANAGE_PAYMENT_METHODS` | `PAYMENT_METHOD_CREATE` | paramètres | indépendance create/update |
| Paiements | Modifier/activer/désactiver | `PATCH .../payment-methods/{id}/` | `MANAGE_PAYMENT_METHODS` | `PAYMENT_METHOD_UPDATE` | paramètres | validation tenant |
| Membres | Lister/consulter | `GET .../members[/id]/` | `VIEW_MEMBERS` | `MEMBER_VIEW` | Membres et accès | données personnelles protégées |
| Membres | Modifier le titre | `PATCH .../members/{id}/` | `MANAGE_MEMBERS` | `MEMBER_UPDATE` | modale membre | aucun effet sur les droits |
| Membres | Suspendre | `POST .../suspend/` | `MANAGE_MEMBERS` | `MEMBER_SUSPEND` | modale membre | propriétaire/soi-même protégés |
| Membres | Réactiver | `POST .../reactivate/` | `MANAGE_MEMBERS` | `MEMBER_REACTIVATE` | modale membre | membre supprimé refusé |
| Membres | Retirer | `DELETE .../members/{id}/` | `MANAGE_MEMBERS` | `MEMBER_REMOVE` | modale membre | révocation atomique des accès |
| Permissions | Catalogue/permissions membre | `GET .../permissions/`, `GET .../members/{id}/permissions/` | `VIEW_MEMBERS` | `MEMBER_PERMISSION_VIEW` | Membres et accès | lecture seule indépendante |
| Permissions | Attribuer | `POST .../members/{id}/permissions/` | `MANAGE_MEMBERS` + owner | `MEMBER_PERMISSION_GRANT` + politique de délégation | modale membre | anti-auto-élévation, droit possédé |
| Permissions | Révoquer | `DELETE .../permissions/{code}/` | `MANAGE_MEMBERS` + owner | `MEMBER_PERMISSION_REVOKE` + politique de délégation | modale membre | indépendant de grant |
| Invitations | Lister | `GET .../invitations/` | `VIEW_MEMBERS` | `INVITATION_VIEW` | Membres et accès | isolation locataire |
| Invitations | Créer | `POST .../invitations/` | `MANAGE_MEMBERS` | `INVITATION_CREATE` | modale invitation | délégation limitée aux droits de l'acteur |
| Invitations | Renvoyer | `POST .../resend/` | `MANAGE_MEMBERS` | `INVITATION_RESEND` | Membres et accès | rotation secret, statut |
| Invitations | Révoquer | `POST .../revoke/` | `MANAGE_MEMBERS` | `INVITATION_REVOKE` | Membres et accès | statut/tenant |
| Invitations reçues | Lister/accepter/refuser | endpoints `/member-invitations/...` | identité destinataire | identité destinataire (inchangé) | espace personnel | e-mail vérifié, expiration |
| Produits | Lister/consulter | `GET .../products[/id]/` | `VIEW_CATALOG` | `PRODUCT_VIEW` | Produits | droit action seul sans liste |
| Produits | Créer | `POST .../products/` | `MANAGE_CATALOG` | `PRODUCT_CREATE` | modale produit | aucune modification implicite |
| Produits | Modifier | `PATCH .../products/{id}/` | `MANAGE_CATALOG` | `PRODUCT_UPDATE` | modale produit | aucune suppression implicite |
| Produits | Archiver | `POST .../products/{id}/archive/` | `MANAGE_CATALOG` | `PRODUCT_DEACTIVATE` | Produits | historique préservé |
| Produits | Supprimer si éligible | `DELETE .../products/{id}/` | absent | `PRODUCT_DELETE` | action ciblée par identifiant | références protégées, scénario DELETE seul |
| Variantes | Lister/consulter | `GET .../variants[/id]/` | `VIEW_CATALOG` | `PRODUCT_VARIANT_VIEW` | Produits | portée produit/tenant |
| Variantes | Créer | `POST .../variants/` | `MANAGE_CATALOG` | `PRODUCT_VARIANT_CREATE` | Produits | contraintes stock |
| Variantes | Modifier | `PATCH .../variants/{id}/` | `MANAGE_CATALOG` | `PRODUCT_VARIANT_UPDATE` | Produits | aucune suppression existante |
| Vente | Recherche article/client limitée | `GET .../pos/search/` | `USE_POS` | `SALE_CREATE` | point de vente | projection compacte, pas de catalogue général |
| Vente | Lister/consulter | `GET .../sales[/id]/` | `VIEW_SALES` | `SALE_VIEW` | Ventes | indépendant du POS |
| Vente | Créer | `POST .../sales/` | `USE_POS` | `SALE_CREATE` | modale vente | indépendant update/complete |
| Vente | Modifier brouillon | `PATCH .../sales/{id}/` | `USE_POS` | `SALE_UPDATE` | modale vente | brouillon uniquement |
| Ligne de vente | Lister | `GET .../sales/{id}/lines/` | `VIEW_SALES` | `SALE_LINE_VIEW` | vente | indépendant create |
| Ligne de vente | Créer | `POST .../sales/{id}/lines/` | `USE_POS` | `SALE_LINE_CREATE` | modale vente | brouillon uniquement |
| Vente | Finaliser | `POST .../complete/` | `USE_POS` | `SALE_COMPLETE` | Ventes | stock/finance atomiques |
| Vente | Annuler | `POST .../cancel/` | `MANAGE_SALES` | `SALE_CANCEL` | Ventes | transition contrôlée |
| Retour | Lister | `GET .../returns/` | `MANAGE_SALE_RETURNS` | `SALE_RETURN_VIEW` | Ventes | lecture indépendante |
| Retour | Créer | `POST .../returns/` | `MANAGE_SALE_RETURNS` | `SALE_RETURN` | Ventes | idempotence/stock/finance |
| Clients | Lister/consulter/profil | endpoints `customers` | `VIEW_CUSTOMERS` | `CUSTOMER_VIEW` | Clients | finance/ventes restent filtrées |
| Clients | Créer | `POST .../customers/` | `MANAGE_CUSTOMERS` | `CUSTOMER_CREATE` | modale client | droit atomique |
| Clients | Modifier | `PATCH .../customers/{id}/` | `MANAGE_CUSTOMERS` | `CUSTOMER_UPDATE` | modale client | hors changement d'état |
| Clients | Désactiver/réactiver | même `PATCH` avec `is_active` | `MANAGE_CUSTOMERS` | `CUSTOMER_DEACTIVATE` / `CUSTOMER_REACTIVATE` | Clients | permission choisie selon transition |
| Fournisseurs | Lister/consulter/profil | endpoints `suppliers` | `VIEW_PURCHASES` | `SUPPLIER_VIEW` | Fournisseurs | indépendant achats |
| Fournisseurs | Créer | `POST .../suppliers/` | `MANAGE_PURCHASES` | `SUPPLIER_CREATE` | modale fournisseur | indépendant achats |
| Fournisseurs | Modifier/état | `PATCH .../suppliers/{id}/` | `MANAGE_PURCHASES` | `SUPPLIER_UPDATE` ou `SUPPLIER_DEACTIVATE` / `SUPPLIER_REACTIVATE` | Fournisseurs | permission selon transition |
| Stock | Lister/consulter/résumé | endpoints inventory hors mouvements | `VIEW_INVENTORY` | `INVENTORY_VIEW` | Stocks | lecture seule |
| Stock | Initialiser article | `POST .../inventory/` | `MANAGE_INVENTORY` | `INVENTORY_INITIALIZE` | Stocks | solde zéro |
| Stock | Historique | `GET .../movements/` | `VIEW_INVENTORY` | `INVENTORY_MOVEMENT_VIEW` | Stocks | séparé du solde |
| Stock | Entrée/sortie/ajustement | `POST .../{item}/movements/` | `MANAGE_INVENTORY` | `INVENTORY_IN` / `INVENTORY_OUT` / `INVENTORY_ADJUST` selon payload | modale mouvement | contrôle après validation, idempotence |
| Achats | Lister/consulter | `GET .../purchases[/id]/` | `VIEW_PURCHASES` | `PURCHASE_VIEW` | Achats | aucun droit fournisseur implicite |
| Achats | Créer | `POST .../purchases/` | `MANAGE_PURCHASES` | `PURCHASE_CREATE` | modale achat | atomique |
| Achats | Modifier brouillon | `PATCH .../purchases/{id}/` | `MANAGE_PURCHASES` | `PURCHASE_UPDATE` | modale achat | brouillon uniquement |
| Lignes achat | Lister/créer/modifier/supprimer | endpoints `lines` | `VIEW_PURCHASES` / `MANAGE_PURCHASES` | `PURCHASE_LINE_VIEW/CREATE/UPDATE/DELETE` | modale achat | droits indépendants |
| Achats | Confirmer/recevoir/annuler | endpoints d'action | `MANAGE_PURCHASES` | `PURCHASE_CONFIRM/RECEIVE/CANCEL` | Achats | transitions et stock préservés |
| Paiements fournisseur | Lister/créer/révoquer | endpoints `payments` | `VIEW_PURCHASES` / `MANAGE_PURCHASES` | `SUPPLIER_PAYMENT_VIEW/CREATE/REVERSE` | Finance/Achats | comptabilisation et idempotence |
| Créances | Lister/consulter | endpoints receivables | `VIEW_RECEIVABLES` | `RECEIVABLE_VIEW` | Finance | lecture seule |
| Créances | Modifier échéance/notes | `PATCH .../receivables/{id}/` | `MANAGE_RECEIVABLES` | `RECEIVABLE_UPDATE` | Finance | pas d'ajustement montant exposé |
| Encaissements | Lister/créer | `GET/POST .../payments/` | `VIEW/MANAGE_RECEIVABLES` | `RECEIVABLE_PAYMENT_VIEW/CREATE` | Finance | transaction atomique |
| Finance | Synthèse | `GET .../financial-summary/` | `VIEW_FINANCIAL_SUMMARY` | `FINANCIAL_SUMMARY_VIEW` | Finance | agrégats tenant |
| Finance | Mouvements liste/détail | endpoints financial-movements | `VIEW_FINANCIAL_SUMMARY` | `FINANCIAL_MOVEMENT_VIEW` | Finance | indépendant synthèse |
| Dépenses | Catégories lire/créer/modifier | endpoints expense-categories | `VIEW_EXPENSES` / `MANAGE_EXPENSE_CATEGORIES` | `EXPENSE_CATEGORY_VIEW/CREATE/UPDATE` | Finance | catégories système protégées |
| Dépenses | Lire/créer/modifier/annuler | endpoints expenses | `VIEW_EXPENSES`, `CREATE_EXPENSES`, `MANAGE_EXPENSES` | `EXPENSE_VIEW/CREATE/UPDATE/CANCEL` | Finance | transitions indépendantes |
| Paiements dépenses | Lister/créer/révoquer | endpoints payments | `VIEW_EXPENSES` / `MANAGE_EXPENSES` | `EXPENSE_PAYMENT_VIEW/CREATE/REVERSE` | Finance | écritures financières |
| Analytique | Dashboard | `GET .../dashboard/` | `VIEW_DASHBOARD` | `DASHBOARD_VIEW` | Dashboard | lecture seule |
| Analytique | Rentabilité | `GET .../profitability/` | `VIEW_PROFITABILITY` | `PROFITABILITY_VIEW` | Dashboard | lecture sensible |
| Rapports | Ventes / achats / dépenses-créances | endpoints reports | `VIEW_REPORTS` | `SALE_REPORT_VIEW/PURCHASE_REPORT_VIEW/EXPENSE_RECEIVABLE_REPORT_VIEW` | Rapports | rapports indépendants |

## Correspondance de migration

Chaque ancien code est développé uniquement vers les opérations qu'il autorisait effectivement :

- `VIEW_MEMBERS` → `MEMBER_VIEW`, `MEMBER_PERMISSION_VIEW`, `INVITATION_VIEW`.
- `MANAGE_MEMBERS` → `MEMBER_UPDATE`, `MEMBER_SUSPEND`, `MEMBER_REACTIVATE`, `MEMBER_REMOVE`, `MEMBER_PERMISSION_GRANT`, `MEMBER_PERMISSION_REVOKE`, `INVITATION_CREATE`, `INVITATION_RESEND`, `INVITATION_REVOKE`.
- `UPDATE_BUSINESS` → `BUSINESS_UPDATE`.
- `VIEW_PAYMENT_METHODS` → `PAYMENT_METHOD_VIEW`; `MANAGE_PAYMENT_METHODS` → `PAYMENT_METHOD_CREATE`, `PAYMENT_METHOD_UPDATE`.
- `VIEW_CUSTOMERS` → `CUSTOMER_VIEW`; `MANAGE_CUSTOMERS` → `CUSTOMER_CREATE`, `CUSTOMER_UPDATE`, `CUSTOMER_DEACTIVATE`, `CUSTOMER_REACTIVATE`.
- `VIEW_CATALOG` → `PRODUCT_VIEW`, `PRODUCT_VARIANT_VIEW`; `MANAGE_CATALOG` → `PRODUCT_CREATE`, `PRODUCT_UPDATE`, `PRODUCT_DEACTIVATE`, `PRODUCT_VARIANT_CREATE`, `PRODUCT_VARIANT_UPDATE`. `PRODUCT_DELETE` n'est pas ajouté car l'ancien système n'exposait aucune suppression physique.
- `VIEW_INVENTORY` → `INVENTORY_VIEW`, `INVENTORY_MOVEMENT_VIEW`; `MANAGE_INVENTORY` → `INVENTORY_INITIALIZE`, `INVENTORY_IN`, `INVENTORY_OUT`, `INVENTORY_ADJUST`.
- `VIEW_PURCHASES` → `SUPPLIER_VIEW`, `PURCHASE_VIEW`, `PURCHASE_LINE_VIEW`, `SUPPLIER_PAYMENT_VIEW`; `MANAGE_PURCHASES` → toutes les anciennes mutations fournisseur, achat, ligne et paiement listées dans la matrice.
- `USE_POS` → `SALE_CREATE`, `SALE_UPDATE`, `SALE_LINE_CREATE`, `SALE_COMPLETE`; les recherches compactes utilisent `SALE_CREATE`. `VIEW_SALES`, `MANAGE_SALES`, `MANAGE_SALE_RETURNS` sont développés vers leurs opérations exactes.
- Les anciennes permissions créances, finance, dépenses, dashboard, rentabilité et rapports sont développées vers les seules opérations indiquées ci-dessus.

Les permissions d'invitations en attente utilisent la même table. Les codes inconnus sont supprimés lors de la migration plutôt que transformés en capacité nouvelle. Les propriétaires restent implicitement autorisés sur le catalogue atomique complet. Déploiement recommandé : backend et migration de données, puis frontend atomique ; aucune migration n'est exécutée automatiquement sur une base persistante.
