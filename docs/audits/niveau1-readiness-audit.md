# Audit de préparation Niveau 1 — Gérer

Date de l'audit : 8 octobre 2026

Périmètre : backend Django/DRF Niveau 1, hors visibilité publique et vente en ligne

Méthode : inspection des modèles, services, serializers, vues, permissions, routes, tests et documentation, puis exécution des validations globales sur PostgreSQL. Quatorze modules fonctionnels sont distingués : Authentification, Business, Members, Catalog, Inventory, Purchases, Sales, Sale Returns, Receivables, Expenses, Finance, Dashboard, Profitability et Reports.

## A. Synthèse exécutive

Le socle Niveau 1 couvre déjà l'essentiel d'un cycle commercial : catalogue, stock, achats, vente comptant ou à crédit, retours atomiques, créances, dépenses, finance et pilotage. Les règles sensibles des retours sont particulièrement bien couvertes. Les agrégats Dashboard, rentabilité et rapports sont cohérents avec les événements économiques et financiers, et la suite globale de 157 tests passe.

La plateforme n'est toutefois pas prête pour un déploiement général sans correction. Un défaut P0 permet de diminuer le montant d'une dépense en dessous de ses paiements actifs, produisant un solde négatif et un état financier incohérent. Le parcours de gestion d'équipe est bloqué par l'absence d'API d'ajout, d'invitation, de changement de rôle et de suspension des membres. Plusieurs listes opérationnelles ne sont ni paginées ni optimisées et plusieurs écritures sensibles rendent l'idempotence facultative, ce qui est inadapté aux reprises après coupure réseau.

Conclusion : **Niveau 1 partiellement prêt**. Un pilote contrôlé mono-propriétaire est techniquement envisageable après correction du P0. Un usage fiable par plusieurs commerçants et équipes nécessite les P1 de la feuille de route.

## B. Inventaire fonctionnel

Les statuts portent sur les capacités réellement accessibles par l'API, pas uniquement sur l'existence d'un modèle.

