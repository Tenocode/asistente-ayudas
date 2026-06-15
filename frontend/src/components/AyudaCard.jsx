// Tarjeta de una ayuda: título, etiqueta de estado y botón clicable a la fuente
// oficial (PDF o web). Los detalles (importe, plazo, requisitos) van en el texto
// explicado por el LLM; la tarjeta aporta el estado de un vistazo y el enlace.

const ESTADOS = {
  abierta: { etiqueta: 'Abierta', clase: 'badge-abierta' },
  cerrada: { etiqueta: 'Cerrada', clase: 'badge-cerrada' },
  desconocida: { etiqueta: 'Plazo sin confirmar', clase: 'badge-desconocida' },
}

function formatearFecha(iso) {
  if (!iso) return null
  const [anio, mes, dia] = iso.split('-')
  return `${dia}/${mes}/${anio}`
}

export default function AyudaCard({ ayuda }) {
  const estado = ESTADOS[ayuda.estado] ?? ESTADOS.desconocida
  const fecha = formatearFecha(ayuda.fecha_fin)
  const esPdf = ayuda.tipo_fuente === 'pdf'

  return (
    <article className="ayuda-card">
      <div className="ayuda-card__head">
        <h3 className="ayuda-card__title">{ayuda.nombre}</h3>
        <span className={`badge ${estado.clase}`}>{estado.etiqueta}</span>
      </div>

      {ayuda.estado === 'cerrada' && fecha && (
        <p className="ayuda-card__meta">Cerró el {fecha} · suele reabrirse cada año</p>
      )}

      {ayuda.url_oficial ? (
        <a
          className="ayuda-card__link"
          href={ayuda.url_oficial}
          target="_blank"
          rel="noopener noreferrer"
        >
          {esPdf ? '📄 Ver convocatoria (PDF)' : '🔗 Ver convocatoria oficial'} →
        </a>
      ) : (
        <span className="ayuda-card__nolink">Sin enlace oficial registrado</span>
      )}
    </article>
  )
}
