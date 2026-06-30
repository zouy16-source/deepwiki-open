// @nuxt/ui design tokens. `primary` ≈ the VSCode blue accent the app already uses;
// surfaces/borders keep coming from our CSS variables (--background, --card-bg, …).
export default defineAppConfig({
  ui: {
    colors: {
      primary: 'blue',
      neutral: 'neutral',
    },
  },
})
