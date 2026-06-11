from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatoFuente:
    """URL candidata descubierta manualmente o con ayuda de investigacion."""

    nombre: str
    ambito: str
    categoria: str
    url_oficial: str          # URL que se muestra al usuario (página de la convocatoria)
    tipo_fuente: str = "auto"
    organismo: str | None = None
    url_tramite: str | None = None
    url_descarga: str | None = None  # URL real para descargar el documento (si difiere de url_oficial)
    notas: str | None = None
    texto_inline: str | None = None  # texto ya extraído (ej. desde API BDNS); evita descarga


@dataclass(frozen=True)
class FuenteExtraida:
    """Fuente oficial ya descargada y convertida a texto indexable."""

    nombre: str
    ambito: str
    categoria: str
    url_oficial: str
    tipo_fuente: str
    texto_extraido: str
    organismo: str | None = None
    url_tramite: str | None = None
    origen_archivo: str | None = None
