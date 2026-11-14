# Adresses internationales des entreprises

Le module `businesses` fournit un référentiel géographique et une adresse principale optionnelle par entreprise.

## Modèles

- `Country` : pays ISO 3166-1 alpha-2 (`iso2` unique et normalisé en majuscules) et indicatif international.
- `AdministrativeArea` : subdivision propre à un pays, unique par paire pays/nom.
- `Locality` : ville ou localité propre à une subdivision, unique par paire subdivision/nom.
- `Address` : pays obligatoire, subdivision/localité optionnelles, champs libres (`state`, `city`, rue, quartier, code postal et complément) et coordonnées GPS optionnelles.

Une subdivision doit appartenir au pays sélectionné et une localité à la subdivision sélectionnée. Les champs libres restent utilisables quand le référentiel local n'est pas encore importé. Si un champ libre et son équivalent structuré sont fournis ensemble, leurs noms doivent correspondre. Latitude et longitude sont respectivement limitées à `[-90, 90]` et `[-180, 180]`.

`Business.structured_address` est optionnel, ce qui préserve les entreprises historiques. Les champs texte historiques `Business.address` et `Business.zone` restent inchangés pour préserver le contrat API existant.

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

Les erreurs de validation géographique retournent `400`, structurées sous `structured_address`. Les entreprises sans adresse structurée restent valides et retournent `structured_address: null`.
