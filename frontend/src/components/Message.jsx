import ReactMarkdown from 'react-markdown'
import AyudaCard from './AyudaCard.jsx'

// Una burbuja del chat. El usuario va como texto plano; el bot se renderiza
// como Markdown (negritas, listas) y, si la respuesta trae ayudas, se pintan
// debajo como tarjetas con enlace a la fuente oficial.
export default function Message({ msg }) {
  const { role, text, ayudas } = msg

  if (role === 'user') {
    return <div className="msg msg--user">{text}</div>
  }

  return (
    <div className="msg msg--bot">
      <div className="msg__text">
        <ReactMarkdown>{text}</ReactMarkdown>
      </div>
      {ayudas?.length > 0 && (
        <div className="ayudas">
          {ayudas.map((ayuda, i) => (
            <AyudaCard key={i} ayuda={ayuda} />
          ))}
        </div>
      )}
    </div>
  )
}
