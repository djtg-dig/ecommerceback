# Référentiel des pays

`countries.json` est un jeu de données versionné de 249 entrées ISO 3166-1 alpha-2. Les codes ISO suivent le référentiel ISO 3166-1; les indicatifs suivent la recommandation ITU-T E.164 et peuvent être partagés par plusieurs territoires.

Il est volontairement chargé par la commande Django `populate_countries` plutôt que téléchargé à l'exécution. Toute actualisation doit conserver `iso2` comme identifiant stable, les caractères Unicode et le comportement idempotent de la commande.
