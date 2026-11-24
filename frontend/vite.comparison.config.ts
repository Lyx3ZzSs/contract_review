import {defineConfig,mergeConfig} from 'vite'
import base from './vite.config'
// Separate cache prevents concurrent production-workbench dev servers from invalidating this probe.
export default mergeConfig(base,defineConfig({
 cacheDir:'node_modules/.vite-comparison',
 server:{port:5176,strictPort:true,proxy:{'/api':'http://127.0.0.1:8011'}},
 optimizeDeps:{esbuildOptions:{target:'esnext'},include:['@docx-editor.dev/core/editor'],exclude:['@docx-editor.dev/fonts','@docx-editor.dev/fonts-cjk/browser']},
}))
