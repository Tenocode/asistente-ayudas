import { useEffect, useRef, useState } from 'react'
import { iniciar, enviarMensaje } from './api.js'
import Message from './components/Message.jsx'

export default function App() {
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const finRef = useRef(null)

  // Al montar: pedir el saludo inicial y la sesión al backend.
  useEffect(() => {
    iniciar()
      .then((data) => {
        setSessionId(data.session_id)
        setMessages([{ role: 'bot', text: data.respuesta }])
      })
      .catch(() =>
        setMessages([
          {
            role: 'bot',
            text: '⚠️ No se pudo conectar con el servidor. ¿Está arrancado el backend (`python src/api.py`)?',
          },
        ]),
      )
  }, [])

  // Auto-scroll al último mensaje.
  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend() {
    const texto = input.trim()
    if (!texto || loading) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text: texto }])
    setLoading(true)

    try {
      const data = await enviarMensaje(sessionId, texto)
      setSessionId(data.session_id)
      setMessages((prev) => [
        ...prev,
        { role: 'bot', text: data.respuesta, ayudas: data.ayudas },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'bot', text: '⚠️ Error de conexión. Inténtalo de nuevo.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>Asistente de Ayudas Públicas</h1>
        <p>Subvenciones y ayudas oficiales en España · información orientativa</p>
      </header>

      <main className="chat">
        {messages.map((msg, i) => (
          <Message key={i} msg={msg} />
        ))}
        {loading && <div className="msg msg--bot msg--thinking">Buscando ayudas…</div>}
        <div ref={finRef} />
      </main>

      <footer className="composer">
        <input
          className="composer__input"
          type="text"
          placeholder="Escribe tu respuesta…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={loading}
          autoFocus
        />
        <button className="composer__btn" onClick={handleSend} disabled={loading}>
          Enviar
        </button>
      </footer>
    </div>
  )
}
