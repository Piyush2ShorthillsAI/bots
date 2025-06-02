// Heygen-Video-Generator/vite.config.ts
import { defineConfig } from 'vite'
// import react from '@vitejs/plugin-react' // If you are using React
// import tsconfigPaths from 'vite-tsconfig-paths' // If you are using tsconfigPaths

export default defineConfig({
  // Your other plugins might go here, e.g., plugins: [react(), tsconfigPaths()],
  plugins: [], // Or whatever plugins you have
  base: '/static/', // <--- THIS IS THE CRITICAL LINE
  build: {
    outDir: 'dist', // Ensure this is 'dist'
    // You might also need to explicitly list publicDir if it's not 'public' by default
    // publicDir: 'public',
  },
  // ... other configurations
})