import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const port = process.env.PORT || 8000

export default defineConfig({
    plugins: [react()],
    server: {
          port: 5173,
          proxy: {
                  '/api': { target: `http://127.0.0.1:${port}`, changeOrigin: true },
          },
    },
    build: { outDir: 'dist', sourcemap: false },
})
