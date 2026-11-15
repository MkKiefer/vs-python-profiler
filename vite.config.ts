/**
 * Builds the dashboard webview (Vue) into dist/webview.js + dist/webview.css and
 * configures Vitest for its specs. The extension host is built by esbuild.mjs.
 */
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';
import { NodeTypes, type NodeTransform } from '@vue/compiler-core';

/** Production bundles carry no `data-testid` attributes, static or bound. */
const stripTestIds: NodeTransform = (node) => {
  if (node.type !== NodeTypes.ELEMENT) return;
  node.props = node.props.filter((prop) => {
    if (prop.type === NodeTypes.ATTRIBUTE) return prop.name !== 'data-testid';
    const arg = prop.arg;
    return !(prop.name === 'bind' && arg?.type === NodeTypes.SIMPLE_EXPRESSION && arg.content === 'data-testid');
  });
};

export default defineConfig(({ mode }) => {
  const production = mode === 'production';
  return {
    plugins: [
      vue({ template: { compilerOptions: { nodeTransforms: production ? [stripTestIds] : [] } } }),
      tailwindcss(),
    ],
    define: { 'process.env.NODE_ENV': JSON.stringify(production ? 'production' : 'development') },
    build: {
      outDir: 'dist',
      emptyOutDir: false, // dist/ also holds the extension bundle
      sourcemap: !production,
      minify: production,
      target: 'es2022',
      lib: {
        entry: 'src/webview/main.ts',
        formats: ['iife'],
        name: 'VsvspyprofDashboard',
        fileName: () => 'webview.js',
        cssFileName: 'webview',
      },
    },
    test: {
      environment: 'jsdom',
      include: ['test/webview/**/*.spec.ts'],
      setupFiles: ['test/webview/support/setup.ts'],
    },
  };
});