| # | Domaine | Fonctionnalité | Statut | Preuve et observation |
|---:|---|---|---|---|
| 1 | Authentification | Échange OIDC mobile | COMPLET | `accounts/views.py::CarriMobileExchangeView` valide audience, nonce et `at_hash`, puis bloque le rejeu via `IDTokenReplay`. |
| 2 | Authentification | Login web OIDC | COMPLET | Authorization Code + PKCE, état et nonce persistés, callback et handoff à usage unique dans `accounts/views.py`. |
| 3 | Authentification | Cycle de vie JWT | PARTIEL | Access 15 min et refresh 30 jours avec rotation, mais `BLACKLIST_AFTER_ROTATION=False` et aucune révocation/logout applicatif (`config/settings/base.py`). |
| 4 | Business | Création, devise CDF/USD et propriétaire initial | COMPLET | `create_business()` crée l'entreprise, l'OWNER et les valeurs par défaut; la devise devient immuable (`businesses/models.py::Business.save`). |
| 5 | Business | Mise à jour du profil et des catégories | À CORRIGER | `BusinessDetailView.patch` sauvegarde d'abord le profil puis appelle `replace_categories` sans transaction englobante; une erreur de catégories peut laisser le profil modifié malgré une réponse 400. |
| 6 | Business | Suspension/archivage opérationnel | À CORRIGER | Le statut existe, mais `businesses/views.py::accessible` et les mixins métiers filtrent seulement le membre actif, jamais `Business.status`. |
| 7 | Membres | Rôles et invariants du modèle | COMPLET | OWNER/MANAGER/EMPLOYEE, membre ACTIVE/SUSPENDED, unicité et protection du dernier OWNER actif dans `businesses/models.py`. |
| 8 | Membres | Invitation et administration par API | ABSENT | Seul `GET /businesses/{id}/members/` existe dans `businesses/urls.py`; aucune route POST/PATCH pour inviter, attribuer un rôle ou suspendre. |
| 9 | Business | Moyens de paiement | COMPLET | Liste, création, consultation et activation/désactivation; gestion OWNER/MANAGER et lecture active pour EMPLOYEE. |
| 10 | Catalogue | Taxonomie, attributs et catégories | COMPLET | Arbre limité à trois niveaux, attributs hérités typés et validation des produits/variantes. |
| 11 | Catalogue | Produits, variantes, prix, coûts et archivage | COMPLET | Prix effectif des variantes, validations tenant, statuts ACTIVE/INACTIVE/ARCHIVED et identifiants publics. |
| 12 | Catalogue | SKU et codes-barres | PARTIEL | SKU contrôlé par validation inter-tables, mais contraintes DB différentes Product/Variant; pas d'unicité DB globale Product+Variant ni normalisation persistée. Aucune unicité du barcode; le POS transforme les doublons en 409 contrôlé. |
| 13 | Catalogue | Recherche POS | COMPLET | Endpoint compact paginé, priorité public_id/barcode/SKU, recherche texte, Product/Variant, stock agrégé et conflits contrôlés. |
| 14 | Inventory | Soldes, IN/OUT/ADJUSTMENT et prévention du négatif | COMPLET | Contraintes DB et `apply_stock_movement()` atomique avec verrou de ligne et journal immuable. |
| 15 | Inventory | Stock automatique achat/vente/retour | COMPLET | Réception, vente et retour utilisent les services Inventory et des références métier; les retours archivés ont un opt-in limité. |
| 16 | Inventory | Traçabilité exposée au client | PARTIEL | `StockMovement` possède `reference_type/reference_id`, mais `StockMovementSerializer` ne les expose pas. |
| 17 | Inventory | Réservations, emplacements et transferts | ABSENT | `reserved_quantity` et `TRANSFER` existent comme fondations, sans workflow de réservation, site de stock ou transfert API. Non bloquant pour un commerce mono-site sans réservation. |
| 18 | Achats | Fournisseurs | COMPLET | Création, liste, consultation et mise à jour, isolées par Business. |
| 19 | Achats | Brouillon, lignes, confirmation, réception, annulation | COMPLET | Transitions verrouillées; réception atomique, mouvements stock et mise à jour du coût. |
| 20 | Achats | Paiements fournisseur et dette | COMPLET | Paiements partiels, plafonnement, reversal Finance et rapports de dette. |
| 21 | Ventes | Clients | PARTIEL | Création et liste uniquement; pas de détail, mise à jour, désactivation ciblée ou recherche dédiée. |
| 22 | Ventes | Brouillon modifiable | PARTIEL | En-tête modifiable et lignes ajoutables, mais aucune route de modification/suppression d'une ligne de vente; une erreur impose de recréer/annuler la vente. |
| 23 | Ventes | Finalisation, paiement et vente à crédit | COMPLET | Service atomique, verrou Sale, snapshots de coût, stock, Finance et Receivable cohérents. |
| 24 | Ventes | Retours partiels/totaux/successifs | COMPLET | Idempotence obligatoire, cumul borné, stock, crédit créance, remboursement et rollback dans une transaction unique. |
| 25 | Créances | Solde, paiements, échéance, retard et crédits retour | COMPLET | Le solde dérive des paiements et `ReceivableAdjustment.RETURN_CREDIT`; montant initial et historique restent immuables. |
| 26 | Créances | API opérationnelle de liste/paiements | PARTIEL | Filtres présents, mais liste non paginée et calculs par propriétés susceptibles de requêtes répétées par ligne. |
| 27 | Dépenses | Création, mise à jour et annulation | À CORRIGER | La modification de `amount` reste autorisée après paiements sans imposer `amount >= paid_amount`, d'où solde négatif possible. |
| 28 | Dépenses | Paiement partiel et reversal | COMPLET | Paiements immuables, plafonnement sous verrou, mouvement Finance et reversal auditable. |
| 29 | Finance | Ledger et transactions de paiement | COMPLET | Sources structurées, contraintes source/type, inflow/outflow, reversals supportés et remboursement de retour. |
| 30 | Finance | Consultation et traçabilité API | PARTIEL | La projection omet `supplier_payment` et `sale_return`; liste non paginée et relations non préchargées. |
| 31 | Pilotage | Dashboard | COMPLET | CA net des retours, flux Finance, créances ajustées, stock/achats, permissions et agrégations bornées. |
| 32 | Pilotage | Rentabilité | COMPLET | CA/COGS bruts, retours, nets, marge et résultat selon snapshots et dates économiques. |
| 33 | Rapports | Sales et Products | COMPLET | Ventes/retours agrégés séparément, périodes, Product parent, quantités nettes et pagination/limite. |
| 34 | Rapports | Expenses et Receivables | COMPLET | Soldes, crédits retour distincts des paiements, retard, clients, pagination et sous-requêtes sans double comptage. |
| 35 | Rapports | Purchases et dettes fournisseurs | COMPLET | Agrégations serveur, périodes et dette courante par fournisseur. |
| 36 | API transversale | Collections opérationnelles mobiles | PARTIEL | Nombreuses listes brutes non paginées : Businesses, Members, Products, Variants, Inventory, mouvements, Customers, Sales, Receivables, Finance, Suppliers, Purchases et paiements. |

