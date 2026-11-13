// For tools that read .ts files without Vue support (ESLint's TypeScript service).
// vue-tsc resolves the real .vue files, which take precedence over this declaration.
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent;
  export default component;
}
