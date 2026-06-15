import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El front (puerto 5173) reenvía las llamadas de la API al backend FastAPI
// (puerto 8000) vía proxy, así no hay problemas de CORS en desarrollo: el
// navegador habla solo con 5173 y Vite hace de intermediario hacia 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/inicio': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
    },
  },
})
