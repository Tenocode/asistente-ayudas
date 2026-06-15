// Capa fina sobre fetch para hablar con el backend FastAPI.
// Las rutas son relativas (/inicio, /chat): en dev las reenvía el proxy de Vite
// a :8000; en producción se servirían desde el mismo origen.

export async function iniciar() {
  const res = await fetch('/inicio')
  if (!res.ok) throw new Error('No se pudo iniciar la sesión')
  return res.json() // { session_id, respuesta }
}

export async function enviarMensaje(sessionId, mensaje) {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, mensaje }),
  })
  if (!res.ok) throw new Error('Error al enviar el mensaje')
  return res.json() // { session_id, respuesta, ayudas }
}
