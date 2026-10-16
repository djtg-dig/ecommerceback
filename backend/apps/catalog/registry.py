"""Code-defined product taxonomy used by all newly classified products."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class AttributeSpec:
    code: str
    label: str
    type: str = "string"
    required: bool = False
    unit: str = ""
    options: tuple[str, ...] = ()
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    variant: bool = False

    def public(self):
        value = asdict(self)
        value["options"] = list(self.options)
        value["min_value"] = str(self.min_value) if self.min_value is not None else None
        value["max_value"] = str(self.max_value) if self.max_value is not None else None
        return value


@dataclass(frozen=True)
class CategorySpec:
    code: str
    label: str
    parent: str
    attributes: tuple[AttributeSpec, ...]
    description: str = ""

    def public(self, *, include_attributes=False):
        value = {"code": self.code, "label": self.label, "parent": self.parent, "description": self.description}
        if include_attributes:
            value["attributes"] = [attribute.public() for attribute in self.attributes]
        return value


def A(code, label, type="string", *, required=False, unit="", options=(), minimum=None, maximum=None, variant=False):
    return AttributeSpec(code, label, type, required, unit, tuple(options), Decimal(str(minimum)) if minimum is not None else None, Decimal(str(maximum)) if maximum is not None else None, variant)


BRAND = A("brand", "Marque")
MODEL = A("model", "Modèle")
COLOR = A("color", "Couleur")
TARGET = A("target_audience", "Public cible", "select", options=("women", "men", "children", "unisex"))


def C(code, label, parent, *attributes, description=""):
    return CategorySpec(code, label, parent, tuple(attributes), description)


_CATEGORIES = (
    C("televisions", "Téléviseurs", "electronics", BRAND, MODEL, A("screen_size", "Taille de l’écran", "decimal", required=True, unit="inch", minimum=1, maximum=200), A("display_technology", "Technologie d’affichage", "select", options=("LED", "QLED", "OLED", "MINI_LED", "OTHER")), A("resolution", "Résolution", "select", options=("HD", "FULL_HD", "4K", "8K", "OTHER")), A("smart_tv", "Smart TV", "boolean"), A("operating_system", "Système d’exploitation"), A("wifi", "Wi-Fi", "boolean"), A("bluetooth", "Bluetooth", "boolean"), A("hdmi_ports", "Ports HDMI", "integer", minimum=0, maximum=20), A("usb_ports", "Ports USB", "integer", minimum=0, maximum=20), COLOR),
    C("smartphones", "Smartphones", "electronics", BRAND, MODEL, A("screen_size", "Taille d’écran", "decimal", unit="inch", minimum=1, maximum=20), A("ram", "RAM", "integer", unit="GB", minimum=1), A("storage", "Stockage", "integer", unit="GB", minimum=1, variant=True), A("battery_capacity", "Capacité de batterie", "integer", unit="mAh", minimum=100), A("operating_system", "Système d’exploitation"), A("network", "Réseau", "select", options=("3G", "4G", "5G")), A("sim_count", "Nombre de SIM", "integer", minimum=1, maximum=4), A("esim", "Compatibilité eSIM", "boolean"), A("main_camera", "Caméra principale", "decimal", unit="MP", minimum=0), COLOR),
    C("feature_phones", "Téléphones classiques", "electronics", BRAND, MODEL, A("sim_count", "Nombre de SIM", "integer", minimum=1, maximum=4), A("battery_capacity", "Capacité de batterie", "integer", unit="mAh", minimum=100), A("network", "Réseau"), COLOR),
    C("game_consoles", "Consoles de jeux", "electronics", A("manufacturer", "Fabricant"), MODEL, A("generation", "Génération"), A("edition", "Édition"), A("storage", "Stockage", "integer", unit="GB", minimum=1, variant=True), A("disc_drive", "Lecteur de disque", "boolean"), COLOR, A("controllers_included", "Manettes incluses", "integer", minimum=0, maximum=10)),
    C("tv_accessories", "Accessoires TV", "electronics", A("accessory_type", "Type", "select", required=True, options=("REMOTE", "WALL_MOUNT", "HDMI_CABLE", "ANTENNA", "DECODER", "OTHER")), BRAND, MODEL, A("compatibility", "Compatibilité", "multi_select"), A("connector", "Connectique"), A("cable_length", "Longueur du câble", "decimal", unit="m", minimum=0), COLOR),
    C("laptops", "Ordinateurs portables", "computing", BRAND, MODEL, A("processor", "Processeur"), A("ram", "RAM", "integer", unit="GB", minimum=1, variant=True), A("storage", "Stockage", "integer", unit="GB", minimum=1, variant=True), A("storage_type", "Type de stockage", "select", options=("SSD", "HDD", "EMMC", "OTHER")), A("screen_size", "Taille d’écran", "decimal", unit="inch", minimum=1), A("resolution", "Résolution"), A("graphics", "Carte graphique"), A("operating_system", "Système d’exploitation"), COLOR),
    C("desktop_computers", "Ordinateurs de bureau", "computing", BRAND, MODEL, A("processor", "Processeur"), A("ram", "RAM", "integer", unit="GB", minimum=1), A("storage", "Stockage", "integer", unit="GB", minimum=1), A("graphics", "Carte graphique"), A("operating_system", "Système d’exploitation")),
    C("computer_accessories", "Accessoires informatiques", "computing", A("accessory_type", "Type", "select", required=True, options=("MOUSE", "KEYBOARD", "CHARGER", "WEBCAM", "HEADSET", "USB_HUB", "OTHER")), BRAND, MODEL, A("connectivity", "Connectivité", "multi_select"), A("compatibility", "Compatibilité", "multi_select"), A("power", "Puissance", "decimal", unit="W", minimum=0), COLOR),
    C("printers", "Imprimantes", "computing", BRAND, MODEL, A("print_technology", "Technologie d’impression"), A("color_mode", "Mode couleur", "select", options=("COLOR", "MONOCHROME")), A("connectivity", "Connectivité", "multi_select"), A("paper_formats", "Formats de papier", "multi_select")),
    C("computer_components", "Composants informatiques", "computing", A("component_type", "Type", "select", required=True, options=("RAM", "SSD", "HDD", "GPU", "CPU", "MOTHERBOARD", "OTHER")), BRAND, MODEL, A("capacity", "Capacité"), A("interface", "Interface"), A("compatibility", "Compatibilité", "multi_select")),
    C("shoes", "Chaussures", "fashion", BRAND, MODEL, A("shoe_type", "Type", "select", options=("SNEAKERS", "FORMAL", "SANDALS", "BOOTS", "OTHER")), A("size", "Pointure", "decimal", required=True, minimum=1, maximum=60, variant=True), A("size_system", "Système de pointure", "select", options=("EU", "UK", "US")), COLOR, A("material", "Matière"), TARGET),
    C("clothing", "Vêtements", "fashion", A("clothing_type", "Type", "select", required=True, options=("SHIRT", "TROUSERS", "DRESS", "JACKET", "TSHIRT", "OTHER")), BRAND, A("size", "Taille", "string", variant=True), A("size_system", "Système de taille"), COLOR, A("material", "Matière"), A("fit", "Coupe"), TARGET),
    C("bags", "Sacs", "fashion", A("bag_type", "Type"), BRAND, A("material", "Matière"), COLOR, A("dimensions", "Dimensions"), A("capacity", "Capacité", "decimal", unit="L", minimum=0)),
    C("watches", "Montres", "fashion", BRAND, MODEL, A("watch_type", "Type", "select", options=("ANALOG", "DIGITAL", "SMART")), A("material", "Matière"), COLOR, A("connectivity", "Connectivité", "multi_select")),
    C("air_conditioners", "Climatisations", "appliances", BRAND, MODEL, A("unit_type", "Type", "select", options=("SPLIT", "PORTABLE", "WINDOW", "OTHER")), A("cooling_capacity", "Puissance", "integer", required=True, unit="BTU/h", minimum=1000), A("inverter", "Technologie inverter", "boolean"), A("power_consumption", "Consommation électrique", "decimal", unit="W", minimum=0), A("voltage", "Tension", "decimal", unit="V", minimum=0), A("refrigerant", "Réfrigérant"), A("recommended_area", "Surface recommandée", "decimal", unit="m²", minimum=0)),
    C("refrigerators", "Réfrigérateurs", "appliances", BRAND, MODEL, A("unit_type", "Type"), A("capacity", "Capacité", "decimal", unit="L", minimum=1), A("door_count", "Nombre de portes", "integer", minimum=1), A("power_consumption", "Consommation électrique", "decimal", unit="W", minimum=0), A("inverter", "Technologie inverter", "boolean"), COLOR),
    C("freezers", "Congélateurs", "appliances", BRAND, MODEL, A("unit_type", "Type"), A("capacity", "Capacité", "decimal", unit="L", minimum=1), A("power_consumption", "Consommation électrique", "decimal", unit="W", minimum=0)),
    C("washing_machines", "Machines à laver", "appliances", BRAND, MODEL, A("capacity", "Capacité", "decimal", unit="kg", minimum=1), A("loading_type", "Type de chargement", "select", options=("FRONT", "TOP")), A("spin_speed", "Vitesse d’essorage", "integer", unit="rpm", minimum=0), A("power_consumption", "Consommation électrique", "decimal", unit="W", minimum=0)),
    C("fans", "Ventilateurs", "appliances", BRAND, MODEL, A("fan_type", "Type"), A("diameter", "Diamètre", "decimal", unit="cm", minimum=1), A("power", "Puissance", "decimal", unit="W", minimum=0), A("speed_count", "Nombre de vitesses", "integer", minimum=1)),
    C("furniture", "Meubles", "home", A("furniture_type", "Type", required=True), A("material", "Matière"), A("dimensions", "Dimensions"), COLOR, A("assembly_required", "Montage requis", "boolean")),
    C("food", "Produits alimentaires", "general", BRAND, A("food_type", "Type"), A("net_weight", "Poids net", "decimal", unit="g", minimum=0), A("expiry_date", "Date d’expiration", "string"), A("ingredients", "Ingrédients", "multi_select")),
    C("construction_materials", "Matériaux de construction", "home", A("material_type", "Type", required=True), BRAND, A("dimensions", "Dimensions"), A("weight", "Poids", "decimal", unit="kg", minimum=0), A("grade", "Qualité ou norme")),
    C("tools", "Outils", "home", A("tool_type", "Type", required=True), BRAND, MODEL, A("power_source", "Source d’énergie"), A("power", "Puissance", "decimal", unit="W", minimum=0)),
    C("kitchenware", "Articles de cuisine", "home", A("item_type", "Type", required=True), BRAND, A("material", "Matière"), A("capacity", "Capacité", "decimal", unit="L", minimum=0), COLOR),
    C("hygiene_products", "Produits d’hygiène", "general", A("product_type", "Type", required=True), BRAND, A("volume", "Contenance", "decimal", unit="ml", minimum=0), A("target_audience", "Public cible")),
    C("school_supplies", "Fournitures scolaires", "general", A("supply_type", "Type", required=True), BRAND, COLOR, A("pack_quantity", "Quantité par lot", "integer", minimum=1)),
    C("books", "Livres", "general", A("author", "Auteur"), A("isbn", "ISBN"), A("publisher", "Éditeur"), A("language", "Langue"), A("page_count", "Nombre de pages", "integer", minimum=1)),
    C("toys", "Jouets", "general", A("toy_type", "Type"), BRAND, A("minimum_age", "Âge minimum", "integer", unit="years", minimum=0), A("material", "Matière")),
    C("sports_equipment", "Équipements sportifs", "general", A("sport", "Sport", required=True), A("equipment_type", "Type"), BRAND, A("size", "Taille", variant=True), A("material", "Matière")),
    C("automotive_parts", "Pièces automobiles", "general", A("part_type", "Type", required=True), BRAND, MODEL, A("vehicle_compatibility", "Compatibilité véhicule", "multi_select"), A("part_number", "Référence fabricant")),
    C("agricultural_products", "Produits agricoles", "general", A("product_type", "Type", required=True), A("variety", "Variété"), A("origin", "Origine"), A("weight", "Poids", "decimal", unit="kg", minimum=0), A("harvest_date", "Date de récolte")),
    C("other_products", "Autres produits", "general", A("product_type", "Type"), BRAND, MODEL, COLOR),
)

CATEGORY_REGISTRY = {category.code: category for category in _CATEGORIES}


def get_category(code):
    return CATEGORY_REGISTRY.get((code or "").strip())


def list_categories():
    return sorted(CATEGORY_REGISTRY.values(), key=lambda item: (item.parent, item.label.casefold(), item.code))


def validate_registry():
    if len(CATEGORY_REGISTRY) != len(_CATEGORIES):
        raise RuntimeError("Les codes de catégories Python doivent être uniques.")
    for category in _CATEGORIES:
        codes = [attribute.code for attribute in category.attributes]
        if len(codes) != len(set(codes)):
            raise RuntimeError(f"Codes d’attributs dupliqués pour {category.code}.")
        for attribute in category.attributes:
            if attribute.type not in {"string", "integer", "decimal", "boolean", "select", "multi_select"}:
                raise RuntimeError(f"Type d’attribut inconnu : {attribute.type}.")


def validate_attributes(category_code, values, *, variant=False):
    category = get_category(category_code)
    if category is None:
        raise ValidationError({"category_code": "Catégorie Python inconnue."})
    if not isinstance(values, dict):
        raise ValidationError({"attributes": "Les caractéristiques doivent former un objet."})
    definitions = {item.code: item for item in category.attributes if item.variant == variant}
    unknown = set(values) - set(definitions)
    if unknown:
        raise ValidationError({"attributes": f"Caractéristique non autorisée : {sorted(unknown)[0]}."})
    missing = [item.code for item in definitions.values() if item.required and item.code not in values]
    if missing:
        raise ValidationError({"attributes": f"Caractéristique obligatoire manquante : {missing[0]}."})
    normalized = {}
    for code, value in values.items():
        spec = definitions[code]
        if spec.type == "boolean":
            if type(value) is not bool:
                raise ValidationError({"attributes": f"{code} doit être un booléen."})
            normalized[code] = value
        elif spec.type == "integer":
            if type(value) is not int:
                raise ValidationError({"attributes": f"{code} doit être un entier."})
            normalized[code] = value
        elif spec.type == "decimal":
            try:
                number = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError({"attributes": f"{code} doit être un nombre."}) from exc
            if isinstance(value, bool) or not number.is_finite():
                raise ValidationError({"attributes": f"{code} doit être un nombre fini."})
            normalized[code] = str(number)
        elif spec.type == "string":
            if not isinstance(value, str):
                raise ValidationError({"attributes": f"{code} doit être un texte."})
            normalized[code] = value.strip()
        elif spec.type == "select":
            if not isinstance(value, str) or value not in spec.options:
                raise ValidationError({"attributes": f"Option inconnue pour {code}."})
            normalized[code] = value
        else:
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValidationError({"attributes": f"{code} doit être une liste de textes."})
            if spec.options and any(item not in spec.options for item in value):
                raise ValidationError({"attributes": f"Option inconnue pour {code}."})
            normalized[code] = list(dict.fromkeys(value))
        if spec.required and normalized[code] in ("", []):
            raise ValidationError({"attributes": f"{code} ne peut pas être vide."})
        if spec.type in {"integer", "decimal"}:
            number = Decimal(str(normalized[code]))
            if (spec.min_value is not None and number < spec.min_value) or (
                spec.max_value is not None and number > spec.max_value
            ):
                raise ValidationError({"attributes": f"Valeur hors limites pour {code}."})
    return normalized


validate_registry()
