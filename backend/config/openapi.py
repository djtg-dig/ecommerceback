"""Extensions de schéma OpenAPI propres à l'API Ecommerce."""

from drf_spectacular.openapi import AutoSchema


class EcommerceAutoSchema(AutoSchema):
    """Conserve les noms de paramètres de chemin dans les operationId implicites.

    Certaines routes publiques sont des alias légitimes ou ne se distinguent que
    par leur paramètre. Les inclure évite une collision sans modifier ces URLs.
    Les operationId explicitement fournis par ``extend_schema`` restent prioritaires.
    """

    def _tokenize_path(self):
        path = self.path[len(self.path_prefix):].rstrip("/").lstrip("/")
        return [
            token.strip("{}").replace("-", "_")
            for token in path.split("/")
            if token
        ]