Décompte : **23 COMPLET, 8 PARTIEL, 2 ABSENT, 3 À CORRIGER**, soit 36 fonctionnalités examinées.

### Couverture de tests observée

- Forte : retours de vente, Inventory, Finance, Dashboard, rentabilité et rapports.
- Correcte : catalogue/POS, dépenses, créances et ventes.
- Insuffisante par rapport à la complexité : achats opérationnels (permissions, isolation, concurrence, lignes dupliquées et coût final), administration des membres inexistante, statut Business non testé comme verrou global.
- Les tests transversaux vérifient un retour mixte complet, l'idempotence, Inventory, créance, Finance et les projections économiques, ainsi qu'un retour sur une période différente de la vente.

## C. Résultats des six parcours métier

| Parcours | Résultat | Appels/étapes | Étape impossible ou fragile |
|---|---|---|---|
| 1. Entreprise → configuration → membres → permissions | INCOMPLET | Création et configuration disponibles. | Impossible d'ajouter/inviter un membre, modifier son rôle ou le suspendre par API. Le statut Business n'arrête pas les opérations. |
| 2. Produit → prix → stock → disponibilité | COMPLET | Création produit puis Inventory IN; consultation Inventory ou recherche POS. | Fonctionnel. La mutation stock manuelle n'est pas idempotente et plusieurs listes ne sont pas paginées. |
| 3. Fournisseur → achat → réception → stock → dette | COMPLET | Fournisseur, achat, lignes, confirmation, réception, paiement/rapport. | Fonctionnel. Une cible répétée sur plusieurs lignes peut rendre le coût catalogue final dépendant de l'ordre; retry de paiement sûr seulement si une clé facultative a été fournie. |
| 4. POS → vente → paiement → stock → créance | COMPLET | Une recherche POS, création Sale, ajout de ligne(s), finalisation. | Fonctionnel, mais brouillon difficile à corriger, création/finalisation sans contrat d'idempotence et listes Sales/Customers non paginées. |
| 5. Retour → stock → créance → remboursement → indicateurs | COMPLET | Un POST atomique suffit; GET paginé. | Workflow le plus robuste : clé obligatoire, retry sûr, snapshots, rollback et projections validés. Pas de reversal du remboursement dans le MVP. |
| 6. Dépense → paiements → Finance → pilotage | COMPLET AVEC RISQUE P0 | Dépense, paiements/reversal, Finance, Dashboard/rentabilité. | Le chemin nominal fonctionne, mais modifier ensuite la dépense sous le total payé corrompt le solde économique. |

