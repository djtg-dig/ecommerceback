# Adresses internationales des entreprises

Le module `businesses` fournit un référentiel géographique et une adresse principale optionnelle par entreprise.

## Modèles

- `Country` : pays ISO 3166-1 alpha-2 (`iso2` unique et normalisé en majuscules) et indicatif international.
- `AdministrativeArea` : subdivision propre à un pays, unique par paire pays/nom.
- `Locality` : ville ou localité propre à une subdivision, unique par paire subdivision/nom.
- `Address` : pays obligatoire, subdivision/localité optionnelles, champs libres (`state`, `city`, rue, quartier, code postal et complément) et coordonnées GPS optionnelles.

Une subdivision doit appartenir au pays sélectionné et une localité à la subdivision sélectionnée. Les champs libres restent utilisables quand le référentiel local n'est pas encore importé. Si un champ libre et son équivalent structuré sont fournis ensemble, leurs noms doivent correspondre. Latitude et longitude sont respectivement limitées à `[-90, 90]` et `[-180, 180]`.

`Business.structured_address` est optionnel, ce qui préserve les entreprises historiques. Les champs texte historiques `Business.address` et `Business.zone` restent inchangés pour préserver le contrat API existant.

## Retrait progressif du champ historique

`structured_address` est l'unique source d'écriture pour les créations et modifications d'entreprise. Le champ texte historique `address` reste **en lecture seule** dans les réponses pendant la période de transition ; il n'est plus accepté comme donnée d'écriture. Les consommateurs doivent basculer vers `structured_address`.

Avant toute suppression du champ, exécuter l'audit sans effet de bord :

```bash
cd backend
../env/bin/python manage.py audit_legacy_business_addresses
```

Le rapport indique les entreprises analysées, déjà structurées, converties, à vérifier manuellement et sans adresse. Aucun pays ou niveau administratif n'est déduit d'un texte historique. Lorsqu'un opérateur a vérifié le pays d'une entreprise précise, il peut conserver le texte sans perte dans `Address.additional_information` :

```bash
../env/bin/python manage.py audit_legacy_business_addresses \
  --apply --business-public-id BUSINESS_PUBLIC_ID --country-iso2 CD
```

Cette conversion crée uniquement `structured_address`; elle ne vide pas le texte historique. Le champ `address` ne pourra être supprimé que lorsque le rapport ne contient plus d'entreprise à vérifier et que tous les consommateurs de lecture auront migré.

## Référentiel et commande

Le fichier versionné `backend/apps/businesses/data/countries.json` contient les 249 entrées ISO 3166-1 alpha-2 et leurs indicatifs disponibles. Il est importé localement, sans accès réseau :

```bash
cd backend
../env/bin/python manage.py populate_countries
```

La commande valide le fichier puis utilise `iso2` comme clé stable. Elle est idempotente et affiche les nombres de pays créés, mis à jour et inchangés. Elle ne supprime jamais les pays absents du fichier.

## API de géographie

Ces endpoints sont publics et en lecture seule.

| Méthode | URL | Paramètres |
| --- | --- | --- |
| GET | `/api/v1/countries/` | `search` facultatif, par nom ou ISO2 |
| GET | `/api/v1/administrative-areas/` | `country_id` obligatoire, `search` facultatif |
| GET | `/api/v1/localities/` | `administrative_area_id` obligatoire, `search` facultatif |

Un filtre absent ou invalide pour les subdivisions/localités produit `400` avec l'erreur sur le paramètre concerné.

## Création et mise à jour d'une entreprise

`POST /api/v1/businesses/` accepte `structured_address` dans le même corps que les champs commerciaux existants. L'opération est atomique : l'adresse et l'entreprise sont créées ensemble ou aucune des deux n'est conservée.

```json
{
  "name": "Entreprise Exemple",
  "primary_currency": "CDF",
  "sales_location_type": "PHYSICAL_STORE",
  "sales_channel": "BOTH",
  "delivery_methods": ["PICKUP"],
  "structured_address": {
    "country_id": 1,
    "administrative_area_id": 12,
    "locality_id": 42,
    "state": "Kinshasa",
    "city": "Gombe",
    "neighborhood": "Gombe",
    "street": "Avenue Exemple",
    "street_number": "12",
    "postal_code": "",
    "additional_information": "Près du marché",
    "latitude": -4.325,
    "longitude": 15.322
  }
}
```

Les réponses de liste, détail, création et modification contiennent `structured_address` avec les objets pays, subdivision et localité. `PATCH /api/v1/businesses/{public_id}/` applique les mêmes permissions `BUSINESS_UPDATE` que l'entreprise et modifie l'adresse déjà associée au lieu d'en créer une seconde. Un utilisateur sans cette permission reçoit `403`; une entreprise hors de sa portée n'est pas modifiable.

Pendant la transition, le champ `address` peut encore être présent dans les réponses pour les clients historiques mais n'est plus inscriptible. Les détails d'invitation ajoutent `business_structured_address`; leur ancien champ `business_address` est calculé depuis cette adresse lorsqu'elle existe, puis utilise le texte historique uniquement comme repli.

Les erreurs de validation géographique retournent `400`, structurées sous `structured_address`. Les entreprises sans adresse structurée restent valides et retournent `structured_address: null`.