**Parcours complets : 5/6.** Le parcours 6 est compté complet pour son chemin nominal, sans diminuer la sévérité du défaut P0.

## D. Authentification, sécurité et intégrité

### Points solides

- Validation OIDC mobile : signature/algorithme, issuer, audience, expiration, nonce et `at_hash`; rejet du rejeu de l'ID token.
- Flux web : PKCE S256, état et nonce, tentative et handoff à durée limitée et à usage unique.
- Authentification globale DRF par JWT ecommerce et accès anonyme explicitement limité aux routes publiques.
- Isolation horizontale généralement appliquée par `business_public_id`, appartenance active et filtre de l'objet au même Business; les objets métier utilisent des identifiants publics.
- Les services sensibles de vente, achat, stock, créance, dépense et retour utilisent `transaction.atomic()` et des verrous de ligne aux points critiques.
- Les rôles sont appliqués : OWNER/MANAGER gèrent et consultent les données financières; EMPLOYEE conserve les opérations POS prévues et est refusé sur retours/rapports de gestion.

### Risques confirmés

1. La suspension ou l'archivage d'un Business n'est pas un verrou d'accès : les sélecteurs vérifient uniquement le membre actif.
2. Les refresh tokens tournent mais les anciens tokens ne sont pas blacklistés; aucun logout/révocation n'est disponible.
3. Les paiements fournisseur, créance et dépense acceptent une clé d'idempotence facultative; les mouvements Inventory manuels et la création de Sale n'en ont pas.
4. `BusinessDetailView.patch` n'est pas atomique entre le profil et les catégories.
5. La modification d'une dépense ne protège pas l'invariant montant total ≥ paiements actifs.
6. Certaines réponses exposent encore des UUID internes d'identité (`performed_by`, `created_by`) alors que la majorité du contrat privilégie les identifiants publics.

### Risques nécessitant mesure ou test supplémentaire

- La concurrence inter-tables sur un SKU Product/Variant n'est pas protégée par une contrainte DB globale; une course peut contourner la validation applicative. Un test concurrent PostgreSQL doit le démontrer avant de choisir le schéma final.
- Les listes Sales, Purchases, Receivables et Finance présentent des accès relationnels/propriétés non préchargés. Le N+1 est visible structurellement, mais son coût exact doit être mesuré avec un volume représentatif avant de fixer des budgets par endpoint.
- Les politiques de sauvegarde, restauration, supervision, rotation des secrets et capacité PostgreSQL ne résident pas dans ce dépôt; elles doivent être auditées dans l'environnement de déploiement.

## E. État des API pour Flutter

### Atouts

- Routes tenant explicites, identifiants publics, Decimal sérialisés sans float et dates ISO.
- Recherche POS compacte : un scan exact donne un appel et zéro/un article, avec conflit explicite plutôt qu'un choix arbitraire.
- Retour de vente en un seul POST idempotent, puis résultat complet; lectures de retours et rapports paginées/agrégées.
- OpenAPI valide et couvre les flux principaux; erreurs d'authentification ne divulguant pas de secrets fournisseur.

### Limites d'intégration

- Les formats d'erreur alternent entre `detail` chaîne, `detail` structuré et erreurs de champs DRF, en français et en anglais. Flutter devra actuellement normaliser plusieurs formes.
- La pagination globale DRF ne s'applique pas automatiquement aux nombreuses `APIView` qui renvoient directement un tableau.
- Les listes opérationnelles non paginées deviennent coûteuses et difficiles à synchroniser à mesure que le commerce grandit.
- L'API Client et l'édition des lignes de brouillon ne suffisent pas pour des écrans de gestion usuels.
- Le journal de stock et la liste Finance cachent certaines références source utiles à une interface d'audit.
- Les résumés Purchase/Finance et quelques erreurs OpenAPI restent décrits par des schémas génériques; deux warnings connus subsistent.

Endpoints réellement manquants pour le Niveau 1 :

1. administration des membres (inviter/ajouter, changer le rôle, suspendre/réactiver, protéger le dernier OWNER);
2. détail/mise à jour/désactivation et recherche des clients;
3. modification et suppression d'une ligne d'une Sale DRAFT;
4. mécanisme de révocation/logout JWT pour appareil perdu ou départ d'un employé.

## F. Performance et connectivité RDC

Les endpoints analytiques utilisent des agrégations séparées et gardent un nombre de requêtes constant avec le volume. Les tests existants ont mesuré : Profitability 5/5 requêtes et 373 octets, Dashboard 10/10 et 441 octets, Sales Report 6/6 et 623 octets, Products Report 4/4 et 487 octets, Receivables Report 5/5 et 2 890 octets. Les tests POS et Sale Returns GET vérifient également un coût constant. Aucun N+1 n'est détecté sur ces endpoints optimisés.

La préparation réseau reste **à améliorer** pour les écrans opérationnels : réponses non paginées, N+1 probables sur Sales/Purchases/Receivables/Finance et retries non uniformément idempotents. Une coupure après une écriture dont la clé est facultative peut inciter le mobile à répéter et dupliquer un paiement ou un mouvement manuel. Le futur offline partiel devra disposer de clés d'opération client persistantes, de curseurs/versionnement et d'une politique explicite de résolution; ces mécanismes ne sont pas encore présents.

## G. Résultats des validations

Commandes exécutées hors sandbox lorsque PostgreSQL était requis :

| Validation | Résultat |
|---|---|
| `env/bin/python -m pytest backend/apps -q --reuse-db` | **157 passed, 0 failed** en 39,10 s |
| `env/bin/python backend/manage.py check` | **PASS**, 0 problème |
| `env/bin/python backend/manage.py makemigrations --check` | **PASS**, aucun changement détecté |
| `env/bin/python backend/manage.py spectacular --file /tmp/ecommerce-openapi.yml --validate` | **PASS**, 0 erreur, 2 warnings connus |
| `git diff --check` avant création du présent document | **PASS** |

Warnings OpenAPI connus : nom d'enum multiple pour le même jeu `PaymentMethod`; collision d'`operationId` entre les deux GET des moyens de paiement Business, résolue par suffixe automatique.

## H. Fonctionnalités réellement manquantes

- Administration des membres par API : bloque le premier parcours multi-utilisateur.
- Révocation/logout des refresh tokens : nécessaire à la gestion du cycle de vie des accès.
- Outils Client et correction de ligne de brouillon : nécessaires à une exploitation POS quotidienne sans contournement.
- Réservations, emplacements et transferts : réellement absents, mais à conserver en P2 tant que le MVP cible un stock mono-site sans réservation.
- Solde de caisse/banque, ouverture et rapprochement : Finance ne fournit actuellement qu'un ledger de flux et un net de période; ne pas le présenter comme un solde bancaire.

## I. Problèmes confirmés et plan de travail priorisé

Chaque lot ci-dessous est autonome, testable et peut faire l'objet d'un commit distinct.

| ID | Priorité | Module | Problème et preuve | Impact métier | Correction recommandée | Tests nécessaires |
|---|---|---|---|---|---|---|
| P0-01 | P0 | Expenses | `ExpenseDetail.patch` accepte tout montant positif; `Expense.clean` n'impose pas `amount >= paid_amount`; `balance = amount - paid_amount`. | Solde négatif, statut faux et incohérence reporting/Finance après paiement. | Verrouiller la dépense lors du PATCH et refuser un montant inférieur aux paiements actifs non reversés; préserver l'atomicité. | Montant égal/supérieur accepté, inférieur refusé, concurrence PATCH/paiement, reports inchangés après refus. |
| P1-01 | P1 | Members | `businesses/urls.py` n'expose que le GET membres. | Une entreprise ne peut pas constituer son équipe via l'application. | Ajouter des endpoints OWNER pour invitation/ajout, rôle, suspension/réactivation, avec identité Carri et invariant dernier OWNER. | Rôles, suspension, dernier OWNER, isolation et concurrence. |
| P1-02 | P1 | Business/Security | `accessible()` et les mixins filtrent le membre mais pas `Business.status`. | Une entreprise suspendue/archivée continue à vendre et muter ses données. | Centraliser un scope Business actif et définir les opérations encore lisibles après suspension. | Chaque famille d'endpoint sur ACTIVE/SUSPENDED/ARCHIVED. |
| P1-03 | P1 | Business | Profil sauvegardé avant `replace_categories()` sans transaction dans `BusinessDetailView.patch`. | Réponse d'échec avec mise à jour partielle silencieuse. | Transaction unique et verrou Business pour profil + catégories. | Échec catégorie avec rollback intégral; concurrence de deux PATCH. |
| P1-04 | P1 | API/Flutter | Collections `APIView` renvoyées intégralement dans plusieurs domaines. | Payload croissant, latence et coût data élevés, risque mémoire mobile. | Pagination homogène avec limite maximale, ordre stable et compatibilité documentée. | Pages, limites, ordre, isolation, taille petit/grand dataset. |
| P1-05 | P1 | Sales/Purchases/Receivables/Finance | Querysets de liste sans préchargements; propriétés `total`, `paid_amount`, `balance` agrègent par objet. | N+1 et latence croissante. | Annotations/sous-requêtes indépendantes et `select_related/prefetch_related`, puis budgets SQL. | Nombre de requêtes petit/grand constant et exactitude avec plusieurs paiements/lignes. |
| P1-06 | P1 | Écritures réseau | Idempotency-Key facultative sur paiements fournisseur/créance/dépense; absente des mouvements manuels et création Sale. | Retry mobile après timeout pouvant dupliquer l'opération ou créer un état ambigu. | Rendre la clé obligatoire pour écritures financières/stock à risque et définir le même contrat 200/201/409. | Même clé/payload, conflit, timeout simulé, concurrence même clé. |
| P1-07 | P1 | Auth | Rotation JWT sans blacklist et aucune route de logout/révocation. | Token d'un appareil perdu ou ancien refresh réutilisable jusqu'à 30 jours. | Activer une stratégie de révocation compatible et fournir logout appareil/session. | Ancien refresh refusé après rotation/logout, autres appareils selon politique. |
| P1-08 | P1 | Sales | `sales/urls.py` n'a pas de détail de SaleLine; `Lines` supporte GET/POST seulement. | Impossible de corriger proprement une ligne DRAFT. | Ajouter PATCH/DELETE tenant-scopés, uniquement DRAFT, avec recalcul serveur. | Modifier/supprimer, terminal immutable, isolation, doublon cible. |
| P1-09 | P1 | Purchases | Aucune unicité PurchaseLine par cible; réception ordonnée par `public_id` écrase successivement `cost_price`. | Coût catalogue final non déterminé métier pour deux lignes du même article. | Refuser la cible dupliquée ou définir une règle de coût pondéré explicite. | Product/Variant dupliqué, réception et coût attendu, migration de données si nécessaire. |
| P1-10 | P1 | Catalog/POS | Barcode sans unicité; SKU global Product+Variant seulement validé applicativement et sans normalisation persistée. | Scan en conflit et course concurrente possible; saisies équivalentes divergent. | Nettoyer les données, normaliser trim/uppercase SKU et trim barcode, puis garantir l'unicité vendable par Business avec une stratégie inter-tables. | Audit doublons, normalisation, concurrence, produits archivés et erreurs 409. |
| P1-11 | P1 | Inventory/Finance | Serializers omettent les références SaleReturn/SupplierPayment et `reference_type/reference_id`. | Audit mobile incomplet d'un mouvement de stock ou financier. | Exposer uniquement les identifiants publics et types de source, sans objets complets. | Chaque source, isolation et budget payload/N+1. |
| P1-12 | P1 | Customers | API limitée à GET liste/POST. | Maintenance des coordonnées et recherche client impraticables à volume réel. | Détail, PATCH, statut actif et recherche paginée compacte. | Permissions POS, isolation, filtres, pagination et historique des ventes. |
| P1-13 | P1 | Purchases/QA | Peu de tests opérationnels au regard des transitions, permissions, paiements et concurrence. | Régressions possibles sur dette, stock et isolation. | Compléter les tests avant optimisation/refonte des achats. | Matrice rôles, tenant, transitions, rollback, idempotence, reversal et verrous. |
| P2-01 | P2 | API | Formes/langues d'erreur hétérogènes. | Parsing Flutter et messages utilisateur plus complexes. | Définir une enveloppe `code/detail/fields` stable et des codes métier. | Matrice 400/401/403/404/409 et compatibilité progressive. |
| P2-02 | P2 | OpenAPI | Deux warnings connus et plusieurs réponses `dict` génériques. | SDK moins précis et collision de noms générés. | Noms d'énum/operationId explicites et serializers de réponse dédiés. | Validation sans nouveau warning et génération d'un client test. |
| P2-03 | P2 | Inventory | Pas de location, réservation ou transfert effectif. | Limite les commerces multi-sites et la future vente réservée. | Concevoir seulement après validation du besoin; ne pas greffer au solde actuel sans modèle de location. | Réservation concurrente, transfert atomique et disponibilité par site. |
| P2-04 | P2 | Finance | Résumé de flux sans compte, solde initial ni rapprochement. | Ne peut pas remplacer une caisse ou un relevé bancaire. | Définir ultérieurement comptes, soldes d'ouverture et rapprochement, en conservant le ledger immuable. | Soldes par compte, clôture, écarts et migrations contrôlées. |

Décompte des problèmes confirmés : **18** — **P0 : 1, P1 : 13, P2 : 4**.

## J. Feuille de route recommandée

1. **Lot 1 — Intégrité Expense (P0-01).** Corriger l'invariant, ajouter tests de concurrence et relancer toute la suite.
2. **Lot 2 — Suspension Business et session (P1-02, P1-07).** Définir le verrou de tenant, appliquer à toutes les routes, puis implémenter la révocation JWT.
3. **Lot 3 — Équipe Business (P1-01).** Livrer l'administration minimale des membres et rendre le parcours 1 complet.
4. **Lot 4 — Reprises réseau sûres (P1-06).** Uniformiser l'idempotence des écritures financières, stock et création de vente.
5. **Lot 5 — Cohérence transactionnelle et achats (P1-03, P1-09, P1-13).** PATCH Business atomique, règle de ligne d'achat et couverture de tests.
6. **Lot 6 — Exploitation POS (P1-08, P1-12).** Édition des lignes DRAFT et gestion/recherche clients.
7. **Lot 7 — Données catalogue (P1-10).** Audit/nettoyage, décision d'unicité inter-tables, migration et contraintes.
8. **Lot 8 — API mobile à volume (P1-04, P1-05, P1-11).** Pagination, suppression des N+1 et traçabilité compacte avec budgets SQL/payload.
9. **Lot 9 — Contrat développeur (P2-01, P2-02).** Erreurs stables et OpenAPI sans ambiguïtés.
10. **Lots ultérieurs (P2-03, P2-04).** Multi-site/réservations et comptabilité de caisse seulement après cadrage métier; ne pas les inclure implicitement dans le MVP actuel.

## Conclusion

Le backend a une architecture métier cohérente et une couverture de tests remarquable sur les workflows financiers les plus récents. Il peut soutenir une démonstration ou un pilote restreint, mais pas encore un déploiement Niveau 1 général auprès de vrais commerçants. La correction du P0 est préalable à toute donnée financière réelle; la gestion des membres, le verrou du statut Business, l'idempotence réseau et la maîtrise des listes sont nécessaires pour qualifier le MVP de fiable.

**Décision : NIVEAU 1 PARTIELLEMENT PRÊT.**
